from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import random
import time

from domain.models import (
    DEFAULT_STUDY_ORDER,
    MAX_REMINDER_INTERVAL_MINUTES,
    MIN_REMINDER_INTERVAL_MINUTES,
    ImportReport,
    LearntWord,
    ReviewRating,
    ReviewState,
    VocabularyEntry,
    normalize_word_id,
)
from domain.dictation import (
    DictationDocument,
    DictationDraftSyncMetadata,
    DictationDraft,
    DictationFormat,
    DictationOptions,
    MarkMode,
    build_document,
    dictation_range_ids,
    nearest_dictation_id,
)
from domain.word_bubbles import BubbleDefinition, resolve_bubble_definition, tokenize_english
from domain.groups import (
    GROUP_ORDER,
    canonical_memberships,
    classify_groups,
    group_label,
    normalize_group_membership,
)
from application.ports import DictationExporter, ExportedDictation
from application.ports import DictationDraftSyncPort
from domain.ports import LearningRepository, WordsLearntRepository
from domain.dictation_sync import (
    DictationDraftSyncConflict,
    DictationDraftSyncEnvelope,
    DictationDraftSyncResult,
    DictationDraftSyncStatus,
    make_sync_envelope,
    reconcile_sync_envelopes,
)
from domain.scheduler import SECONDS_PER_DAY, retention_at, schedule_review


@dataclass(frozen=True)
class DashboardSnapshot:
    total_words: int
    due_now: int
    new_words: int
    reviewed_today: int
    due_next_7_days: int
    due_next_30_days: int


@dataclass(frozen=True)
class LibraryGroup:
    key: str
    label: str
    count: int


