from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import unicodedata


ALGORITHM_VERSION = "lexi-sm2-v1"
DEFAULT_REVIEW_BATCH_SIZE = 20


INITIAL_REVIEW_WEIGHTS = {
    "again": 1.0,
    "hard": 0.8,
    "good": 0.2,
    "easy": 0.05,
}


def normalize_word_id(word: str) -> str:
    return unicodedata.normalize("NFKC", word).strip().casefold()


class ReviewRating(str, Enum):
    AGAIN = "again"
    HARD = "hard"
    GOOD = "good"
    EASY = "easy"


def initial_review_weight(rating: ReviewRating | str) -> float:
    resolved = rating if isinstance(rating, ReviewRating) else ReviewRating(rating)
    return INITIAL_REVIEW_WEIGHTS[resolved.value]


def updated_review_weight(current_weight: float, rating: ReviewRating | str) -> float:
    resolved = rating if isinstance(rating, ReviewRating) else ReviewRating(rating)
    if resolved in (ReviewRating.GOOD, ReviewRating.EASY):
        return INITIAL_REVIEW_WEIGHTS[resolved.value]
    normalized = float(current_weight)
    if normalized not in INITIAL_REVIEW_WEIGHTS.values():
        return INITIAL_REVIEW_WEIGHTS[ReviewRating.GOOD.value]
    return normalized


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
class LearntWord:
    word_id: str
    weight: float
    learnt_at_utc: float
    last_reviewed_at_utc: float
    review_count: int = 0

    @classmethod
    def create(
        cls,
        word_id: str,
        rating: ReviewRating | str,
        learnt_at_utc: float,
    ) -> "LearntWord":
        return cls(
            word_id=word_id,
            weight=initial_review_weight(rating),
            learnt_at_utc=float(learnt_at_utc),
            last_reviewed_at_utc=float(learnt_at_utc),
            review_count=0,
        )

    def reviewed(self, rating: ReviewRating | str, reviewed_at_utc: float) -> "LearntWord":
        return LearntWord(
            word_id=self.word_id,
            weight=updated_review_weight(self.weight, rating),
            learnt_at_utc=self.learnt_at_utc,
            last_reviewed_at_utc=float(reviewed_at_utc),
            review_count=self.review_count + 1,
        )

    def to_dict(self) -> dict:
        return {
            "wordId": self.word_id,
            "weight": self.weight,
            "learntAtUtc": self.learnt_at_utc,
            "lastReviewedAtUtc": self.last_reviewed_at_utc,
            "reviewCount": self.review_count,
        }

    @classmethod
    def from_dict(cls, word_id: str, payload: dict) -> "LearntWord":
        weight = float(payload.get("weight", 0.2))
        if weight not in INITIAL_REVIEW_WEIGHTS.values():
            weight = INITIAL_REVIEW_WEIGHTS[ReviewRating.GOOD.value]
        return cls(
            word_id=word_id,
            weight=weight,
            learnt_at_utc=float(payload.get("learntAtUtc", 0.0)),
            last_reviewed_at_utc=float(
                payload.get("lastReviewedAtUtc", payload.get("learntAtUtc", 0.0))
            ),
            review_count=max(0, int(payload.get("reviewCount", 0))),
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
