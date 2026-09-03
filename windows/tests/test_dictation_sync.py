from __future__ import annotations

from pathlib import Path
import sys
import unittest

WINDOWS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WINDOWS_DIR))

from domain.dictation import (
    DictationDraft,
    DictationDraftSyncMetadata,
    DictationGroupDraft,
)
from domain.dictation_sync import (
    DICTATION_DRAFT_SYNC_VERSION,
    MAX_DICTATION_DRAFT_BYTES,
    DictationDraftSyncConflict,
    DictationDraftSyncEnvelope,
    DictationDraftSyncResult,
    DictationDraftSyncStatus,
    conflict_result,
    make_sync_envelope,
    reconcile_sync_envelopes,
)
from infrastructure.dictation_draft_sync import (
    DisabledDictationDraftSync,
    DictationDraftSyncConfig,
    HttpDictationDraftSync,
)
from application.services import LearningService
from infrastructure.repository import JsonLearningRepository
import tempfile


def sample_draft(**kwargs) -> DictationDraft:
    values = {
        "mode": "manual",
        "scope_group": "CET-4",
        "selected_ids": (" Apple ", "BANANA", "apple"),
        "groups": {
            "CET-4": DictationGroupDraft(
                selected_ids=(" Apple ", "BANANA", "apple"),
                anchor_id=" Apple ",
                endpoint_id="BANANA",
                scroll_position=2.0,
            ),
        },
    }
    values.update(kwargs)
    return DictationDraft(**values)


class DictationSyncDomainTests(unittest.TestCase):
    def test_make_envelope_aligns_embedded_draft_metadata(self):
        draft = sample_draft()
        envelope = make_sync_envelope(
            "user-1",
            draft,
            revision="opaque-7",
            updated_at_utc=12,
        )
        self.assertEqual(envelope.draft.sync_metadata.account_id, "user-1")
        self.assertEqual(envelope.draft.sync_metadata.revision, "opaque-7")
        self.assertEqual(envelope.draft.sync_metadata.updated_at_utc, 12.0)
        self.assertEqual(envelope.draft.sync_metadata.deleted, envelope.deleted)

    def test_same_revision_with_different_canonical_payload_is_conflict(self):
        local = make_sync_envelope(
            "user-1", sample_draft(custom_example="local"), revision="same", updated_at_utc=1
        )
        remote = make_sync_envelope(
            "user-1", sample_draft(custom_example="remote"), revision="same", updated_at_utc=1
        )
        result = reconcile_sync_envelopes(local, remote)
        self.assertEqual(result.status, DictationDraftSyncStatus.CONFLICT)
        self.assertEqual(result.conflict.local.draft.custom_example, "local")
        self.assertEqual(result.conflict.remote.draft.custom_example, "remote")

    def test_same_revision_and_canonical_payload_is_synced(self):
        local = make_sync_envelope(
            "user-1", sample_draft(custom_example="same"), revision="same", updated_at_utc=1
        )
        remote = DictationDraftSyncEnvelope.from_json(local.canonical_json())
        result = reconcile_sync_envelopes(local, remote)
        self.assertEqual(result.status, DictationDraftSyncStatus.SYNCED)
    def test_envelope_round_trip_uses_wire_names_and_normalized_draft(self):
        envelope = make_sync_envelope(" user-1 ", sample_draft(), revision=" 42 ", updated_at_utc=1730000000)
        self.assertEqual(envelope.version, DICTATION_DRAFT_SYNC_VERSION)
        self.assertEqual(envelope.account_id, "user-1")
        self.assertEqual(envelope.revision, "42")
        self.assertEqual(envelope.to_dict()["accountId"], "user-1")
        self.assertEqual(envelope.to_dict()["draft"]["selectedIds"], ["apple", "banana"])
        restored = DictationDraftSyncEnvelope.from_dict(envelope.to_dict())
        self.assertEqual(restored.canonical_json(), envelope.canonical_json())

    def test_tombstone_is_explicit_and_cannot_carry_draft(self):
        tombstone = make_sync_envelope("user-1", None, revision="7", updated_at_utc=1)
        self.assertTrue(tombstone.is_tombstone)
        self.assertIsNone(tombstone.to_dict()["draft"])
        with self.assertRaises(ValueError):
            DictationDraftSyncEnvelope("user-1", deleted=True, draft=sample_draft())

    def test_canonical_size_is_utf8_and_limit_is_one_mib(self):
        envelope = make_sync_envelope("user-1", sample_draft(), updated_at_utc=1)
        self.assertEqual(envelope.byte_size(), len(envelope.canonical_json().encode("utf-8")))
        self.assertLessEqual(envelope.byte_size(), MAX_DICTATION_DRAFT_BYTES)

    def test_conflict_keeps_local_and_remote_without_overwrite(self):
        local = make_sync_envelope("user-1", sample_draft(), revision="1", updated_at_utc=1)
        remote = make_sync_envelope("user-1", sample_draft(custom_example="remote"), revision="2", updated_at_utc=2)
        result = conflict_result(local, remote)
        self.assertEqual(result.status, DictationDraftSyncStatus.CONFLICT)
        self.assertEqual(result.conflict.local.revision, "1")
        self.assertEqual(result.conflict.remote.revision, "2")


