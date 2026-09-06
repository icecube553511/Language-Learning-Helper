from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from domain.dictation import DictationDocument, DictationFormat


@dataclass(frozen=True)
class ExportedDictation:
    bytes: bytes
    file_name: str
    mime_type: str


class DictationExporter(Protocol):
    def export(self, document: DictationDocument, output_format: DictationFormat | None = None) -> ExportedDictation: ...
