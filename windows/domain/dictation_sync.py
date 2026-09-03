"""Portable types for the optional dictation-draft sync boundary.

The domain owns the wire shape and consistency vocabulary, but deliberately
does not know how a request is made or where credentials are stored.  The
Windows infrastructure adapter can therefore remain local-only until a
composition root opts into an HTTPS implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
import time
from typing import Mapping

from .dictation import (
    DictationDraft,
    DictationDraftSyncMetadata,
    MAX_DICTATION_DRAFT_BYTES,
)


DICTATION_DRAFT_SYNC_VERSION = "dictation-draft-v1"


class DictationDraftSyncStatus(str, Enum):
    """Outcome of a pull or push attempt.

    ``DISABLED`` is intentionally distinct from ``CONFLICT``: no remote data
    was consulted in disabled/local-only mode, so callers must keep the local
    draft and may retry after configuration changes.
    """

    DISABLED = "disabled"
    LOCAL_ONLY = "local-only"
    SYNCED = "synced"
    CONFLICT = "conflict"
    TOMBSTONE = "tombstone"
    TOO_LARGE = "too-large"
    INVALID = "invalid"

    @property
    def is_local_only(self) -> bool:
        return self in {self.DISABLED, self.LOCAL_ONLY, self.TOO_LARGE}


# Short aliases are useful to adapters and preserve a stable vocabulary if
# the application later grows a generic sync result hierarchy.
SyncStatus = DictationDraftSyncStatus


@dataclass(frozen=True, init=False)
class DictationDraftSyncEnvelope:
    """Canonical metadata plus one draft (or a deletion tombstone).

    The constructor accepts both the flat wire fields used by the Android
    port and a ``metadata=DictationDraftSyncMetadata(...)`` value.  This keeps
    the domain API ergonomic while guaranteeing one canonical JSON shape.
    """

    metadata: DictationDraftSyncMetadata
    draft: DictationDraft | None

    def __init__(
        self,
        account_id: str | None = None,
        revision: str = "",
        updated_at_utc: float = 0.0,
        deleted: bool = False,
        draft: DictationDraft | None = None,
        *,
        metadata: DictationDraftSyncMetadata | None = None,
    ) -> None:
        if metadata is None:
            metadata = DictationDraftSyncMetadata(
                account_id=str(account_id or ""),
                revision=revision,
                updated_at_utc=updated_at_utc,
                deleted=deleted,
            )
        elif not isinstance(metadata, DictationDraftSyncMetadata):
            raise TypeError("metadata must be DictationDraftSyncMetadata")
        # Explicit flat values must agree with metadata when supplied.  The
        # default values are intentionally ignored so ``metadata=`` remains
        # concise and backwards-compatible.
        if account_id is not None and str(account_id).strip() != metadata.account_id:
            raise ValueError("account_id does not match metadata")
        if metadata.deleted and draft is not None:
            raise ValueError("deleted envelopes must not contain a draft")
        if not metadata.deleted and draft is None:
            raise ValueError("non-deleted envelopes require a draft")
        if draft is not None and not isinstance(draft, DictationDraft):
            raise TypeError("draft must be a DictationDraft")
        # Keep the metadata embedded in a persisted draft identical to the
        # envelope metadata.  Drafts created before sync was configured carry
        # the default empty account/revision; normalizing here preserves those
        # drafts while making the canonical local and wire payloads agree.
        if draft is not None and draft.sync_metadata != metadata:
            draft = replace(draft, sync_metadata=metadata)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "draft", draft)

    @property
    def account_id(self) -> str:
        return self.metadata.account_id

    @property
    def revision(self) -> str:
        return self.metadata.revision

    @property
    def updated_at_utc(self) -> float:
        return self.metadata.updated_at_utc

    @property
    def deleted(self) -> bool:
        return self.metadata.deleted

    @property
    def version(self) -> str:
        return DICTATION_DRAFT_SYNC_VERSION

    @property
    def is_tombstone(self) -> bool:
        return self.deleted

    def to_dict(self) -> dict:
        payload = self.metadata.to_dict()
        payload["draft"] = None if self.deleted else self.draft.to_dict()
        return payload

    def canonical_payload(self) -> dict:
        return self.to_dict()

    @classmethod
    def from_dict(cls, payload: Mapping) -> "DictationDraftSyncEnvelope":
        if not isinstance(payload, Mapping):
            raise ValueError("sync envelope must be an object")
        version = payload.get("version")
        if version is not None and str(version) != DICTATION_DRAFT_SYNC_VERSION:
            raise ValueError("unsupported dictation draft sync version")
        # A few early prototypes nested metadata.  Accepting it here costs no
        # wire compatibility and lets callers migrate without data loss.
        metadata_payload = payload.get("metadata")
        metadata = (
            DictationDraftSyncMetadata.from_dict(metadata_payload)
            if isinstance(metadata_payload, Mapping)
            else DictationDraftSyncMetadata.from_dict(payload)
        )
        deleted = metadata.deleted
        raw_draft = payload.get("draft")
        draft = None if deleted else DictationDraft.from_dict(raw_draft)
        if not deleted and draft is None:
            raise ValueError("sync envelope contains an invalid draft")
        return cls(
            metadata=metadata,
            draft=draft,
        )

    def canonical_json(self) -> str:
        """Compact deterministic JSON used for transport and size checks."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )

    def canonical_json_bytes(self) -> bytes:
        return self.canonical_json().encode("utf-8")

    def to_json(self) -> str:
        return self.canonical_json()

    @classmethod
    def from_json(cls, raw: str | bytes) -> "DictationDraftSyncEnvelope":
        try:
            payload = json.loads(raw)
        except (TypeError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("sync envelope is not valid JSON") from error
        return cls.from_dict(payload)

    def byte_size(self) -> int:
        return len(self.canonical_json_bytes())

    @property
    def size_bytes(self) -> int:
        return self.byte_size()

    def within_size_limit(self, limit: int = MAX_DICTATION_DRAFT_BYTES) -> bool:
        return self.byte_size() <= int(limit)


@dataclass(frozen=True)
class DictationDraftSyncConflict:
    """Both versions are retained so presentation can ask the user."""

    local: DictationDraftSyncEnvelope
    remote: DictationDraftSyncEnvelope


@dataclass(frozen=True)
class DictationDraftSyncResult:
    status: DictationDraftSyncStatus
    envelope: DictationDraftSyncEnvelope | None = None
    conflict: DictationDraftSyncConflict | None = None
    message: str = ""

    @property
    def revision(self) -> str | None:
        return self.envelope.revision if self.envelope is not None else None

    @property
    def disabled(self) -> bool:
        return self.status is DictationDraftSyncStatus.DISABLED

    @property
    def local_only(self) -> bool:
        return self.status in {
            DictationDraftSyncStatus.DISABLED,
            DictationDraftSyncStatus.LOCAL_ONLY,
        }

    @property
    def is_conflict(self) -> bool:
        return self.status is DictationDraftSyncStatus.CONFLICT

    @property
    def is_success(self) -> bool:
        return self.status in {
            DictationDraftSyncStatus.SYNCED,
            DictationDraftSyncStatus.TOMBSTONE,
        }


# Public names used by composition roots that only expose the disabled
# adapter.  They intentionally remain aliases, so a future enabled adapter
# can return the same result object without a migration.
DisabledDictationDraftSyncResult = DictationDraftSyncResult
SyncResult = DictationDraftSyncResult


def sync_envelope_size(
    envelope: DictationDraftSyncEnvelope,
    limit: int = MAX_DICTATION_DRAFT_BYTES,
) -> int:
    """Validate and return the canonical UTF-8 byte count.

    The caller can use the returned value for diagnostics while the adapter
    uses ``within_size_limit`` to reject an oversized request before transport.
    """
    size = envelope.byte_size()
    if size > int(limit):
        raise ValueError(f"dictation draft sync payload exceeds {int(limit)} bytes")
    return size


def make_sync_envelope(
    account_id: str,
    draft: DictationDraft | None,
    *,
    revision: str | None = None,
    updated_at_utc: float | None = None,
) -> DictationDraftSyncEnvelope:
    """Build a draft or tombstone envelope from local state."""
    # A saved draft carries the server revision/account metadata.  Callers
    # may override it explicitly (for example when resolving a conflict), but
    # the ordinary save path must never reset an existing revision to ``0``.
    if draft is not None:
        saved = draft.sync_metadata
        if (revision is None or not str(revision).strip()) and saved.revision:
            revision = saved.revision
        if (not account_id or not str(account_id).strip()) and saved.account_id:
            account_id = saved.account_id
    if revision is None:
        revision = ""
    if draft is not None and updated_at_utc is None:
        saved = draft.sync_metadata
        if saved.updated_at_utc:
            updated_at_utc = saved.updated_at_utc
    return DictationDraftSyncEnvelope(
        account_id=account_id,
        revision=revision,
        updated_at_utc=time.time() if updated_at_utc is None else updated_at_utc,
        deleted=draft is None,
        draft=draft,
    )


def conflict_result(
    local: DictationDraftSyncEnvelope,
    remote: DictationDraftSyncEnvelope,
) -> DictationDraftSyncResult:
    """Create a non-destructive conflict result, including tombstones."""
    if local.account_id != remote.account_id:
        raise ValueError("local and remote envelopes must use the same account")
    return DictationDraftSyncResult(
        status=DictationDraftSyncStatus.CONFLICT,
        conflict=DictationDraftSyncConflict(local=local, remote=remote),
        message="remote revision differs from local revision",
    )


def reconcile_sync_envelopes(
    local: DictationDraftSyncEnvelope,
    remote: DictationDraftSyncEnvelope | None,
) -> DictationDraftSyncResult:
    """Reconcile an optional remote snapshot without silently losing data.

    Revisions are opaque server tokens.  Equality means the snapshots are
    already in agreement; any mismatch is surfaced as a conflict, including a
    remote tombstone, so an older delete can never erase a newer local draft.
    """
    if remote is None:
        return DictationDraftSyncResult(
            status=(
                DictationDraftSyncStatus.TOMBSTONE
                if local.deleted
                else DictationDraftSyncStatus.LOCAL_ONLY
            ),
            envelope=local,
        )
    if local.account_id != remote.account_id:
        return DictationDraftSyncResult(
            status=DictationDraftSyncStatus.INVALID,
            message="local and remote envelopes use different accounts",
        )
    if local.revision == remote.revision:
        # An editor may have changed its payload while retaining the last
        # server revision.  Equal opaque tokens alone therefore do not prove
        # that the two snapshots are identical; surface a conflict instead of
        # silently replacing local edits.
        if local.canonical_json() != remote.canonical_json():
            return conflict_result(local, remote)
        return DictationDraftSyncResult(
            status=(
                DictationDraftSyncStatus.TOMBSTONE
                if remote.deleted
                else DictationDraftSyncStatus.SYNCED
            ),
            envelope=remote,
        )
    return conflict_result(local, remote)
