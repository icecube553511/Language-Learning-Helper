from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from domain.dictation import DictationDocument, DictationFormat
from domain.dictation_sync import (
    DictationDraftSyncEnvelope,
    DictationDraftSyncMetadata,
    DictationDraftSyncResult,
    DictationDraftSyncStatus,
)
from domain.ports import DictationDraftSyncPort


@dataclass(frozen=True)
class ExportedDictation:
    bytes: bytes
    file_name: str
    mime_type: str


class DictationExporter(Protocol):
    def export(self, document: DictationDocument, output_format: DictationFormat | None = None) -> ExportedDictation: ...


# ``DictationDraftSyncPort`` is re-exported from ``domain.ports`` above for
# callers that historically imported all application boundaries here.
