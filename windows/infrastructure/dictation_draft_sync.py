"""Infrastructure adapters for optional dictation-draft synchronization.

The default adapter is deliberately local-only.  ``HttpDictationDraftSync``
is opt-in and only accepts an HTTPS endpoint plus an in-memory bearer token.
The transport stays at the infrastructure edge; callers deal exclusively in
the domain envelope/result types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from typing import Callable
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote, urlparse, urlunparse

from domain.dictation_sync import (
    DictationDraftSyncEnvelope,
    DictationDraftSyncConflict,
    DictationDraftSyncResult,
    DictationDraftSyncStatus,
    MAX_DICTATION_DRAFT_BYTES,
)


DisabledDictationDraftSyncResult = DictationDraftSyncResult


@dataclass(frozen=True)
class DictationDraftSyncConfig:
    """Configuration supplied by the composition root/secure storage.

    The bearer token is held only in memory by this value and is never copied
    into a draft or result.  ``configured`` additionally requires HTTPS so a
    future transport cannot accidentally downgrade the contract.
    """

    endpoint: str | None = None
    account_id: str | None = None
    bearer_token: str | None = field(default=None, repr=False)
    timeout_seconds: float = 10.0

    @property
    def endpoint_url(self) -> str | None:
        return self.endpoint

    @property
    def token(self) -> str | None:
        return self.bearer_token

    @property
    def configured(self) -> bool:
        if not all(
            value is not None and str(value).strip()
            for value in (self.endpoint, self.account_id, self.bearer_token)
        ):
            return False
        try:
            parsed = urlparse(str(self.endpoint))
        except ValueError:
            return False
        try:
            timeout = float(self.timeout_seconds)
        except (TypeError, ValueError):
            return False
        return (
            parsed.scheme.lower() == "https"
            and bool(parsed.netloc)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and math.isfinite(timeout)
            and timeout > 0
        )

    def __repr__(self) -> str:
        # Keep credentials out of accidental diagnostics and crash reports.
        token_state = "set" if self.bearer_token else "unset"
        return (
            "DictationDraftSyncConfig("
            f"endpoint={self.endpoint!r}, account_id={self.account_id!r}, "
            f"bearer_token=<{token_state}>, timeout_seconds={self.timeout_seconds!r})"
        )


class DisabledDictationDraftSync:
    """Concrete no-network adapter used until online sync is explicitly wired."""

    def __init__(
        self,
        config: DictationDraftSyncConfig | None = None,
        *,
        endpoint: str | None = None,
        endpoint_url: str | None = None,
        account_id: str | None = None,
        bearer_token: str | None = None,
        token: str | None = None,
        timeout_seconds: float = 10.0,
    ):
        if config is not None and any(
            value is not None
            for value in (endpoint, endpoint_url, account_id, bearer_token, token)
        ):
            raise ValueError("pass either config or individual sync settings")
        self.config = config or DictationDraftSyncConfig(
            endpoint=endpoint if endpoint is not None else endpoint_url,
            account_id=account_id,
            bearer_token=bearer_token if bearer_token is not None else token,
            timeout_seconds=timeout_seconds,
        )

    @property
    def enabled(self) -> bool:
        # Even complete config is not enabled until an HTTPS implementation is
        # installed.  This adapter is deliberately a no-op skeleton.
        return False

    def _disabled(self, message: str) -> DictationDraftSyncResult:
        return DictationDraftSyncResult(
            status=DictationDraftSyncStatus.DISABLED,
            message=message,
        )

    def pull(self, account_id: str | None = None) -> DictationDraftSyncResult:
        # No config check is needed before this return: this class has no
        # transport at all, and therefore cannot perform an accidental request.
        if self.config.account_id and account_id and str(account_id).strip() != str(self.config.account_id).strip():
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.INVALID,
                message="account_id does not match sync configuration",
            )
        if not self.config.configured:
            return self._disabled("dictation draft sync is not configured; local-only mode")
        return self._disabled("dictation draft sync transport is not installed")

    def push(
        self,
        account_id: str | DictationDraftSyncEnvelope | None = None,
        envelope: DictationDraftSyncEnvelope | None = None,
        if_match_revision: str | None = None,
    ) -> DictationDraftSyncResult:
        # Accept ``push(envelope, if_match_revision=...)`` as a convenience for
        # callers whose account is fixed by the composition-root config.
        if isinstance(account_id, DictationDraftSyncEnvelope) and envelope is None:
            envelope = account_id
            account_id = self.config.account_id
        if envelope is None:
            raise TypeError("envelope must be a DictationDraftSyncEnvelope")
        if not isinstance(envelope, DictationDraftSyncEnvelope):
            raise TypeError("envelope must be a DictationDraftSyncEnvelope")
        requested_account = "" if account_id is None else str(account_id).strip()
        if requested_account and requested_account != envelope.account_id:
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.INVALID,
                message="account_id does not match envelope",
            )
        if self.config.account_id and requested_account and requested_account != str(self.config.account_id).strip():
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.INVALID,
                message="account_id does not match sync configuration",
            )
        # Size validation happens before any future transport call and is also
        # meaningful in local-only mode, where the caller should surface why a
        # sync attempt was skipped while retaining its local save.
        if envelope.byte_size() > MAX_DICTATION_DRAFT_BYTES:
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.TOO_LARGE,
                message=f"dictation draft sync payload exceeds {MAX_DICTATION_DRAFT_BYTES} bytes",
            )
        if not self.config.configured:
            return self._disabled("dictation draft sync is not configured; local-only mode")
        return self._disabled("dictation draft sync transport is not installed")


# Name the behavior in both contract and product language.  The named port is
# a zero-logic subclass so type/introspection output is useful to composition
# roots while behavior stays in one implementation.
class DisabledDictationDraftSyncPort(DisabledDictationDraftSync):
    pass


LocalOnlyDictationDraftSync = DisabledDictationDraftSyncPort


class HttpDictationDraftSync:
    """Optional HTTPS implementation of :class:`DictationDraftSyncPort`.

    ``urllib`` is used intentionally so the Windows client has no additional
    runtime dependency.  The opener is injectable for deterministic tests;
    production callers should leave it at the standard-library default.
    """

    def __init__(
        self,
        config: DictationDraftSyncConfig | None = None,
        *,
        endpoint: str | None = None,
        endpoint_url: str | None = None,
        account_id: str | None = None,
        bearer_token: str | None = None,
        token: str | None = None,
        timeout_seconds: float = 10.0,
        opener: Callable[..., object] | None = None,
    ) -> None:
        if config is not None and any(
            value is not None
            for value in (
                endpoint,
                endpoint_url,
                account_id,
                bearer_token,
                token,
            )
        ):
            raise ValueError("pass either config or individual sync settings")
        self.config = config or DictationDraftSyncConfig(
            endpoint=endpoint if endpoint is not None else endpoint_url,
            account_id=account_id,
            bearer_token=bearer_token if bearer_token is not None else token,
            timeout_seconds=timeout_seconds,
        )
        # Keep the default lookup lazy so tests and embedders can replace the
        # standard opener after constructing the adapter.
        self._opener = opener

    @property
    def enabled(self) -> bool:
        return self.config.configured

    def _disabled(self) -> DictationDraftSyncResult:
        return DictationDraftSyncResult(
            status=DictationDraftSyncStatus.DISABLED,
            message="dictation draft sync is not configured; local-only mode",
        )

    def _validate_account(self, account_id: str | None) -> tuple[str | None, DictationDraftSyncResult | None]:
        requested = str(account_id or "").strip()
        configured = str(self.config.account_id or "").strip()
        if not requested:
            requested = configured
        if configured and requested != configured:
            return None, DictationDraftSyncResult(
                status=DictationDraftSyncStatus.INVALID,
                message="account_id does not match sync configuration",
            )
        if not requested:
            return None, DictationDraftSyncResult(
                status=DictationDraftSyncStatus.INVALID,
                message="account_id is required",
            )
        return requested, None

    def _url(self, account_id: str) -> str:
        parsed = urlparse(str(self.config.endpoint))
        base_path = parsed.path.rstrip("/")
        suffix = f"/v1/dictation-drafts/{quote(account_id, safe='')}"
        if base_path.endswith("/v1/dictation-drafts"):
            path = f"{base_path}/{quote(account_id, safe='')}"
        else:
            path = f"{base_path}{suffix}"
        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

    def _headers(self, *, content_type: bool = False, if_match: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {str(self.config.bearer_token).strip()}",
        }
        if content_type:
            headers["Content-Type"] = "application/json"
        if if_match:
            headers["If-Match"] = if_match
        return headers

    @staticmethod
    def _status(response: object) -> int:
        value = getattr(response, "status", None)
        if value is None:
            getter = getattr(response, "getcode", None)
            value = getter() if callable(getter) else 0
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _read(response: object) -> bytes:
        reader = getattr(response, "read", None)
        if not callable(reader):
            return b""
        # Read one byte past the contract limit so an oversized response can
        # be rejected without buffering an unbounded server payload.  Small
        # test doubles may not accept an amount argument, hence the fallback.
        try:
            raw = reader(MAX_DICTATION_DRAFT_BYTES + 1)
        except TypeError:
            raw = reader()
        if isinstance(raw, bytes):
            return raw
        if isinstance(raw, str):
            return raw.encode("utf-8")
        return bytes(raw or b"")

    def _request(self, request: urllib_request.Request) -> tuple[int, bytes]:
        opener = self._opener or urllib_request.urlopen
        response = opener(request, timeout=float(self.config.timeout_seconds))
        try:
            return self._status(response), self._read(response)
        finally:
            closer = getattr(response, "close", None)
            if callable(closer):
                closer()

    @staticmethod
    def _decode(raw: bytes) -> DictationDraftSyncEnvelope | None:
        if not raw.strip():
            return None
        try:
            payload = json.loads(raw)
            # Some servers wrap a conflict snapshot in ``remote`` or
            # ``envelope``.  Accept those names while keeping the canonical
            # wire form flat for successful responses.
            if isinstance(payload, dict):
                if isinstance(payload.get("remote"), dict):
                    payload = payload["remote"]
                elif isinstance(payload.get("envelope"), dict):
                    payload = payload["envelope"]
            return DictationDraftSyncEnvelope.from_dict(payload)
        except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            return None

    @staticmethod
    def _invalid(message: str) -> DictationDraftSyncResult:
        # Never include exception text, response bodies, URLs, or headers:
        # those values may contain credentials or user-entered identifiers.
        return DictationDraftSyncResult(
            status=DictationDraftSyncStatus.INVALID,
            message=message,
        )

    def _http_error(self, error: urllib_error.HTTPError) -> tuple[int, bytes]:
        try:
            return int(error.code), self._read(error)
        except Exception:
            return int(getattr(error, "code", 0) or 0), b""
        finally:
            closer = getattr(error, "close", None)
            if callable(closer):
                closer()

    @staticmethod
    def _too_large(raw: bytes) -> DictationDraftSyncResult | None:
        if len(raw) > MAX_DICTATION_DRAFT_BYTES:
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.TOO_LARGE,
                message=f"dictation draft sync payload exceeds {MAX_DICTATION_DRAFT_BYTES} bytes",
            )
        return None

    def pull(self, account_id: str | None = None) -> DictationDraftSyncResult:
        if not self.enabled:
            return self._disabled()
        resolved, failure = self._validate_account(account_id)
        if failure is not None:
            return failure
        request = urllib_request.Request(
            self._url(resolved),
            method="GET",
            headers=self._headers(),
        )
        try:
            status, raw = self._request(request)
        except urllib_error.HTTPError as error:
            status, raw = self._http_error(error)
        except (OSError, TimeoutError, ValueError):
            return self._invalid("dictation draft sync request failed")
        if status == 404:
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.LOCAL_ONLY,
                message="remote dictation draft is missing",
            )
        if status == 409:
            oversized = self._too_large(raw)
            if oversized is not None:
                return oversized
            remote = self._decode(raw)
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.CONFLICT,
                envelope=remote,
                message="remote dictation draft revision conflict",
            )
        if status not in (200, 201):
            return self._status_result(status)
        oversized = self._too_large(raw)
        if oversized is not None:
            return oversized
        envelope = self._decode(raw)
        if envelope is None:
            return self._invalid("sync response was not a valid dictation draft envelope")
        if envelope.account_id != resolved:
            return self._invalid("sync response account_id does not match request")
        return DictationDraftSyncResult(
            status=(
                DictationDraftSyncStatus.TOMBSTONE
                if envelope.deleted
                else DictationDraftSyncStatus.SYNCED
            ),
            envelope=envelope,
        )

    def push(
        self,
        account_id: str | DictationDraftSyncEnvelope | None = None,
        envelope: DictationDraftSyncEnvelope | None = None,
        if_match_revision: str | None = None,
    ) -> DictationDraftSyncResult:
        if isinstance(account_id, DictationDraftSyncEnvelope) and envelope is None:
            envelope = account_id
            account_id = self.config.account_id
        if envelope is None or not isinstance(envelope, DictationDraftSyncEnvelope):
            raise TypeError("envelope must be a DictationDraftSyncEnvelope")
        if envelope.byte_size() > MAX_DICTATION_DRAFT_BYTES:
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.TOO_LARGE,
                message=f"dictation draft sync payload exceeds {MAX_DICTATION_DRAFT_BYTES} bytes",
            )
        if not self.enabled:
            return self._disabled()
        resolved, failure = self._validate_account(account_id)
        if failure is not None:
            return failure
        if envelope.account_id != resolved:
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.INVALID,
                message="account_id does not match envelope",
            )
        revision = str(if_match_revision if if_match_revision is not None else envelope.revision).strip()
        # Older local drafts encode the initial empty revision as ``"0"``.
        # It is still an unguarded first PUT; a caller can provide an explicit
        # If-Match value when a server really uses ``0`` as a revision token.
        if if_match_revision is None and revision == "0":
            revision = ""
        request = urllib_request.Request(
            self._url(resolved),
            data=envelope.canonical_json_bytes(),
            method="PUT",
            headers=self._headers(content_type=True, if_match=revision or None),
        )
        try:
            status, raw = self._request(request)
        except urllib_error.HTTPError as error:
            status, raw = self._http_error(error)
        except (OSError, TimeoutError, ValueError):
            return self._invalid("dictation draft sync request failed")
        if status in (409, 412):
            oversized = self._too_large(raw)
            if oversized is not None:
                return oversized
            remote = self._decode(raw)
            conflict = (
                DictationDraftSyncConflict(local=envelope, remote=remote)
                if remote is not None
                else None
            )
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.CONFLICT,
                conflict=conflict,
                envelope=remote,
                message="remote dictation draft revision conflict",
            )
        if status == 404:
            return DictationDraftSyncResult(
                status=DictationDraftSyncStatus.LOCAL_ONLY,
                message="remote dictation draft is missing; no overwrite was attempted",
            )
        if status not in (200, 201, 204):
            return self._status_result(status)
        oversized = self._too_large(raw)
        if oversized is not None:
            return oversized
        returned = self._decode(raw) or envelope
        if returned.account_id != resolved:
            return self._invalid("sync response account_id does not match request")
        return DictationDraftSyncResult(
            status=(
                DictationDraftSyncStatus.TOMBSTONE
                if returned.deleted
                else DictationDraftSyncStatus.SYNCED
            ),
            envelope=returned,
        )

    @staticmethod
    def _status_result(status: int) -> DictationDraftSyncResult:
        if status in (401, 403):
            return HttpDictationDraftSync._invalid("dictation draft sync authorization failed")
        if status >= 500:
            return HttpDictationDraftSync._invalid("dictation draft sync server unavailable")
        return HttpDictationDraftSync._invalid("dictation draft sync request was rejected")


# Descriptive aliases keep composition roots free to use either the protocol
# name or the transport-specific name without introducing duplicate logic.
HttpsDictationDraftSync = HttpDictationDraftSync
OnlineDictationDraftSync = HttpDictationDraftSync