class DisabledSyncAdapterTests(unittest.TestCase):
    def test_missing_configuration_is_disabled_without_transport(self):
        adapter = DisabledDictationDraftSync()
        result = adapter.pull("user-1")
        self.assertEqual(result.status, DictationDraftSyncStatus.DISABLED)
        pushed = adapter.push("user-1", make_sync_envelope("user-1", sample_draft(), updated_at_utc=1))
        self.assertEqual(pushed.status, DictationDraftSyncStatus.DISABLED)

    def test_oversized_payload_is_rejected_before_disabled_result(self):
        draft = sample_draft(custom_example="x" * MAX_DICTATION_DRAFT_BYTES)
        envelope = make_sync_envelope("user-1", draft, updated_at_utc=1)
        result = DisabledDictationDraftSync(DictationDraftSyncConfig()).push("user-1", envelope)
        self.assertEqual(result.status, DictationDraftSyncStatus.TOO_LARGE)

    def test_incomplete_or_non_https_configuration_stays_disabled(self):
        for config in (
            DictationDraftSyncConfig(endpoint="https://sync.example", account_id="user-1"),
            DictationDraftSyncConfig(endpoint="http://sync.example", account_id="user-1", bearer_token="secret"),
        ):
            self.assertFalse(config.configured)
            self.assertEqual(
                DisabledDictationDraftSync(config).pull("user-1").status,
                DictationDraftSyncStatus.DISABLED,
            )


class _FakeResponse:
    def __init__(self, status: int, body: bytes = b""):
        self.status = status
        self._body = body
        self.closed = False

    def read(self):
        return self._body

    def close(self):
        self.closed = True


