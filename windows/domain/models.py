from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import unicodedata


ALGORITHM_VERSION = "lexi-sm2-v1"


def normalize_word_id(word: str) -> str:
    return unicodedata.normalize("NFKC", word).strip().casefold()


class ReviewRating(str, Enum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


@dataclass(frozen=True)
class ExampleSentence:
    english: str
    chinese: str

    def to_dict(self) -> dict[str, str]:
        return {"en": self.english, "zh": self.chinese}


@dataclass(frozen=True)
class VocabularyEntry:
    word_id: str
    word: str
    meaning: str
    examples: tuple[ExampleSentence, ...]
    phonetic: str = ""
    level: str = "custom"
    tags: tuple[str, ...] = ()
    mnemonic: str = ""
    source: str = "user"

    @classmethod
    def create(
        cls,
        word: str,
        meaning: str,
        examples: list[ExampleSentence] | tuple[ExampleSentence, ...],
        phonetic: str = "",
        level: str = "custom",
        tags: list[str] | tuple[str, ...] = (),
        mnemonic: str = "",
        source: str = "user",
    ) -> "VocabularyEntry":
        normalized_word = unicodedata.normalize("NFKC", word).strip()
        return cls(
            word_id=normalize_word_id(normalized_word),
            word=normalized_word,
            meaning=meaning.strip(),
            examples=tuple(examples),
            phonetic=phonetic.strip(),
            level=level.strip() or "custom",
            tags=tuple(tag.strip() for tag in tags if tag.strip()),
            mnemonic=mnemonic.strip(),
            source=source,
        )

    def is_study_ready(self) -> bool:
        if not self.word_id or not self.meaning or len(self.examples) < 3:
            return False
        english = [item.english.strip() for item in self.examples[:3]]
        return (
            all(english)
            and len({item.casefold() for item in english}) == 3
            and all(item.chinese.strip() for item in self.examples[:3])
        )

    def to_dict(self) -> dict:
        return {
            "id": self.word_id,
            "word": self.word,
            "meaning": self.meaning,
            "phonetic": self.phonetic,
            "level": self.level,
            "tags": list(self.tags),
            "mnemonic": self.mnemonic,
            "examples": [item.to_dict() for item in self.examples],
            "source": self.source,
        }


@dataclass(frozen=True)
class ReviewState:
    word_id: str
    state: str = "new"
    interval_days: float = 0.0
    ease: float = 2.5
    repetitions: int = 0
    lapses: int = 0
    due_at_utc: float = 0.0
    last_reviewed_at_utc: float | None = None

    def to_dict(self) -> dict:
        payload = asdict(self)
        return {
            "wordId": payload["word_id"],
            "state": payload["state"],
            "intervalDays": payload["interval_days"],
            "ease": payload["ease"],
            "repetitions": payload["repetitions"],
            "lapses": payload["lapses"],
            "dueAtUtc": payload["due_at_utc"],
            "lastReviewedAtUtc": payload["last_reviewed_at_utc"],
        }

    @classmethod
    def from_dict(cls, word_id: str, payload: dict) -> "ReviewState":
        return cls(
            word_id=word_id,
            state=str(payload.get("state", "new")),
            interval_days=float(payload.get("intervalDays", 0.0)),
            ease=float(payload.get("ease", 2.5)),
            repetitions=int(payload.get("repetitions", 0)),
            lapses=int(payload.get("lapses", 0)),
            due_at_utc=float(payload.get("dueAtUtc", 0.0)),
            last_reviewed_at_utc=(
                float(payload["lastReviewedAtUtc"])
                if payload.get("lastReviewedAtUtc") is not None
                else None
            ),
        )


@dataclass(frozen=True)
class ImportIssue:
    row: int
    field: str
    error_code: str
    message: str
    status: str = "failed"


@dataclass
class ImportReport:
    total_rows: int = 0
    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    issues: list[ImportIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
