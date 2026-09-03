from __future__ import annotations

from datetime import datetime
import base64
import json
import os
from pathlib import Path
import tempfile
import threading

from domain.models import (
    DEFAULT_STUDY_ORDER,
    DEFAULT_REMINDER_INTERVAL_MINUTES,
    DEFAULT_REVIEW_BATCH_SIZE,
    MAX_REMINDER_INTERVAL_MINUTES,
    MIN_REMINDER_INTERVAL_MINUTES,
    ReviewState,
    VocabularyEntry,
)
from domain.dictation import DictationDraft, DictationDraftSyncMetadata, MarkMode
from domain.dictation_sync import DictationDraftSyncEnvelope
from infrastructure.catalog import entry_from_payload
from infrastructure.draft_cipher import (
    DraftCipher,
    default_draft_cipher,
)


SCHEMA_VERSION = 1


class JsonLearningRepository:
    def __init__(
        self,
        data_dir: Path,
        catalog_entries: list[VocabularyEntry] | None = None,
        *,
        draft_cipher: DraftCipher | None = None,
        cipher: DraftCipher | None = None,
    ):
        if draft_cipher is not None and cipher is not None:
            raise ValueError("pass either draft_cipher or cipher")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "learning-state.json"
        self._lock = threading.RLock()
        # The cipher is an infrastructure dependency.  DPAPI is the default
        # on Windows; tests and non-Windows tooling can inject a test cipher.
        self._draft_cipher: DraftCipher = draft_cipher or cipher or default_draft_cipher()
        # A legacy plaintext draft may be readable during a one-time upgrade
        # even when the current host cannot access DPAPI (for example, a
        # non-Windows test runner).  Keep that value process-local only; the
        # state serializer below strips it before any subsequent write.
        self._legacy_plaintext_draft: DictationDraft | None = None
        self._catalog = {item.word_id: item for item in (catalog_entries or [])}
        self._user_entries: dict[str, VocabularyEntry] = {}
        self._reviews: dict[str, ReviewState] = {}
        self._activity: dict[str, list[str]] = {}
        self._tag_overrides: dict[str, set[str]] = {}
        self._settings: dict[str, object] = {
            "fontScale": 1.0,
            "reviewBatchSize": DEFAULT_REVIEW_BATCH_SIZE,
            "studyOrder": DEFAULT_STUDY_ORDER,
            "studyLevels": [],
            "reviewLevels": [],
            "reminderLevels": [],
            "reminderEnabled": False,
            "reminderIntervalMinutes": DEFAULT_REMINDER_INTERVAL_MINUTES,
            "markMode": MarkMode.ASK.value,
            # The draft is a complete, versioned JSON object.  Keeping it in
            # the existing state envelope preserves atomic writes and allows
            # older installations to ignore the new key safely.
            "dictationDraft": None,
            # The last remote revision survives a local/remote tombstone so a
            # subsequent fresh draft still uses optimistic concurrency.  It
            # is encrypted independently because a tombstone is not an editor
            # draft and must not be restored as one.
            "dictationDraftSyncMetadata": None,
            "dictationLastSyncedEnvelope": None,
            "dictationConflictBackups": [],
        }
        self._load()

    def _load(self) -> None:
        if not self.state_path.is_file():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        for raw in payload.get("userEntries", []):
            entry = entry_from_payload(raw, source="user")
            if entry is not None and entry.word_id not in self._catalog:
                self._user_entries[entry.word_id] = entry
        reviews = payload.get("reviews", {})
        if isinstance(reviews, dict):
            for word_id, raw in reviews.items():
                if isinstance(raw, dict):
                    self._reviews[str(word_id)] = ReviewState.from_dict(str(word_id), raw)
        activity = payload.get("activity", {})
        if isinstance(activity, dict):
            self._activity = {
                str(day): list(dict.fromkeys(str(word_id) for word_id in word_ids))
                for day, word_ids in activity.items()
                if isinstance(word_ids, list)
            }
        settings = payload.get("settings", {})
        if isinstance(settings, dict):
            self._settings.update(settings)
        # Accept the standalone key used by the cross-platform draft
        # contract as well as the nested settings form written by v1 clients.
        if "dictationDraft" in payload and (
            not isinstance(settings, dict) or "dictationDraft" not in settings
        ):
            self._settings["dictationDraft"] = payload.get("dictationDraft")
        if "dictationDraftSyncMetadata" in payload and (
            not isinstance(settings, dict) or "dictationDraftSyncMetadata" not in settings
        ):
            self._settings["dictationDraftSyncMetadata"] = payload.get(
                "dictationDraftSyncMetadata",
            )
        overrides = payload.get("tagOverrides", {})
        if isinstance(overrides, dict):
            self._tag_overrides = {
                str(word_id): {str(tag).strip().casefold() for tag in tags if str(tag).strip()}
                for word_id, tags in overrides.items()
                if isinstance(tags, list)
            }
        # Migrate only after every other state section has been loaded.  The
        # migration rewrites the whole atomic state file; doing it earlier
        # would accidentally serialize an as-yet-unloaded tag-overrides map.
        self._migrate_plaintext_draft_if_possible()

    def _payload(self) -> dict:
        # Never write a legacy/plain object back to disk.  A failed migration
        # must not turn an unrelated settings update into a plaintext draft
        # write.  The process-local value remains available through
        # ``get_dictation_draft`` until the user saves or clears it.
        stored_draft = self._settings.get("dictationDraft")
        if stored_draft is not None and not self._is_encrypted_draft(stored_draft):
            stored_draft = None
        stored_sync_metadata = self._settings.get("dictationDraftSyncMetadata")
        if stored_sync_metadata is not None and not self._is_encrypted_draft(stored_sync_metadata):
            stored_sync_metadata = None
        stored_last_synced = self._settings.get("dictationLastSyncedEnvelope")
        if stored_last_synced is not None and not self._is_encrypted_draft(stored_last_synced):
            stored_last_synced = None
        stored_conflicts = self._settings.get("dictationConflictBackups", [])
        if not isinstance(stored_conflicts, list):
            stored_conflicts = []
        stored_conflicts = [
            item for item in stored_conflicts if self._is_encrypted_draft(item)
        ][:3]
        settings = dict(self._settings)
        settings["dictationDraft"] = stored_draft
        settings["dictationDraftSyncMetadata"] = stored_sync_metadata
        settings["dictationLastSyncedEnvelope"] = stored_last_synced
        settings["dictationConflictBackups"] = stored_conflicts
        return {
            "schemaVersion": SCHEMA_VERSION,
            "userEntries": [entry.to_dict() for entry in self._user_entries.values()],
            "reviews": {word_id: state.to_dict() for word_id, state in self._reviews.items()},
            "activity": self._activity,
            "tagOverrides": {word_id: sorted(tags) for word_id, tags in self._tag_overrides.items()},
            "settings": settings,
            "dictationDraft": stored_draft,
        }

    @staticmethod
    def _is_encrypted_draft(value: object) -> bool:
        return (
            isinstance(value, dict)
            and str(value.get("format", "")).casefold() == "dpapi-v1"
            and isinstance(value.get("ciphertext"), str)
        )

    def _encrypt_draft(self, draft: DictationDraft) -> dict:
        plaintext = draft.canonical_json_bytes()
        try:
            ciphertext = self._draft_cipher.encrypt(plaintext)
        except Exception as error:
            raise RuntimeError("本机无法保护默写草稿") from error
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise RuntimeError("本机无法保护默写草稿")
        return {
            "format": "dpapi-v1",
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def _decrypt_draft(self, value: object) -> DictationDraft | None:
        if not self._is_encrypted_draft(value):
            # A plain object is an old v1 record.  It is accepted for one-way
            # migration, but new writes never retain this representation.
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (TypeError, UnicodeError, json.JSONDecodeError):
                    return None
            return DictationDraft.from_dict(value)
        encoded = value.get("ciphertext")
        try:
            ciphertext = base64.b64decode(str(encoded), validate=True)
            if not ciphertext:
                return None
            plaintext = self._draft_cipher.decrypt(ciphertext)
            if not isinstance(plaintext, bytes):
                return None
            payload = json.loads(plaintext.decode("utf-8"))
            return DictationDraft.from_dict(payload)
        except Exception:
            return None

    def _encrypt_dictation_sync_metadata(
        self,
        metadata: DictationDraftSyncMetadata,
    ) -> dict:
        plaintext = metadata.canonical_json().encode("utf-8")
        try:
            ciphertext = self._draft_cipher.encrypt(plaintext)
        except Exception as error:
            raise RuntimeError("本机无法保护默写同步元数据") from error
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise RuntimeError("本机无法保护默写同步元数据")
        return {
            "format": "dpapi-v1",
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def _decrypt_dictation_sync_metadata(
        self,
        value: object,
    ) -> DictationDraftSyncMetadata | None:
        if not self._is_encrypted_draft(value):
            return None
        encoded = value.get("ciphertext")
        try:
            ciphertext = base64.b64decode(str(encoded), validate=True)
            if not ciphertext:
                return None
            plaintext = self._draft_cipher.decrypt(ciphertext)
            if not isinstance(plaintext, bytes):
                return None
            payload = json.loads(plaintext.decode("utf-8"))
            if not isinstance(payload, dict):
                return None
            return DictationDraftSyncMetadata.from_dict(payload)
        except Exception:
            return None

    def _encrypt_dictation_sync_envelope(
        self,
        envelope: DictationDraftSyncEnvelope,
    ) -> dict:
        try:
            ciphertext = self._draft_cipher.encrypt(envelope.canonical_json_bytes())
        except Exception as error:
            raise RuntimeError("本机无法保护默写同步备份") from error
        if not isinstance(ciphertext, bytes) or not ciphertext:
            raise RuntimeError("本机无法保护默写同步备份")
        return {
            "format": "dpapi-v1",
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def _decrypt_dictation_sync_envelope(
        self,
        value: object,
    ) -> DictationDraftSyncEnvelope | None:
        if not self._is_encrypted_draft(value):
            return None
        try:
            ciphertext = base64.b64decode(str(value.get("ciphertext")), validate=True)
            if not ciphertext:
                return None
            plaintext = self._draft_cipher.decrypt(ciphertext)
            if not isinstance(plaintext, bytes):
                return None
            payload = json.loads(plaintext.decode("utf-8"))
            return DictationDraftSyncEnvelope.from_dict(payload)
        except Exception:
            return None

    def _migrate_plaintext_draft_if_possible(self) -> None:
        value = self._settings.get("dictationDraft")
        if value is None or self._is_encrypted_draft(value):
            return
        draft = self._decrypt_draft(value)
        if draft is None:
            # An invalid legacy object is neither recoverable nor safe to keep
            # as ordinary JSON.  Remove it during the one-way migration.
            self._settings["dictationDraft"] = None
            try:
                self._save_locked()
            except OSError:
                pass
            return
        try:
            self._settings["dictationDraft"] = self._encrypt_draft(draft)
            # Rewrite immediately so a process crash after loading cannot
            # leave the legacy plaintext representation on disk.
            self._save_locked()
        except RuntimeError:
            # Fail closed when the platform cipher is unavailable: retain the
            # value only in memory for this process, but never manufacture a
            # fake "encrypted" blob or claim migration succeeded.  `_payload`
            # also strips the legacy object if another setting is saved later.
            self._legacy_plaintext_draft = draft
            self._settings["dictationDraft"] = None
            try:
                self._save_locked()
            except OSError:
                pass

    def _save_locked(self) -> None:
        text = json.dumps(self._payload(), ensure_ascii=False, indent=2)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="learning-state-", suffix=".tmp", dir=self.data_dir
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.state_path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)

    def all_entries(self) -> list[VocabularyEntry]:
        with self._lock:
            merged = dict(self._catalog)
            merged.update(self._user_entries)
            return sorted((self._with_tag_override(item) for item in merged.values()), key=lambda item: item.word_id)

    def _with_tag_override(self, entry: VocabularyEntry) -> VocabularyEntry:
        tags = self._tag_overrides.get(entry.word_id)
        return entry if tags is None else VocabularyEntry(
            word_id=entry.word_id, word=entry.word, meaning=entry.meaning,
            examples=entry.examples, phonetic=entry.phonetic, level=entry.level,
            tags=tuple(sorted(tags)), mnemonic=entry.mnemonic, source=entry.source,
        )

    def add_entries(self, entries: list[VocabularyEntry]) -> int:
        added = 0
        with self._lock:
            known = set(self._catalog) | set(self._user_entries)
            for entry in entries:
                if entry.word_id in known or not entry.is_study_ready():
                    continue
                self._user_entries[entry.word_id] = entry
                known.add(entry.word_id)
                added += 1
            if added:
                self._save_locked()
        return added

    def review_state(self, word_id: str) -> ReviewState:
        with self._lock:
            return self._reviews.get(word_id, ReviewState(word_id=word_id))

    def all_review_states(self) -> list[ReviewState]:
        with self._lock:
            return list(self._reviews.values())

    def save_review_state(self, state: ReviewState) -> None:
        with self._lock:
            self._reviews[state.word_id] = state
            self._save_locked()

    def record_activity(self, word_id: str, reviewed_at_utc: float) -> None:
        local_day = datetime.fromtimestamp(reviewed_at_utc).strftime("%Y-%m-%d")
        with self._lock:
            words = self._activity.setdefault(local_day, [])
            if word_id not in words:
                words.append(word_id)
            for old_day in sorted(self._activity)[:-120]:
                del self._activity[old_day]
            self._save_locked()

    def reviewed_count_for_local_day(self, local_day: str) -> int:
        with self._lock:
            return len(self._activity.get(local_day, []))

    def get_font_scale(self) -> float:
        with self._lock:
            try:
                return min(1.4, max(0.9, float(self._settings.get("fontScale", 1.0))))
            except (TypeError, ValueError):
                return 1.0

    def set_font_scale(self, scale: float) -> None:
        with self._lock:
            self._settings["fontScale"] = min(1.4, max(0.9, float(scale)))
            self._save_locked()

    def get_review_batch_size(self) -> int:
        with self._lock:
            try:
                return max(1, int(self._settings.get("reviewBatchSize", DEFAULT_REVIEW_BATCH_SIZE)))
            except (TypeError, ValueError):
                return DEFAULT_REVIEW_BATCH_SIZE

    def set_review_batch_size(self, size: int) -> None:
        with self._lock:
            self._settings["reviewBatchSize"] = max(1, int(size))
            self._save_locked()

    def get_study_order(self) -> str:
        with self._lock:
            value = str(self._settings.get("studyOrder", DEFAULT_STUDY_ORDER))
            return value if value in {"alphabetical", "random"} else DEFAULT_STUDY_ORDER

    def set_study_order(self, order: str) -> None:
        if order not in {"alphabetical", "random"}:
            raise ValueError("学习顺序必须为 alphabetical 或 random")
        with self._lock:
            self._settings["studyOrder"] = order
            self._save_locked()

    def _get_levels(self, key: str) -> set[str]:
        with self._lock:
            raw = self._settings.get(key, [])
            if isinstance(raw, str):
                raw = raw.replace(",", "|").split("|")
            if not isinstance(raw, list):
                return set()
            return {str(item).strip().upper() for item in raw if str(item).strip()}

    def _set_levels(self, key: str, levels: set[str]) -> None:
        with self._lock:
            self._settings[key] = sorted({str(item).strip().upper() for item in levels if str(item).strip()})
            self._save_locked()

    def get_study_levels(self) -> set[str]:
        return self._get_levels("studyLevels")

    def set_study_levels(self, levels: set[str]) -> None:
        self._set_levels("studyLevels", levels)

    def get_review_levels(self) -> set[str]:
        return self._get_levels("reviewLevels")

    def set_review_levels(self, levels: set[str]) -> None:
        self._set_levels("reviewLevels", levels)

    def get_reminder_levels(self) -> set[str]:
        return self._get_levels("reminderLevels")

    def set_reminder_levels(self, levels: set[str]) -> None:
        self._set_levels("reminderLevels", levels)

    def update_entry_labels(self, word_ids: set[str], level: str, tags: set[str]) -> int:
        normalized_ids = {str(item) for item in word_ids}
        normalized_level = level.strip() or "custom"
        normalized_tags = tuple(sorted({tag.strip() for tag in tags if tag.strip()}))
        updated = 0
        with self._lock:
            for word_id in normalized_ids:
                entry = self._user_entries.get(word_id)
                if entry is None:
                    continue
                self._user_entries[word_id] = VocabularyEntry(
                    word_id=entry.word_id,
                    word=entry.word,
                    meaning=entry.meaning,
                    examples=entry.examples,
                    phonetic=entry.phonetic,
                    level=normalized_level,
                    tags=normalized_tags,
                    mnemonic=entry.mnemonic,
                    source=entry.source,
                )
                self._tag_overrides[word_id] = set(normalized_tags)
                updated += 1
            if updated:
                self._save_locked()
        return updated

    def update_tags(self, word_ids: set[str], add: set[str], remove: set[str]) -> int:
        normalized_ids = {str(item) for item in word_ids}
        normalized_add = {str(tag).strip().casefold() for tag in add if str(tag).strip()}
        normalized_remove = {str(tag).strip().casefold() for tag in remove if str(tag).strip()}
        with self._lock:
            known = set(self._catalog) | set(self._user_entries)
            ids = normalized_ids & known
            for word_id in ids:
                entry = self._catalog.get(word_id) or self._user_entries.get(word_id)
                if entry is None:
                    continue
                current = set(self._with_tag_override(entry).tags)
                self._tag_overrides[word_id] = (current | normalized_add) - normalized_remove
            if ids:
                self._save_locked()
            return len(ids)

    def get_mark_mode(self) -> MarkMode:
        with self._lock:
            try:
                return MarkMode(str(self._settings.get("markMode", MarkMode.ASK.value)).upper())
            except ValueError:
                return MarkMode.ASK

    def set_mark_mode(self, mode: MarkMode) -> None:
        resolved = mode if isinstance(mode, MarkMode) else MarkMode(str(mode).upper())
        with self._lock:
            self._settings["markMode"] = resolved.value
            self._save_locked()

    def get_dictation_draft(self) -> DictationDraft | None:
        """Load the last explicitly saved 默写纸 draft, if it is valid."""
        with self._lock:
            if self._legacy_plaintext_draft is not None:
                return self._legacy_plaintext_draft
            return self._decrypt_draft(self._settings.get("dictationDraft"))

    def get_dictation_sync_metadata(self) -> DictationDraftSyncMetadata | None:
        """Return the encrypted last-known server revision, if any."""
        with self._lock:
            return self._decrypt_dictation_sync_metadata(
                self._settings.get("dictationDraftSyncMetadata"),
            )

    def save_dictation_sync_metadata(
        self,
        metadata: DictationDraftSyncMetadata,
    ) -> None:
        if not isinstance(metadata, DictationDraftSyncMetadata):
            raise TypeError("metadata must be DictationDraftSyncMetadata")
        with self._lock:
            self._settings["dictationDraftSyncMetadata"] = (
                self._encrypt_dictation_sync_metadata(metadata)
            )
            self._save_locked()

    def get_last_synced_dictation_envelope(
        self,
    ) -> DictationDraftSyncEnvelope | None:
        with self._lock:
            return self._decrypt_dictation_sync_envelope(
                self._settings.get("dictationLastSyncedEnvelope"),
            )

    def save_last_synced_dictation_envelope(
        self,
        envelope: DictationDraftSyncEnvelope,
    ) -> None:
        if not isinstance(envelope, DictationDraftSyncEnvelope):
            raise TypeError("envelope must be DictationDraftSyncEnvelope")
        with self._lock:
            self._settings["dictationLastSyncedEnvelope"] = (
                self._encrypt_dictation_sync_envelope(envelope)
            )
            self._save_locked()

    def get_dictation_conflict_backups(
        self,
    ) -> tuple[DictationDraftSyncEnvelope, ...]:
        with self._lock:
            stored = self._settings.get("dictationConflictBackups", [])
            if not isinstance(stored, list):
                return ()
            decoded = (
                self._decrypt_dictation_sync_envelope(value)
                for value in stored[:3]
            )
            return tuple(value for value in decoded if value is not None)

    def add_dictation_conflict_backup(
        self,
        envelope: DictationDraftSyncEnvelope,
    ) -> None:
        if not isinstance(envelope, DictationDraftSyncEnvelope):
            raise TypeError("envelope must be DictationDraftSyncEnvelope")
        canonical = envelope.canonical_json()
        with self._lock:
            existing = [
                value
                for value in self.get_dictation_conflict_backups()
                if value.canonical_json() != canonical
            ]
            retained = [envelope, *existing][:3]
            self._settings["dictationConflictBackups"] = [
                self._encrypt_dictation_sync_envelope(value) for value in retained
            ]
            self._save_locked()

    def save_dictation_draft(self, draft: DictationDraft) -> None:
        """Persist a complete draft atomically through the normal state file."""
        if not isinstance(draft, DictationDraft):
            raise TypeError("draft must be a DictationDraft")
        with self._lock:
            self._legacy_plaintext_draft = None
            self._settings["dictationDraft"] = self._encrypt_draft(draft)
            try:
                self._settings["dictationDraftSyncMetadata"] = (
                    self._encrypt_dictation_sync_metadata(draft.sync_metadata)
                )
            except RuntimeError:
                # Draft persistence must remain available on hosts where the
                # optional metadata cipher is unavailable (for example,
                # non-Windows test tooling).  The draft itself has already
                # passed the platform cipher boundary; metadata will be
                # refreshed on the next successful sync acknowledgement.
                pass
            self._save_locked()

    def clear_dictation_draft(self) -> None:
        """Delete the saved draft while retaining its encrypted sync token."""
        with self._lock:
            self._legacy_plaintext_draft = None
            self._settings["dictationDraft"] = None
            self._save_locked()

    def get_reminder_enabled(self) -> bool:
        with self._lock:
            return self._settings.get("reminderEnabled", False) is True

    def set_reminder_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._settings["reminderEnabled"] = bool(enabled)
            self._save_locked()

    def get_reminder_interval_minutes(self) -> float:
        with self._lock:
            try:
                return min(
                    MAX_REMINDER_INTERVAL_MINUTES,
                    max(
                        MIN_REMINDER_INTERVAL_MINUTES,
                        float(self._settings.get(
                            "reminderIntervalMinutes",
                            DEFAULT_REMINDER_INTERVAL_MINUTES,
                        )),
                    ),
                )
            except (TypeError, ValueError):
                return DEFAULT_REMINDER_INTERVAL_MINUTES

    def set_reminder_interval_minutes(self, minutes: float) -> None:
        with self._lock:
            self._settings["reminderIntervalMinutes"] = min(
                MAX_REMINDER_INTERVAL_MINUTES,
                max(MIN_REMINDER_INTERVAL_MINUTES, float(minutes)),
            )
            self._save_locked()