class HttpSyncAdapterTests(unittest.TestCase):
    def setUp(self):
        self.envelope = make_sync_envelope(
            "user-1",
            sample_draft(),
            revision="42",
            updated_at_utc=1730000000,
        )

    def test_missing_or_non_https_config_never_calls_opener(self):
        calls = []

        def opener(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("network must remain disabled")

        for config in (
            DictationDraftSyncConfig(),
            DictationDraftSyncConfig(
                endpoint="http://sync.example",
                account_id="user-1",
                bearer_token="secret",
            ),
        ):
            adapter = HttpDictationDraftSync(config, opener=opener)
            self.assertFalse(adapter.enabled)
            self.assertEqual(adapter.pull("user-1").status, DictationDraftSyncStatus.DISABLED)
            self.assertEqual(
                adapter.push("user-1", self.envelope).status,
                DictationDraftSyncStatus.DISABLED,
            )
        self.assertEqual(calls, [])

    def test_pull_uses_https_path_and_bearer_and_decodes_envelope(self):
        calls = []

        def opener(request, timeout):
            calls.append((request, timeout))
            return _FakeResponse(200, self.envelope.canonical_json_bytes())

        adapter = HttpDictationDraftSync(
            endpoint="https://sync.example/api",
            account_id="user-1",
            bearer_token="secret-token",
            opener=opener,
        )
        result = adapter.pull("user-1")
        self.assertEqual(result.status, DictationDraftSyncStatus.SYNCED)
        self.assertEqual(result.envelope.revision, "42")
        request, timeout = calls[0]
        self.assertEqual(request.full_url, "https://sync.example/api/v1/dictation-drafts/user-1")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-token")
        self.assertEqual(timeout, 10.0)

    def test_push_sends_canonical_body_and_if_match(self):
        calls = []

        def opener(request, timeout):
            calls.append((request, timeout))
            return _FakeResponse(200, self.envelope.canonical_json_bytes())

        adapter = HttpDictationDraftSync(
            endpoint="https://sync.example",
            account_id="user-1",
            bearer_token="secret-token",
            opener=opener,
        )
        result = adapter.push("user-1", self.envelope, if_match_revision="41")
        self.assertEqual(result.status, DictationDraftSyncStatus.SYNCED)
        request, _ = calls[0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-token")
        self.assertEqual(request.get_header("If-match"), "41")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.data, self.envelope.canonical_json_bytes())

    def test_initial_revision_omits_if_match_header(self):
        calls = []
        initial = make_sync_envelope("user-1", sample_draft(), revision="", updated_at_utc=1)

        def opener(request, timeout):
            calls.append(request)
            return _FakeResponse(204)

        adapter = HttpDictationDraftSync(
            endpoint="https://sync.example",
            account_id="user-1",
            bearer_token="secret-token",
            opener=opener,
        )
        result = adapter.push("user-1", initial)
        self.assertEqual(result.status, DictationDraftSyncStatus.SYNCED)
        self.assertIsNone(calls[0].get_header("If-match"))

    def test_endpoint_userinfo_is_rejected(self):
        adapter = HttpDictationDraftSync(
            endpoint="https://user:password@sync.example",
            account_id="user-1",
            bearer_token="secret-token",
            opener=lambda *args, **kwargs: self.fail("network must remain disabled"),
        )
        self.assertFalse(adapter.enabled)
        self.assertEqual(adapter.pull("user-1").status, DictationDraftSyncStatus.DISABLED)

    def test_conflict_retains_local_and_remote_without_logging_token(self):
        remote = make_sync_envelope(
            "user-1", sample_draft(custom_example="remote"), revision="43", updated_at_utc=2
        )
        captured = []

        def opener(request, timeout):
            captured.append(request)
            return _FakeResponse(409, remote.canonical_json_bytes())

        adapter = HttpDictationDraftSync(
            endpoint="https://sync.example",
            account_id="user-1",
            bearer_token="secret-token",
            opener=opener,
        )
        result = adapter.push("user-1", self.envelope)
        self.assertEqual(result.status, DictationDraftSyncStatus.CONFLICT)
        self.assertIsNotNone(result.conflict)
        self.assertEqual(result.conflict.local.revision, "42")
        self.assertEqual(result.conflict.remote.revision, "43")
        self.assertNotIn("secret-token", result.message)
        self.assertNotIn("secret-token", repr(result))
        self.assertEqual(captured[0].get_header("Authorization"), "Bearer secret-token")

    def test_404_is_explained_as_remote_missing_and_tombstone_is_reported(self):
        def missing(request, timeout):
            return _FakeResponse(404)

        adapter = HttpDictationDraftSync(
            endpoint="https://sync.example",
            account_id="user-1",
            bearer_token="secret",
            opener=missing,
        )
        self.assertEqual(adapter.pull("user-1").status, DictationDraftSyncStatus.LOCAL_ONLY)
        self.assertIn("missing", adapter.pull("user-1").message)

        tombstone = make_sync_envelope("user-1", None, revision="44", updated_at_utc=3)
        adapter = HttpDictationDraftSync(
            endpoint="https://sync.example",
            account_id="user-1",
            bearer_token="secret",
            opener=lambda request, timeout: _FakeResponse(200, tombstone.canonical_json_bytes()),
        )
        pulled = adapter.pull("user-1")
        self.assertEqual(pulled.status, DictationDraftSyncStatus.TOMBSTONE)
        self.assertTrue(pulled.envelope.deleted)

    def test_oversized_payload_is_rejected_before_opener(self):
        calls = []
        huge = make_sync_envelope(
            "user-1",
            sample_draft(custom_example="x" * MAX_DICTATION_DRAFT_BYTES),
            updated_at_utc=1,
        )
        adapter = HttpDictationDraftSync(
            endpoint="https://sync.example",
            account_id="user-1",
            bearer_token="secret",
            opener=lambda *args, **kwargs: calls.append(args),
        )
        result = adapter.push("user-1", huge)
        self.assertEqual(result.status, DictationDraftSyncStatus.TOO_LARGE)
        self.assertEqual(calls, [])


class ServiceSyncTests(unittest.TestCase):
    class RecordingPort:
        def __init__(self, *, pull_result=None, push_result=None):
            self.pull_result = pull_result
            self.push_result = push_result
            self.pushed = []

        def pull(self, account_id):
            return self.pull_result

        def push(self, account_id, envelope, if_match_revision=None):
            self.pushed.append((account_id, envelope, if_match_revision))
            return self.push_result

    def test_save_and_sync_is_local_first_when_port_is_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            service = LearningService(
                repository,
                dictation_draft_sync=DisabledDictationDraftSync(),
            )
            draft = sample_draft()
            result = service.save_and_sync_dictation_draft(draft, "user-1", updated_at_utc=1)
            self.assertEqual(result.status, DictationDraftSyncStatus.DISABLED)
            self.assertEqual(repository.get_dictation_draft().to_dict(), draft.to_dict())

    def test_clear_and_sync_emits_tombstone_shape(self):
        class RecordingPort(DisabledDictationDraftSync):
            def __init__(self):
                super().__init__()
                self.seen = None

            def push(self, account_id, envelope, if_match_revision=None):
                self.seen = envelope
                return super().push(account_id, envelope, if_match_revision)

        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            repository.save_dictation_draft(sample_draft())
            adapter = RecordingPort()
            service = LearningService(repository, dictation_draft_sync=adapter)
            service.clear_and_sync_dictation_draft("user-1", revision="9", updated_at_utc=1)
            self.assertIsNone(repository.get_dictation_draft())
            self.assertIsNotNone(adapter.seen)
            self.assertTrue(adapter.seen.deleted)
            self.assertIsNone(adapter.seen.draft)

    def test_pull_different_revision_does_not_overwrite_local_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory), draft_cipher=None)
            local = sample_draft(
                custom_example="local",
                sync_metadata=DictationDraftSyncMetadata("user-1", "1", 1),
            )
            repository.save_dictation_draft(local)
            remote = make_sync_envelope(
                "user-1", sample_draft(custom_example="remote"), revision="2", updated_at_utc=2
            )
            port = self.RecordingPort(
                pull_result=DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.SYNCED,
                    envelope=remote,
                )
            )
            service = LearningService(repository, dictation_draft_sync=port)
            result = service.pull_dictation_draft("user-1")
            self.assertEqual(result.status, DictationDraftSyncStatus.CONFLICT)
            self.assertIsNotNone(result.conflict)
            self.assertEqual(result.conflict.local.revision, "1")
            self.assertEqual(result.conflict.remote.revision, "2")
            self.assertEqual(repository.get_dictation_draft().custom_example, "local")

    def test_pull_can_be_deferred_without_mutating_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            remote = make_sync_envelope(
                "user-1", sample_draft(custom_example="remote"), revision="2", updated_at_utc=2
            )
            port = self.RecordingPort(
                pull_result=DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.SYNCED,
                    envelope=remote,
                )
            )
            service = LearningService(repository, dictation_draft_sync=port)
            result = service.pull_dictation_draft("user-1", apply=False)
            self.assertEqual(result.status, DictationDraftSyncStatus.SYNCED)
            self.assertIsNone(repository.get_dictation_draft())
            service.apply_pulled_dictation_draft("user-1", result)
            self.assertEqual(repository.get_dictation_draft().custom_example, "remote")

    def test_deferred_pull_rechecks_local_snapshot_before_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            remote = make_sync_envelope(
                "user-1", sample_draft(custom_example="remote"), revision="2", updated_at_utc=2
            )
            port = self.RecordingPort(
                pull_result=DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.SYNCED,
                    envelope=remote,
                )
            )
            service = LearningService(repository, dictation_draft_sync=port)
            result = service.pull_dictation_draft("user-1", apply=False)
            repository.save_dictation_draft(
                sample_draft(
                    custom_example="edited-while-pulling",
                    sync_metadata=DictationDraftSyncMetadata("user-1", "1", 1),
                )
            )
            applied = service.apply_pulled_dictation_draft("user-1", result)
            self.assertEqual(applied.status, DictationDraftSyncStatus.CONFLICT)
            self.assertEqual(
                repository.get_dictation_draft().custom_example,
                "edited-while-pulling",
            )

    def test_push_success_persists_server_revision_and_uses_local_if_match(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            local = sample_draft(
                custom_example="local",
                sync_metadata=DictationDraftSyncMetadata("user-1", "1", 1),
            )
            repository.save_dictation_draft(local)
            returned = make_sync_envelope(
                "user-1", sample_draft(custom_example="local"), revision="2", updated_at_utc=2
            )
            port = self.RecordingPort(
                push_result=DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.SYNCED,
                    envelope=returned,
                )
            )
            service = LearningService(repository, dictation_draft_sync=port)
            result = service.push_dictation_draft("user-1")
            self.assertEqual(result.status, DictationDraftSyncStatus.SYNCED)
            self.assertEqual(port.pushed[0][2], "1")
            saved = repository.get_dictation_draft()
            self.assertEqual(saved.sync_metadata.account_id, "user-1")
            self.assertEqual(saved.sync_metadata.revision, "2")
            self.assertEqual(saved.sync_metadata.updated_at_utc, 2.0)
            self.assertEqual(
                repository.get_last_synced_dictation_envelope().revision,
                "2",
            )

    def test_push_uses_captured_draft_without_applying_stale_response(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            captured = sample_draft(
                custom_example="captured",
                sync_metadata=DictationDraftSyncMetadata("user-1", "1", 1),
            )
            newer = sample_draft(
                custom_example="newer",
                sync_metadata=DictationDraftSyncMetadata("user-1", "1", 1),
            )
            repository.save_dictation_draft(newer)
            returned = make_sync_envelope(
                "user-1", captured, revision="2", updated_at_utc=2
            )
            port = self.RecordingPort(
                push_result=DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.SYNCED,
                    envelope=returned,
                )
            )
            service = LearningService(repository, dictation_draft_sync=port)
            result = service.push_dictation_draft(
                "user-1", draft=captured, apply_response=False,
            )
            self.assertEqual(port.pushed[0][1].draft.custom_example, "captured")
            self.assertEqual(repository.get_dictation_draft().custom_example, "newer")
            self.assertEqual(result.envelope.revision, "2")

    def test_push_rejects_local_account_mismatch_without_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            local = sample_draft(
                sync_metadata=DictationDraftSyncMetadata("user-a", "7", 7),
            )
            repository.save_dictation_draft(local)
            port = self.RecordingPort(
                push_result=DictationDraftSyncResult(status=DictationDraftSyncStatus.SYNCED)
            )
            service = LearningService(repository, dictation_draft_sync=port)
            result = service.push_dictation_draft("user-b")
            self.assertEqual(result.status, DictationDraftSyncStatus.INVALID)
            self.assertEqual(port.pushed, [])
            self.assertEqual(repository.get_dictation_draft().sync_metadata.account_id, "user-a")

    def test_new_draft_inherits_last_server_revision_after_tombstone(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            tombstone = make_sync_envelope("user-1", None, revision="opaque-9", updated_at_utc=9)
            port = self.RecordingPort(
                pull_result=DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.TOMBSTONE,
                    envelope=tombstone,
                )
            )
            service = LearningService(repository, dictation_draft_sync=port)
            result = service.pull_dictation_draft("user-1")
            self.assertEqual(result.status, DictationDraftSyncStatus.TOMBSTONE)
            fresh = sample_draft(custom_example="fresh")
            service.save_dictation_draft(fresh)
            saved = repository.get_dictation_draft()
            self.assertEqual(saved.sync_metadata.account_id, "user-1")
            self.assertEqual(saved.sync_metadata.revision, "opaque-9")
            restarted = LearningService(
                JsonLearningRepository(Path(directory)),
                dictation_draft_sync=port,
            )
            restarted.clear_dictation_draft()
            restarted.save_dictation_draft(sample_draft(custom_example="after-restart"))
            self.assertEqual(
                restarted.dictation_draft().sync_metadata.revision,
                "opaque-9",
            )

    def test_clear_and_sync_inherits_previous_revision_for_tombstone(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            local = sample_draft(
                sync_metadata=DictationDraftSyncMetadata("user-1", "opaque-7", 7),
            )
            repository.save_dictation_draft(local)
            tombstone = make_sync_envelope(
                "user-1", None, revision="opaque-8", updated_at_utc=8
            )
            port = self.RecordingPort(
                push_result=DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.TOMBSTONE,
                    envelope=tombstone,
                )
            )
            service = LearningService(repository, dictation_draft_sync=port)
            result = service.clear_and_sync_dictation_draft("user-1")
            self.assertEqual(result.status, DictationDraftSyncStatus.TOMBSTONE)
            self.assertEqual(port.pushed[0][1].revision, "opaque-7")
            self.assertEqual(port.pushed[0][2], "opaque-7")
            self.assertIsNone(repository.get_dictation_draft())

    def test_push_success_without_response_body_still_writes_aligned_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            local = sample_draft(
                sync_metadata=DictationDraftSyncMetadata("user-1", "opaque-7", 7),
            )
            repository.save_dictation_draft(local)
            port = self.RecordingPort(
                push_result=DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.SYNCED,
                )
            )
            service = LearningService(repository, dictation_draft_sync=port)
            service.push_dictation_draft("user-1")
            saved = repository.get_dictation_draft()
            self.assertEqual(saved.sync_metadata.account_id, "user-1")
            self.assertEqual(saved.sync_metadata.revision, "opaque-7")

    def test_clear_and_sync_restores_local_snapshot_on_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            local = sample_draft(
                custom_example="keep-me",
                sync_metadata=DictationDraftSyncMetadata("user-1", "opaque-7", 7),
            )
            repository.save_dictation_draft(local)
            remote = make_sync_envelope(
                "user-1", sample_draft(custom_example="remote"), revision="opaque-8", updated_at_utc=8
            )
            port = self.RecordingPort(
                push_result=DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.CONFLICT,
                    envelope=remote,
                )
            )
            service = LearningService(repository, dictation_draft_sync=port)
            result = service.clear_and_sync_dictation_draft("user-1")
            self.assertEqual(result.status, DictationDraftSyncStatus.CONFLICT)
            self.assertEqual(repository.get_dictation_draft().custom_example, "keep-me")

    def test_keep_local_conflict_rebases_current_editor_on_remote_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            local = make_sync_envelope(
                "user-1", sample_draft(custom_example="saved"), revision="7", updated_at_utc=7
            )
            remote = make_sync_envelope(
                "user-1", sample_draft(custom_example="remote"), revision="8", updated_at_utc=8
            )
            service = LearningService(repository)
            rebased = service.prepare_local_dictation_conflict_retry(
                DictationDraftSyncConflict(local=local, remote=remote),
                sample_draft(custom_example="edited-after-request"),
                updated_at_utc=9,
            )
            self.assertEqual(rebased.custom_example, "edited-after-request")
            self.assertEqual(rebased.sync_metadata.revision, "8")
            self.assertEqual(rebased.sync_metadata.updated_at_utc, 9)
            self.assertEqual(repository.get_dictation_draft().to_dict(), rebased.to_dict())
            self.assertEqual(
                repository.get_dictation_conflict_backups()[0].canonical_json(),
                remote.canonical_json(),
            )

    def test_conflict_backup_failure_does_not_replace_local_draft(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            original = sample_draft(
                custom_example="keep-me",
                sync_metadata=DictationDraftSyncMetadata("user-1", "7", 7),
            )
            repository.save_dictation_draft(original)
            def fail_backup(_envelope):
                raise RuntimeError("secure storage unavailable")

            repository.add_dictation_conflict_backup = fail_backup
            conflict = DictationDraftSyncConflict(
                local=make_sync_envelope("user-1", original, revision="7", updated_at_utc=7),
                remote=make_sync_envelope(
                    "user-1",
                    sample_draft(custom_example="remote"),
                    revision="8",
                    updated_at_utc=8,
                ),
            )
            service = LearningService(repository)

            with self.assertRaises(RuntimeError):
                service.accept_remote_dictation_conflict(conflict)

            self.assertEqual(repository.get_dictation_draft().custom_example, "keep-me")

    def test_accept_remote_tombstone_persists_revision_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            local = make_sync_envelope(
                "user-1", sample_draft(custom_example="local"), revision="7", updated_at_utc=7
            )
            repository.save_dictation_draft(local.draft)
            remote = make_sync_envelope("user-1", None, revision="8", updated_at_utc=8)
            service = LearningService(repository)
            accepted = service.accept_remote_dictation_conflict(
                DictationDraftSyncConflict(local=local, remote=remote)
            )
            self.assertIsNone(accepted)
            self.assertEqual(
                repository.get_dictation_conflict_backups()[0].canonical_json(),
                local.canonical_json(),
            )
            restarted = LearningService(JsonLearningRepository(Path(directory)))
            self.assertIsNone(restarted.dictation_draft())
            self.assertEqual(restarted.dictation_sync_metadata().revision, "8")
            self.assertTrue(restarted.dictation_sync_metadata().deleted)

    def test_pending_local_tombstone_conflicts_with_remote_draft_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = JsonLearningRepository(Path(directory))
            service = LearningService(repository)
            service.save_dictation_draft(sample_draft(
                sync_metadata=DictationDraftSyncMetadata("user-1", "7", 7),
            ))
            service.stage_dictation_tombstone("user-1", updated_at_utc=8)

            remote = make_sync_envelope(
                "user-1", sample_draft(custom_example="remote"), revision="7", updated_at_utc=7
            )
            port = self.RecordingPort(
                pull_result=DictationDraftSyncResult(
                    status=DictationDraftSyncStatus.SYNCED,
                    envelope=remote,
                )
            )
            restarted = LearningService(
                JsonLearningRepository(Path(directory)),
                dictation_draft_sync=port,
            )
            result = restarted.pull_dictation_draft("user-1")
            self.assertEqual(result.status, DictationDraftSyncStatus.CONFLICT)
            self.assertTrue(result.conflict.local.deleted)
            self.assertIsNone(restarted.dictation_draft())


if __name__ == "__main__":
    unittest.main()