class LearningService:
    def __init__(
        self,
        repository: LearningRepository,
        csv_importer=None,
        words_learnt_repository: WordsLearntRepository | None = None,
        dictation_exporter: DictationExporter | None = None,
        dictation_draft_sync: DictationDraftSyncPort | None = None,
    ):
        self.repository = repository
        self.csv_importer = csv_importer
        self.words_learnt_repository = words_learnt_repository
        self.dictation_exporter = dictation_exporter
        self.dictation_draft_sync = dictation_draft_sync
        # A cleared draft has no persisted object from which to recover the
        # last server token.  Repositories that support the optional metadata
        # slot keep it encrypted across restarts; lightweight test doubles can
        # omit the slot and retain the conservative in-memory fallback.
        metadata_getter = getattr(repository, "get_dictation_sync_metadata", None)
        try:
            restored_metadata = metadata_getter() if callable(metadata_getter) else None
        except Exception:
            # A broken secure-store record must not prevent the local app from
            # starting; the in-memory default still keeps ordinary local mode
            # usable until a fresh sync response is observed.
            restored_metadata = None
        self._last_dictation_sync_metadata = (
            restored_metadata
            if isinstance(restored_metadata, DictationDraftSyncMetadata)
            else DictationDraftSyncMetadata()
        )
        self._migrate_legacy_review_states()

    def _migrate_legacy_review_states(self) -> int:
        if self.words_learnt_repository is None:
            return 0
        known = {
            word.word_id
            for word in self.words_learnt_repository.all_learnt_words()
        }
        migrated = []
        for state in self.repository.all_review_states():
            if state.word_id in known or state.last_reviewed_at_utc is None:
                continue
            migrated.append(LearntWord(
                word_id=state.word_id,
                weight=0.2,
                learnt_at_utc=state.last_reviewed_at_utc,
                last_reviewed_at_utc=state.last_reviewed_at_utc,
            ))
        return self.words_learnt_repository.save_learnt_words(migrated)

    def _learnt_by_id(self) -> dict[str, LearntWord]:
        if self.words_learnt_repository is None:
            return {
                state.word_id: LearntWord(
                    word_id=state.word_id,
                    weight=0.2,
                    learnt_at_utc=state.last_reviewed_at_utc or 0.0,
                    last_reviewed_at_utc=state.last_reviewed_at_utc or 0.0,
                )
                for state in self.repository.all_review_states()
                if state.last_reviewed_at_utc is not None
            }
        return {
            word.word_id: word
            for word in self.words_learnt_repository.all_learnt_words()
        }

    def dashboard(self, now_utc: float | None = None) -> DashboardSnapshot:
        now = time.time() if now_utc is None else now_utc
        entries = self.repository.all_entries()
        states = self.repository.all_review_states()
        learnt_ids = set(self._learnt_by_id())
        entry_ids = {entry.word_id for entry in entries}
        reviewed = [
            state for state in states
            if state.word_id in learnt_ids
            and state.word_id in entry_ids
            and state.last_reviewed_at_utc is not None
        ]
        due_now = sum(state.due_at_utc <= now for state in reviewed)
        local_day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        return DashboardSnapshot(
            total_words=len(entries),
            due_now=due_now,
            new_words=sum(entry.word_id not in learnt_ids for entry in entries),
            reviewed_today=self.repository.reviewed_count_for_local_day(local_day),
            due_next_7_days=sum(now < state.due_at_utc <= now + 7 * SECONDS_PER_DAY for state in reviewed),
            due_next_30_days=sum(now < state.due_at_utc <= now + 30 * SECONDS_PER_DAY for state in reviewed),
        )

    def next_card(
        self,
        now_utc: float | None = None,
        exclude_id: str = "",
        rng: random.Random | None = None,
    ) -> VocabularyEntry | None:
        entries = self.repository.all_entries()
        learnt_ids = set(self._learnt_by_id())
        fresh = [
            entry for entry in entries
            if entry.word_id not in learnt_ids
            and entry.word_id != exclude_id
            and self._matches_levels(entry, self.study_levels())
        ]
        if fresh:
            if self.study_order() == "alphabetical":
                return sorted(fresh, key=lambda item: item.word_id)[0]
            return (rng or random.SystemRandom()).choice(fresh)
        return None

    @staticmethod
    def _matches_levels(entry: VocabularyEntry, levels: set[str]) -> bool:
        return not levels or bool(entry.levels.intersection({item.upper() for item in levels}))

    def study_order(self) -> str:
        getter = getattr(self.repository, "get_study_order", None)
        value = getter() if getter else DEFAULT_STUDY_ORDER
        return value if value in {"alphabetical", "random"} else DEFAULT_STUDY_ORDER

    def set_study_order(self, order: str) -> str:
        if order not in {"alphabetical", "random"}:
            raise ValueError("学习顺序必须为 alphabetical 或 random")
        setter = getattr(self.repository, "set_study_order", None)
        if setter:
            setter(order)
        return order

    def study_levels(self) -> set[str]:
        getter = getattr(self.repository, "get_study_levels", None)
        return set(getter()) if getter else set()

    def set_study_levels(self, levels: set[str]) -> set[str]:
        normalized = {str(item).strip().upper() for item in levels if str(item).strip()}
        setter = getattr(self.repository, "set_study_levels", None)
        if setter:
            setter(normalized)
        return normalized

    def review_levels(self) -> set[str]:
        getter = getattr(self.repository, "get_review_levels", None)
        return set(getter()) if getter else set()

    def set_review_levels(self, levels: set[str]) -> set[str]:
        normalized = {str(item).strip().upper() for item in levels if str(item).strip()}
        setter = getattr(self.repository, "set_review_levels", None)
        if setter:
            setter(normalized)
        return normalized

    def reminder_levels(self) -> set[str]:
        getter = getattr(self.repository, "get_reminder_levels", None)
        return set(getter()) if getter else set()

    def set_reminder_levels(self, levels: set[str]) -> set[str]:
        normalized = {str(item).strip().upper() for item in levels if str(item).strip()}
        invalid = normalized - {"CET4", "CET6", "CUSTOM"}
        if invalid:
            raise ValueError("提醒词汇组只能包含 CET4、CET6 或 custom")
        setter = getattr(self.repository, "set_reminder_levels", None)
        if setter:
            setter(normalized)
        return normalized

    def available_levels(self) -> list[str]:
        levels = {level for entry in self.repository.all_entries() for level in entry.levels}
        return sorted(levels or {"CUSTOM"})

    def available_program_tags(self) -> set[str]:
        return {"cet4", "cet6", "gk", "zk", "evaluated"}

    def word_bubble(self, token: str, context_example: str = "") -> BubbleDefinition:
        """Resolve an example token without exposing the repository to presentation."""
        return resolve_bubble_definition(self.repository.all_entries(), token, context_example)

    @staticmethod
    def example_tokens(text: str):
        return tokenize_english(text)

    def dictation_candidates(
        self,
        count: int,
        include_evaluated: bool = False,
        group: str | None = None,
        rng: random.Random | None = None,
        candidate_ids: set[str] | None = None,
        random_candidate_ids: set[str] | None = None,
    ) -> list[VocabularyEntry]:
        if count < 0:
            raise ValueError("默写词数不能为负数")
        pool = sorted(
            {entry.word_id: entry for entry in self._dictation_pool(include_evaluated, group)}.values(),
            key=lambda item: item.word_id,
        )
        # ``candidate_ids`` is an explicit random subset.  ``None`` retains
        # the legacy whole-group behavior; an empty set deliberately yields no
        # candidates so callers can distinguish "not configured" from "empty".
        if random_candidate_ids is not None:
            candidate_ids = random_candidate_ids
        if candidate_ids is not None:
            wanted = {normalize_word_id(str(value)) for value in candidate_ids}
            pool = [entry for entry in pool if normalize_word_id(entry.word_id) in wanted]
        randomizer = rng or random.SystemRandom()
        result = []
        for _ in range(min(count, len(pool))):
            result.append(pool.pop(randomizer.randrange(len(pool))))
        return result

    def _dictation_pool(
        self,
        include_evaluated: bool = False,
        group: str | None = None,
    ) -> list[VocabularyEntry]:
        base = [
            entry for entry in self.repository.all_entries()
            if include_evaluated or "evaluated" not in {tag.casefold() for tag in entry.tags}
        ]
        if not group or group == "all":
            return base
        return self._entries_in_group(base, group)

    def dictation_pool(
        self,
        include_evaluated: bool = False,
        group: str | None = None,
    ) -> list[VocabularyEntry]:
        return self._dictation_pool(include_evaluated, group)

    def selected_dictation_candidates(
        self,
        word_ids: set[str],
        include_evaluated: bool = False,
        group: str | None = None,
    ) -> list[VocabularyEntry]:
        wanted = {normalize_word_id(str(value)) for value in word_ids}
        base = [
            entry for entry in self.repository.all_entries()
            if normalize_word_id(entry.word_id) in wanted
            and (include_evaluated or "evaluated" not in {tag.casefold() for tag in entry.tags})
        ]
        if not group or group == "all":
            return base
        return self._entries_in_group(base, group)

    def build_dictation_document(
        self,
        options: DictationOptions,
        *,
        count: int | None = None,
        include_evaluated: bool = False,
        group: str | None = None,
        word_ids: set[str] | None = None,
        entries: list[VocabularyEntry] | None = None,
        rng: random.Random | None = None,
        candidate_ids: set[str] | None = None,
        random_candidate_ids: set[str] | None = None,
    ) -> DictationDocument:
        selected_entries = (entries if entries is not None else
                            self.selected_dictation_candidates(word_ids, include_evaluated, group)
                            if word_ids is not None else
                            self.dictation_candidates(count or 0, include_evaluated, group, rng, candidate_ids, random_candidate_ids))
        return build_document(selected_entries, options)

    def dictation_draft(self) -> DictationDraft | None:
        getter = getattr(self.repository, "get_dictation_draft", None)
        draft = getter() if getter else None
        if draft is not None and isinstance(draft.sync_metadata, DictationDraftSyncMetadata):
            self._last_dictation_sync_metadata = draft.sync_metadata
        return draft

    def dictation_sync_metadata(self) -> DictationDraftSyncMetadata:
        """Return the latest local or tombstone revision without a draft."""
        return self._last_dictation_sync_metadata

    def save_dictation_draft(self, draft: DictationDraft) -> None:
        saver = getattr(self.repository, "save_dictation_draft", None)
        if saver is None:
            raise RuntimeError("Dictation draft storage is not configured")
        draft = self._inherit_sync_metadata(draft)
        saver(draft)
        if isinstance(draft.sync_metadata, DictationDraftSyncMetadata):
            self._last_dictation_sync_metadata = draft.sync_metadata

    def _inherit_sync_metadata(self, draft: DictationDraft) -> DictationDraft:
        """Carry the last server token into a newly edited local draft.

        Presentation creates an immutable draft from controls, so an edit
        naturally starts with the domain defaults (empty account, revision
        ``0``).  Replacing those defaults with the last observed metadata is
        what keeps the next push guarded by ``If-Match``.  Explicit metadata
        supplied by a remote/conflict resolution is always preserved.
        """
        if not isinstance(draft, DictationDraft):
            return draft
        current = draft.sync_metadata
        if not isinstance(current, DictationDraftSyncMetadata):
            return draft
        inherited = self._last_dictation_sync_metadata
        compatible_account = (
            not current.account_id
            or not inherited.account_id
            or current.account_id == inherited.account_id
        )
        if not (
            compatible_account
            and inherited.account_id
            and current.revision in {"", "0"}
            and inherited.revision not in {"", "0"}
        ):
            return draft
        return replace(
            draft,
            sync_metadata=DictationDraftSyncMetadata(
                account_id=current.account_id or inherited.account_id,
                revision=inherited.revision,
                updated_at_utc=current.updated_at_utc or inherited.updated_at_utc,
                deleted=False,
            ),
        )

    def save_and_sync_dictation_draft(
        self,
        draft: DictationDraft,
        account_id: str,
        *,
        revision: str | None = None,
        updated_at_utc: float | None = None,
    ) -> DictationDraftSyncResult:
        """Persist locally first, then attempt an optional remote push.

        Local persistence deliberately happens before size/configuration checks;
        an unavailable or oversized sync payload must never discard an editor
        save.
        """
        self.save_dictation_draft(draft)
        return self.push_dictation_draft(
            account_id,
            draft=draft,
            revision=revision,
            updated_at_utc=updated_at_utc,
        )

    def clear_and_sync_dictation_draft(
        self,
        account_id: str,
        *,
        revision: str | None = None,
        updated_at_utc: float | None = None,
    ) -> DictationDraftSyncResult:
        """Clear local state and emit a tombstone through the optional port."""
        # Capture the previous token before deleting the local object.  A
        # tombstone with an empty/initial token would otherwise be an
        # unguarded overwrite of a remote edit.
        previous = self.dictation_draft()
        metadata = self.stage_dictation_tombstone(
            account_id,
            revision=revision,
            updated_at_utc=updated_at_utc,
        )
        result = self.push_dictation_draft(
            account_id,
            revision=metadata.revision,
            updated_at_utc=metadata.updated_at_utc,
            deleted=True,
        )
        # A revision conflict must leave the pre-delete snapshot available for
        # the user to choose.  Local-only/disabled deletion remains a valid
        # explicit local action, so only restore on an actual conflict.
        if result.status is DictationDraftSyncStatus.CONFLICT and previous is not None:
            self.save_dictation_draft(previous)
        return result

    def stage_dictation_tombstone(
        self,
        account_id: str = "",
        *,
        revision: str | None = None,
        updated_at_utc: float | None = None,
    ) -> DictationDraftSyncMetadata:
        """Persist a local deletion before optional asynchronous transport."""
        current_draft = self.dictation_draft()
        current = (
            current_draft.sync_metadata
            if current_draft is not None
            else self._last_dictation_sync_metadata
        )
        requested_account = str(account_id or "").strip()
        effective_account = requested_account or current.account_id
        if current.account_id and requested_account and current.account_id != requested_account:
            raise ValueError("local dictation draft belongs to a different account")
        effective_revision = current.revision if revision is None else revision
        metadata = DictationDraftSyncMetadata(
            account_id=effective_account,
            revision=effective_revision,
            updated_at_utc=time.time() if updated_at_utc is None else updated_at_utc,
            deleted=True,
        )
        self._last_dictation_sync_metadata = metadata
        saver = getattr(self.repository, "save_dictation_sync_metadata", None)
        if callable(saver):
            saver(metadata)
        self.clear_dictation_draft()
        return metadata

    def clear_dictation_draft(self) -> None:
        clearer = getattr(self.repository, "clear_dictation_draft", None)
        if clearer is not None:
            clearer()

    def pull_dictation_draft(
        self,
        account_id: str,
        *,
        apply: bool = True,
    ) -> DictationDraftSyncResult:
        """Pull an optional remote snapshot and apply only non-conflicting data.

        Local persistence remains the source of truth when the port is absent,
        disabled, or reports a conflict.  A remote tombstone clears the local
        snapshot only after the adapter explicitly returns ``TOMBSTONE``.

        ``apply=False`` performs the transport and reconciliation checks but
        leaves the repository untouched.  Presentation uses that mode for
        background pulls so a user edit cannot be overwritten before the Tk
        thread has had a chance to inspect its dirty state.
        """
        adapter = self.dictation_draft_sync
        if adapter is None:
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.DISABLED,
                message="dictation draft sync is not configured; local-only mode",
            )
        result = adapter.pull(account_id)
        envelope = result.envelope

        if envelope is not None and envelope.account_id.strip() != str(account_id).strip():
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.INVALID,
                message="sync response account_id does not match request",
            )

        # A pull conflict returned by an adapter may carry only the remote
        # envelope (HTTP 409 is the common case).  Complete it with the local
        # snapshot here so presentation always has both choices.
        local_draft = self.dictation_draft()
        local_envelope = self._local_sync_envelope(account_id, local_draft)
        if result.status is DictationDraftSyncStatus.CONFLICT:
            if result.conflict is not None or envelope is None or local_envelope is None:
                return result
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.CONFLICT,
                envelope=envelope,
                conflict=DictationDraftSyncConflict(local=local_envelope, remote=envelope),
                message=result.message or "remote dictation draft revision conflict",
            )

        # Adapter success is not sufficient on its own: compare the returned
        # snapshot with the locally stored revision before mutating disk.  A
        # remote tombstone with a different token is handled as a conflict.
        if envelope is not None and local_envelope is not None:
            reconciled = reconcile_sync_envelopes(local_envelope, envelope)
            if reconciled.status is DictationDraftSyncStatus.CONFLICT:
                return reconciled
            if reconciled.status is DictationDraftSyncStatus.INVALID:
                return reconciled

        if apply:
            return self.apply_pulled_dictation_draft(account_id, result)
        return result

    def apply_pulled_dictation_draft(
        self,
        account_id: str,
        result: DictationDraftSyncResult,
    ) -> DictationDraftSyncResult:
        """Apply a previously reconciled pull result to local storage.

        The local snapshot is read again immediately before mutation.  This
        second reconciliation closes the gap between a background network
        response and the UI callback: if the editor was saved in that gap,
        the remote response becomes a normal conflict instead of replacing it.
        """
        if result.status not in {
            DictationDraftSyncStatus.SYNCED,
            DictationDraftSyncStatus.TOMBSTONE,
        }:
            return result
        envelope = result.envelope
        if envelope is not None and envelope.account_id.strip() != str(account_id).strip():
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.INVALID,
                message="sync response account_id does not match request",
            )
        local_draft = self.dictation_draft()
        local_envelope = self._local_sync_envelope(account_id, local_draft)
        if envelope is not None and local_envelope is not None:
            reconciled = reconcile_sync_envelopes(local_envelope, envelope)
            if reconciled.status in {
                DictationDraftSyncStatus.CONFLICT,
                DictationDraftSyncStatus.INVALID,
            }:
                return reconciled
        if envelope is not None:
            if (
                result.status is DictationDraftSyncStatus.TOMBSTONE
                and not envelope.deleted
            ):
                return DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.INVALID,
                    message="tombstone result did not contain a deleted envelope",
                )
            self._remember_sync_envelope(envelope)
            if envelope.deleted:
                self.clear_dictation_draft()
            elif envelope.draft is not None:
                self.save_dictation_draft(envelope.draft)
        elif result.status is DictationDraftSyncStatus.TOMBSTONE:
            # Treat an explicit tombstone status as authoritative even when a
            # legacy adapter omitted the redundant envelope body.
            self.clear_dictation_draft()
        return result

    def push_dictation_draft(
        self,
        account_id: str,
        *,
        draft: DictationDraft | None = None,
        revision: str | None = None,
        updated_at_utc: float | None = None,
        deleted: bool = False,
        apply_response: bool = True,
    ) -> DictationDraftSyncResult:
        """Build and push a canonical envelope after local persistence.

        ``deleted`` creates a tombstone; otherwise the current local draft is
        used.  The adapter decides whether configuration permits transport.
        """
        adapter = self.dictation_draft_sync
        if adapter is None:
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.DISABLED,
                message="dictation draft sync is not configured; local-only mode",
            )
        source_draft = None if deleted else (draft if draft is not None else self.dictation_draft())
        if not deleted and source_draft is None:
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.INVALID,
                message="no local dictation draft is available to sync",
            )
        if source_draft is not None:
            source_draft = self._inherit_sync_metadata(source_draft)
            local_account = source_draft.sync_metadata.account_id.strip()
            requested_account = str(account_id).strip()
            if local_account and local_account != requested_account:
                return DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.INVALID,
                    message="local dictation draft belongs to a different account",
                )
        elif deleted:
            local_account = self._last_dictation_sync_metadata.account_id.strip()
            requested_account = str(account_id).strip()
            if local_account and local_account != requested_account:
                return DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.INVALID,
                    message="local dictation draft belongs to a different account",
                )
        envelope = make_sync_envelope(
            account_id,
            source_draft,
            revision=revision,
            updated_at_utc=updated_at_utc,
        )
        # ``make_sync_envelope`` inherits the local token when revision is
        # omitted.  Pass the effective token to the adapter as the If-Match
        # guard (the adapter maps the initial ``0`` token to no header).
        if_match_revision = (
            None if envelope.revision in {"", "0"} else envelope.revision
        )
        result = adapter.push(account_id, envelope, if_match_revision)
        returned = result.envelope
        if returned is None and result.status in {
            DictationDraftSyncStatus.SYNCED,
            DictationDraftSyncStatus.TOMBSTONE,
        }:
            # A successful 204-style adapter may omit the response body.  The
            # outbound canonical envelope is still the best known snapshot,
            # and retaining it advances local metadata without inventing a
            # server token.
            returned = envelope
        if returned is not None and returned.account_id.strip() != str(account_id).strip():
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.INVALID,
                message="sync response account_id does not match request",
            )
        if result.status is DictationDraftSyncStatus.CONFLICT:
            # Some adapters expose the remote envelope but do not construct a
            # conflict object.  Preserve local data and fill the pair here.
            if result.conflict is None and returned is not None:
                return replace(
                    result,
                    conflict=DictationDraftSyncConflict(
                        local=envelope,
                        remote=returned,
                    ),
                )
            return result

        # Make the effective envelope visible to asynchronous callers even
        # when the adapter returned a 204/empty body.  The outbound snapshot
        # is the only metadata we can safely retain in that case.
        if (
            result.envelope is None
            and returned is not None
            and result.status in {
                DictationDraftSyncStatus.SYNCED,
                DictationDraftSyncStatus.TOMBSTONE,
            }
        ):
            result = replace(result, envelope=returned)

        # Only a successful server response is allowed to advance local
        # metadata.  In particular, disabled/too-large/network failures must
        # leave the locally authored revision untouched.
        if apply_response and result.status in {
            DictationDraftSyncStatus.SYNCED,
            DictationDraftSyncStatus.TOMBSTONE,
        } and returned is not None:
            if result.status is DictationDraftSyncStatus.TOMBSTONE and not returned.deleted:
                return DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.INVALID,
                    message="tombstone result did not contain a deleted envelope",
                )
            self._remember_sync_envelope(returned)
            if returned.deleted:
                self.clear_dictation_draft()
            elif returned.draft is not None:
                self.save_dictation_draft(returned.draft)
        return result

    def apply_push_dictation_result(
        self,
        account_id: str,
        result: DictationDraftSyncResult,
        *,
        fallback_envelope: DictationDraftSyncEnvelope | None = None,
    ) -> DictationDraftSyncResult:
        """Apply a successful push response after an async snapshot check.

        A 204 response may omit an envelope; in that case the caller supplies
        the outbound snapshot as ``fallback_envelope``.  The method itself
        never performs transport and is therefore safe to call on Tk's thread.
        """
        if result.status not in {
            DictationDraftSyncStatus.SYNCED,
            DictationDraftSyncStatus.TOMBSTONE,
        }:
            return result
        returned = result.envelope or fallback_envelope
        if returned is None:
            return result
        if returned.account_id.strip() != str(account_id).strip():
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.INVALID,
                message="sync response account_id does not match request",
            )
        if result.status is DictationDraftSyncStatus.TOMBSTONE and not returned.deleted:
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.INVALID,
                message="tombstone result did not contain a deleted envelope",
            )
        self._remember_sync_envelope(returned)
        if returned.deleted:
            self.clear_dictation_draft()
        elif returned.draft is not None:
            self.save_dictation_draft(returned.draft)
        return result

    def _local_sync_envelope(
        self,
        account_id: str,
        draft: DictationDraft | None,
    ) -> DictationDraftSyncEnvelope | None:
        """Build a local envelope without inventing a draft when absent."""
        if draft is None:
            metadata = self._last_dictation_sync_metadata
            if not metadata.deleted:
                return None
            if metadata.account_id and metadata.account_id.strip() != str(account_id).strip():
                return None
            return DictationDraftSyncEnvelope(
                metadata=replace(metadata, account_id=metadata.account_id or str(account_id).strip()),
                draft=None,
            )
        local_account = draft.sync_metadata.account_id or account_id
        if local_account.strip() != str(account_id).strip():
            # Keep the mismatch visible to ``reconcile_sync_envelopes`` rather
            # than silently rebinding a draft to another account.
            local_account = draft.sync_metadata.account_id
        return make_sync_envelope(
            local_account,
            draft,
            revision=draft.sync_metadata.revision,
            updated_at_utc=draft.sync_metadata.updated_at_utc,
        )

    def _remember_sync_envelope(self, envelope: DictationDraftSyncEnvelope) -> None:
        self._last_dictation_sync_metadata = envelope.metadata
        persist_operations = (
            ("save_dictation_sync_metadata", envelope.metadata),
            ("save_last_synced_dictation_envelope", envelope),
        )
        for method_name, value in persist_operations:
            saver = getattr(self.repository, method_name, None)
            if not callable(saver):
                continue
            try:
                saver(value)
            except Exception:
                # Sync acknowledgement remains valid for this process even if
                # the platform cipher is temporarily unavailable.  Do not
                # turn a successful network operation into a UI failure.
                pass

    def _archive_dictation_conflict_backup(
        self,
        envelope: DictationDraftSyncEnvelope,
    ) -> None:
        saver = getattr(self.repository, "add_dictation_conflict_backup", None)
        if callable(saver):
            saver(envelope)

    def remember_dictation_sync_envelope(
        self,
        envelope: DictationDraftSyncEnvelope,
    ) -> None:
        """Record an acknowledgement without replacing a newer editor draft."""
        self._remember_sync_envelope(envelope)

    def prepare_local_dictation_conflict_retry(
        self,
        conflict: DictationDraftSyncConflict,
        draft: DictationDraft | None = None,
        *,
        updated_at_utc: float | None = None,
    ) -> DictationDraft | None:
        """Rebase an explicitly chosen local snapshot onto the remote token."""
        local = conflict.local
        remote = conflict.remote
        if local.account_id != remote.account_id:
            raise ValueError("sync conflict envelopes use different accounts")
        self._archive_dictation_conflict_backup(remote)
        timestamp = time.time() if updated_at_utc is None else updated_at_utc
        metadata = DictationDraftSyncMetadata(
            account_id=remote.account_id,
            revision=remote.revision,
            updated_at_utc=timestamp,
            deleted=local.deleted,
        )
        if local.deleted:
            self._last_dictation_sync_metadata = metadata
            saver = getattr(self.repository, "save_dictation_sync_metadata", None)
            if callable(saver):
                saver(metadata)
            self.clear_dictation_draft()
            return None
        source = draft or local.draft
        if source is None:
            raise ValueError("local sync conflict does not contain a draft")
        rebased = replace(source, sync_metadata=metadata)
        self.save_dictation_draft(rebased)
        return rebased

    def accept_remote_dictation_conflict(
        self,
        conflict: DictationDraftSyncConflict,
    ) -> DictationDraft | None:
        """Apply the user's explicit remote choice without reconciling again."""
        local = conflict.local
        remote = conflict.remote
        if local.account_id != remote.account_id:
            raise ValueError("sync conflict envelopes use different accounts")
        self._archive_dictation_conflict_backup(local)
        self._remember_sync_envelope(remote)
        if remote.deleted:
            self.clear_dictation_draft()
            return None
        if remote.draft is None:
            raise ValueError("remote sync conflict does not contain a draft")
        self.save_dictation_draft(remote.draft)
        return remote.draft

    def dictation_range_ids(
        self,
        anchor_id: str | None,
        endpoint_id: str | None,
        *,
        group: str | None = None,
        include_evaluated: bool = True,
    ) -> frozenset[str]:
        """Compute an inclusive range from the complete group sequence."""
        entries = self.dictation_pool(include_evaluated, group)
        return dictation_range_ids(entries, anchor_id, endpoint_id)

    def nearest_dictation_anchor(
        self,
        reference_id: str | None,
        selected_ids: set[str],
        *,
        group: str | None = None,
        include_evaluated: bool = True,
    ) -> str | None:
        entries = self.dictation_pool(include_evaluated, group)
        return nearest_dictation_id(entries, reference_id, selected_ids)

    def export_dictation(self, document: DictationDocument, exporter: DictationExporter | None = None) -> list[ExportedDictation]:
        adapter = exporter or self.dictation_exporter
        if adapter is None:
            raise RuntimeError("Dictation exporter is not configured")
        return [adapter.export(document, output_format) for output_format in sorted(document.options.formats, key=lambda item: item.value)]

    def update_program_tags(self, word_ids: set[str], add: set[str], remove: set[str]) -> int:
        normalized_add = {str(tag).strip().casefold() for tag in add if str(tag).strip()}
        normalized_remove = {str(tag).strip().casefold() for tag in remove if str(tag).strip()}
        if not (normalized_add | normalized_remove) <= self.available_program_tags():
            raise ValueError("只允许修改程序标签")
        if normalized_add & normalized_remove:
            raise ValueError("同一标签不能同时添加和移除")
        return self.repository.update_tags(set(word_ids), normalized_add, normalized_remove)

    def mark_mode(self) -> MarkMode:
        getter = getattr(self.repository, "get_mark_mode", None)
        return getter() if getter else MarkMode.ASK

    def set_mark_mode(self, mode: MarkMode | str) -> MarkMode:
        resolved = mode if isinstance(mode, MarkMode) else MarkMode(str(mode).upper())
        setter = getattr(self.repository, "set_mark_mode", None)
        if setter:
            setter(resolved)
        return resolved

    def update_entry_labels(self, word_ids: set[str], level: str, tags: set[str]) -> int:
        updater = getattr(self.repository, "update_entry_labels", None)
        if updater is None:
            return 0
        return updater(word_ids, level, tags)

    def rate_card(
        self,
        word_id: str,
        rating: ReviewRating | str,
        reviewed_at_utc: float | None = None,
    ) -> ReviewState:
        at_utc = time.time() if reviewed_at_utc is None else reviewed_at_utc
        updated = schedule_review(self.repository.review_state(word_id), rating, at_utc)
        self.repository.save_review_state(updated)
        self.repository.record_activity(word_id, at_utc)
        if (
            self.words_learnt_repository is not None
            and self.words_learnt_repository.learnt_word(word_id) is None
        ):
            self.words_learnt_repository.save_learnt_word(
                LearntWord.create(word_id, rating, at_utc)
            )
        return updated

    def start_review_session(
        self,
        count: int | None = None,
        rng: random.Random | None = None,
        *,
        due_only: bool = False,
        now_utc: float | None = None,
    ) -> list[VocabularyEntry]:
        entries = {entry.word_id: entry for entry in self.repository.all_entries()}
        learnt = [
            word for word in self._learnt_by_id().values()
            if word.word_id in entries and self._matches_levels(entries[word.word_id], self.review_levels())
        ]
        if due_only:
            now = time.time() if now_utc is None else now_utc
            states = {state.word_id: state for state in self.repository.all_review_states()}
            learnt = [
                word for word in learnt
                if word.word_id in states and states[word.word_id].due_at_utc <= now
            ]
        if not learnt:
            return []

        requested = self.review_batch_size() if count is None else int(count)
        size = min(len(learnt), max(1, requested))
        randomizer = rng or random.SystemRandom()
        pool = sorted(learnt, key=lambda word: word.word_id)
        selected: list[VocabularyEntry] = []
        for _ in range(size):
            total_weight = sum(word.weight for word in pool)
            threshold = randomizer.random() * total_weight
            cumulative = 0.0
            selected_index = len(pool) - 1
            for index, word in enumerate(pool):
                cumulative += word.weight
                if threshold < cumulative:
                    selected_index = index
                    break
            word = pool.pop(selected_index)
            selected.append(entries[word.word_id])
        return selected

    def rate_review_card(
        self,
        word_id: str,
        rating: ReviewRating | str,
        reviewed_at_utc: float | None = None,
    ) -> ReviewState:
        if self.words_learnt_repository is None:
            raise RuntimeError("Words_Learnt repository is not configured")
        learnt = self.words_learnt_repository.learnt_word(word_id)
        if learnt is None:
            raise ValueError("Only learnt words can be reviewed")
        at_utc = time.time() if reviewed_at_utc is None else reviewed_at_utc
        updated = schedule_review(self.repository.review_state(word_id), rating, at_utc)
        self.repository.save_review_state(updated)
        self.repository.record_activity(word_id, at_utc)
        self.words_learnt_repository.save_learnt_word(learnt.reviewed(rating, at_utc))
        return updated

    def learnt_word_count(self) -> int:
        entry_ids = {entry.word_id for entry in self.repository.all_entries()}
        return sum(word_id in entry_ids for word_id in self._learnt_by_id())

    def review_batch_size(self) -> int:
        stored = self.repository.get_review_batch_size()
        total = self.learnt_word_count()
        return min(stored, total) if total else 1

    def set_review_batch_size(self, size: int) -> int:
        total = self.learnt_word_count()
        bounded = min(max(1, int(size)), max(1, total))
        self.repository.set_review_batch_size(bounded)
        return bounded

    def reminder_enabled(self) -> bool:
        return self.repository.get_reminder_enabled()

    def reminder_interval_minutes(self) -> float:
        return self.repository.get_reminder_interval_minutes()

    def set_reminder_settings(self, enabled: bool, interval_minutes: float) -> float:
        minutes = float(interval_minutes)
        if not MIN_REMINDER_INTERVAL_MINUTES <= minutes <= MAX_REMINDER_INTERVAL_MINUTES:
            raise ValueError("提醒间隔需在 0.5 到 120 分钟之间")
        self.repository.set_reminder_enabled(enabled)
        self.repository.set_reminder_interval_minutes(minutes)
        return minutes

    def reminder_card(
        self,
        exclude_id: str = "",
        rng: random.Random | None = None,
        now_utc: float | None = None,
    ) -> VocabularyEntry | None:
        entries = [
            entry for entry in self.repository.all_entries()
            if self._matches_levels(entry, self.reminder_levels())
        ]
        if not entries:
            return None
        now = time.time() if now_utc is None else now_utc
        due_ids = {
            state.word_id
            for state in self.repository.all_review_states()
            if state.last_reviewed_at_utc is not None and state.due_at_utc <= now
        }
        candidates = [entry for entry in entries if entry.word_id in due_ids] or entries
        without_previous = [entry for entry in candidates if entry.word_id != exclude_id]
        return (rng or random.SystemRandom()).choice(without_previous or candidates)

    def due_review_count(self, now_utc: float | None = None) -> int:
        now = time.time() if now_utc is None else now_utc
        learnt_ids = set(self._learnt_by_id())
        entry_ids = {entry.word_id for entry in self.repository.all_entries()}
        return sum(
            state.word_id in learnt_ids
            and state.word_id in entry_ids
            and state.last_reviewed_at_utc is not None
            and state.due_at_utc <= now
            for state in self.repository.all_review_states()
        )

    def search(self, query: str) -> list[VocabularyEntry]:
        key = query.strip().casefold()
        entries = self.repository.all_entries()
        if not key:
            return entries
        return [
            entry for entry in entries
            if key in entry.word.casefold()
            or key in entry.meaning.casefold()
            or any(key in tag.casefold() for tag in entry.tags)
        ]

    def library_groups(self) -> list[LibraryGroup]:
        """Return the ordered library groups (canonical first, then extras)."""
        return self._group_summary(self.repository.all_entries())

    def _group_summary(self, entries: list[VocabularyEntry]) -> list[LibraryGroup]:
        canonical_counts = {key: 0 for key in GROUP_ORDER}
        extra_counts: dict[str, int] = {}
        for entry in entries:
            memberships = {normalize_group_membership(value) for value in entry.levels}
            for key in classify_groups(memberships, entry.tags):
                if key in canonical_counts:
                    canonical_counts[key] += 1
            for code in memberships:
                if code not in canonical_memberships():
                    extra_counts[code] = extra_counts.get(code, 0) + 1
        result = [LibraryGroup("all", group_label("all"), canonical_counts["all"])]
        for key in GROUP_ORDER[1:]:
            result.append(LibraryGroup(key, group_label(key), canonical_counts[key]))
        for code in sorted(extra_counts):
            result.append(LibraryGroup(code, code, extra_counts[code]))
        return result

    def _entries_in_group(self, entries: list[VocabularyEntry], key: str) -> list[VocabularyEntry]:
        if key == "all":
            return entries
        if key in GROUP_ORDER:
            return [
                entry for entry in entries
                if key in classify_groups(
                    {normalize_group_membership(value) for value in entry.levels},
                    entry.tags,
                )
            ]
        code = normalize_group_membership(key)
        return [
            entry for entry in entries
            if code in {normalize_group_membership(value) for value in entry.levels}
        ]

    def words_in_group(self, key: str, query: str = "") -> list[VocabularyEntry]:
        """Return the member words of a group, optionally filtered by query."""
        selected = self._entries_in_group(self.repository.all_entries(), key)
        needle = query.strip().casefold()
        if not needle:
            return selected
        return [
            entry for entry in selected
            if needle in entry.word.casefold()
            or needle in entry.meaning.casefold()
            or any(needle in tag.casefold() for tag in entry.tags)
        ]

    def dictation_groups(
        self,
        include_evaluated: bool = False,
    ) -> list[LibraryGroup]:
        """Return the ordered dictation-candidate groups for manual selection."""
        return self._group_summary(self.dictation_pool(include_evaluated))

    def dictation_words_in_group(
        self,
        key: str,
        include_evaluated: bool = False,
    ) -> list[VocabularyEntry]:
        """Return the dictation-candidate words of a group for manual selection."""
        return self._entries_in_group(self.dictation_pool(include_evaluated), key)

    def import_csv(self, path) -> ImportReport:
        if self.csv_importer is None:
            raise RuntimeError("CSV importer is not configured")
        entries, report = self.csv_importer.parse(path, {item.word_id for item in self.repository.all_entries()})
        imported = self.repository.add_entries(entries)
        report.succeeded = imported
        if imported < len(entries):
            report.skipped += len(entries) - imported
        return report

    def forecast(self, days: int, now_utc: float | None = None) -> list[tuple[str, int]]:
        if days not in (7, 30):
            raise ValueError("Forecast supports 7 or 30 days")
        now = time.time() if now_utc is None else now_utc
        start = datetime.fromtimestamp(now).date()
        counts: Counter[str] = Counter()
        entry_ids = {entry.word_id for entry in self.repository.all_entries()}
        learnt_ids = set(self._learnt_by_id())
        for state in self.repository.all_review_states():
            if (
                state.last_reviewed_at_utc is None
                or state.word_id not in entry_ids
                or state.word_id not in learnt_ids
            ):
                continue
            due_date = datetime.fromtimestamp(state.due_at_utc).date()
            offset = (due_date - start).days
            if 0 <= offset < days:
                counts[due_date.isoformat()] += 1
        return [((start + timedelta(days=index)).isoformat(), counts[(start + timedelta(days=index)).isoformat()]) for index in range(days)]

    def retention_curve(self, days: int = 30, now_utc: float | None = None) -> list[float]:
        now = time.time() if now_utc is None else now_utc
        entry_ids = {entry.word_id for entry in self.repository.all_entries()}
        learnt_ids = set(self._learnt_by_id())
        states = [
            state for state in self.repository.all_review_states()
            if state.last_reviewed_at_utc is not None
            and state.word_id in entry_ids
            and state.word_id in learnt_ids
        ]
        if not states:
            return [0.0 for _ in range(days + 1)]
        return [
            sum(retention_at(state, now + day * SECONDS_PER_DAY) for state in states) / len(states)
            for day in range(days + 1)
        ]

    def font_scale(self) -> float:
        return self.repository.get_font_scale()

    def set_font_scale(self, scale: float) -> float:
        bounded = min(1.4, max(0.9, float(scale)))
        self.repository.set_font_scale(bounded)
        return bounded
