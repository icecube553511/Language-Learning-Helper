from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import ClassVar, Iterable


# Balance constants are intentionally centralized: later releases are expected
# to tune these values without changing the reward/recovery algorithm.
DEFAULT_SATIETY = 50.0
DEFAULT_FOOD_RESERVE = 0.0
SATIETY_MINIMUM = 0.0
SATIETY_MAXIMUM = 100.0
FOOD_RESERVE_MINIMUM = 0.0
FOOD_RESERVE_MAXIMUM = 200.0
HUNGRY_BELOW = 30.0
SATISFIED_FROM = 70.0
RESERVE_REFILL_TARGET = 50.0
SATIETY_OVERFLOW_TO_RESERVE_RATIO = 0.20


class Mood(str, Enum):
    SAD = "sad"
    WORRIED = "worried"
    HAPPY = "happy"
    EXCITED = "excited"
    BORED = "bored"
    CALM = "calm"

    @property
    def label(self) -> str:
        return {
            Mood.SAD: "悲伤",
            Mood.WORRIED: "担忧",
            Mood.HAPPY: "开心",
            Mood.EXCITED: "兴奋",
            Mood.BORED: "无聊",
            Mood.CALM: "平静",
        }[self]


class HungerState(str, Enum):
    HUNGRY = "hungry"
    SATED = "sated"
    SATISFIED = "satisfied"


class ReviewRecoveryTag(str, Enum):
    FORGOT = "ToBeReviewed_Forgot"
    VAGUE = "ToBeReviewed_Vague"

    @classmethod
    def from_persisted(cls, raw: object) -> ReviewRecoveryTag | None:
        """Decode legacy scalar/list shapes with deterministic conflict precedence."""
        candidates = tuple(_marker_candidates(raw))
        if cls.FORGOT.value in candidates:
            return cls.FORGOT
        if cls.VAGUE.value in candidates:
            return cls.VAGUE
        return None


class RatingPhase(str, Enum):
    STUDY = "study"
    REVIEW = "review"


def _marker_candidates(raw: object) -> Iterable[str]:
    if isinstance(raw, ReviewRecoveryTag):
        yield raw.value
    elif isinstance(raw, str):
        yield raw
    elif isinstance(raw, dict):
        for key, enabled in raw.items():
            if enabled:
                yield str(key)
    elif isinstance(raw, (list, tuple, set, frozenset)):
        for value in raw:
            yield from _marker_candidates(value)


def _finite_float(value: object, field_name: str) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a finite float") from error
    if not math.isfinite(resolved):
        raise ValueError(f"{field_name} must be a finite float")
    return resolved


def _restored_float(value: object, default: float) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError):
        return default
    return resolved if math.isfinite(resolved) else default


@dataclass(frozen=True)
class FoodJar:
    """Bingzi's immutable reserve container.

    The value object owns reserve capacity and transfer behavior. Persistence
    deliberately continues to encode only its scalar amount as ``foodReserve``.
    """

    stored_satiety: float = DEFAULT_FOOD_RESERVE

    capacity: ClassVar[float] = FOOD_RESERVE_MAXIMUM
    overflow_storage_ratio: ClassVar[float] = SATIETY_OVERFLOW_TO_RESERVE_RATIO

    def __post_init__(self) -> None:
        stored = min(
            self.capacity,
            max(
                FOOD_RESERVE_MINIMUM,
                _finite_float(self.stored_satiety, "stored_satiety"),
            ),
        )
        object.__setattr__(self, "stored_satiety", stored)

    @property
    def remaining_capacity(self) -> float:
        return self.capacity - self.stored_satiety

    def add_direct(self, amount: float) -> FoodJar:
        """Store a direct reserve gain at 100%, bounded by jar capacity."""
        addition = _finite_float(amount, "direct_food_reserve_gain")
        if addition < 0.0:
            raise ValueError("direct_food_reserve_gain must be non-negative")
        return FoodJar(self.stored_satiety + addition)

    def store_overflow(self, satiety_overflow: float) -> FoodJar:
        """Convert positive satiety overflow at the configured 20% ratio."""
        overflow = _finite_float(satiety_overflow, "satiety_overflow")
        if overflow < 0.0:
            raise ValueError("satiety_overflow must be non-negative")
        return FoodJar(
            self.stored_satiety + overflow * self.overflow_storage_ratio
        )

    def withdraw(self, requested: float) -> tuple[FoodJar, float]:
        """Return the updated jar and the amount available for a 1:1 refill."""
        requested_amount = _finite_float(requested, "requested_food_reserve")
        if requested_amount < 0.0:
            raise ValueError("requested_food_reserve must be non-negative")
        transferred = min(requested_amount, self.stored_satiety)
        return FoodJar(self.stored_satiety - transferred), transferred


@dataclass(frozen=True, init=False)
class PetVitals:
    satiety: float
    food_jar: FoodJar
    mood: Mood

    def __init__(
        self,
        satiety: float = DEFAULT_SATIETY,
        food_reserve: float | FoodJar = DEFAULT_FOOD_RESERVE,
        mood: Mood = Mood.CALM,
        *,
        food_jar: FoodJar | None = None,
    ) -> None:
        """Compose a FoodJar while retaining the previous scalar constructor."""
        if food_jar is not None:
            if isinstance(food_reserve, FoodJar) or food_reserve != DEFAULT_FOOD_RESERVE:
                raise ValueError("provide either food_reserve or food_jar, not both")
            jar = food_jar
        elif isinstance(food_reserve, FoodJar):
            jar = food_reserve
        else:
            jar = FoodJar(food_reserve)

        satiety = min(
            SATIETY_MAXIMUM,
            max(SATIETY_MINIMUM, _finite_float(satiety, "satiety")),
        )
        try:
            resolved_mood = mood if isinstance(mood, Mood) else Mood(str(mood))
        except ValueError as error:
            raise ValueError("mood must be a supported Mood") from error

        if satiety < HUNGRY_BELOW:
            jar, transfer = jar.withdraw(RESERVE_REFILL_TARGET - satiety)
            satiety += transfer

        object.__setattr__(self, "satiety", satiety)
        object.__setattr__(self, "food_jar", jar)
        object.__setattr__(self, "mood", resolved_mood)

    @property
    def food_reserve(self) -> float:
        """Compatibility view for callers and the stable persisted scalar."""
        return self.food_jar.stored_satiety

    @property
    def hunger_state(self) -> HungerState:
        if self.satiety < HUNGRY_BELOW:
            return HungerState.HUNGRY
        if self.satiety < SATISFIED_FROM:
            return HungerState.SATED
        return HungerState.SATISFIED

    def to_dict(self) -> dict[str, object]:
        return {
            "satiety": self.satiety,
            "foodReserve": self.food_reserve,
            "mood": self.mood.value,
        }

    @classmethod
    def from_dict(cls, payload: object) -> PetVitals:
        if not isinstance(payload, dict):
            return cls()
        raw_mood = payload.get("mood", Mood.CALM.value)
        try:
            mood = Mood(str(raw_mood))
        except ValueError:
            mood = Mood.CALM
        return cls(
            satiety=_restored_float(payload.get("satiety"), DEFAULT_SATIETY),
            food_reserve=_restored_float(
                payload.get("foodReserve", payload.get("food_reserve")),
                DEFAULT_FOOD_RESERVE,
            ),
            mood=mood,
        )


@dataclass(frozen=True)
class RatingReward:
    satiety_gain: float
    food_reserve_gain: float
    next_marker: ReviewRecoveryTag | None


@dataclass(frozen=True)
class RatingOutcome:
    vitals: PetVitals
    prior_marker: ReviewRecoveryTag | None
    next_marker: ReviewRecoveryTag | None
    satiety_gain: float
    food_reserve_gain: float


# These reward amounts are balance parameters and are expected to change in a
# later tuning pass. Keep the complete matrix here rather than in UI callbacks.
_STUDY_REWARDS: dict[str, tuple[float, float, ReviewRecoveryTag | None]] = {
    "again": (0.0, 0.0, ReviewRecoveryTag.FORGOT),
    "hard": (0.0, 0.0, ReviewRecoveryTag.VAGUE),
    "good": (2.0, 0.0, None),
    "easy": (3.0, 0.0, None),
}

_REVIEW_SUCCESS_REWARDS: dict[
    ReviewRecoveryTag | None,
    dict[str, tuple[float, float]],
] = {
    None: {"good": (0.2, 0.5), "easy": (0.3, 0.8)},
    ReviewRecoveryTag.VAGUE: {"good": (1.0, 0.7), "easy": (1.2, 1.0)},
    ReviewRecoveryTag.FORGOT: {"good": (1.5, 0.9), "easy": (2.0, 1.4)},
}


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value)).strip().lower()


def normalize_review_marker(raw: object) -> ReviewRecoveryTag | None:
    return ReviewRecoveryTag.from_persisted(raw)


def reward_for_rating(
    phase: RatingPhase | str,
    rating: object,
    prior_marker: ReviewRecoveryTag | str | None = None,
) -> RatingReward:
    resolved_phase = RatingPhase(_enum_value(phase))
    resolved_rating = _enum_value(rating)
    if resolved_rating not in _STUDY_REWARDS:
        raise ValueError(f"Unsupported rating: {resolved_rating}")
    marker = normalize_review_marker(prior_marker)

    if resolved_phase is RatingPhase.STUDY:
        satiety, reserve, next_marker = _STUDY_REWARDS[resolved_rating]
        return RatingReward(satiety, reserve, next_marker)

    if resolved_rating == "again":
        return RatingReward(0.0, 0.0, ReviewRecoveryTag.FORGOT)
    if resolved_rating == "hard":
        return RatingReward(0.0, 0.0, ReviewRecoveryTag.VAGUE)
    satiety, reserve = _REVIEW_SUCCESS_REWARDS[marker][resolved_rating]
    return RatingReward(satiety, reserve, None)


def apply_vital_change(
    vitals: PetVitals,
    satiety_gain: float = 0.0,
    food_reserve_gain: float = 0.0,
) -> PetVitals:
    satiety_addition = _finite_float(satiety_gain, "satiety_gain")
    reserve_addition = _finite_float(food_reserve_gain, "food_reserve_gain")
    raw_satiety = vitals.satiety + satiety_addition
    overflow = max(0.0, raw_satiety - SATIETY_MAXIMUM)
    satiety = min(SATIETY_MAXIMUM, max(SATIETY_MINIMUM, raw_satiety))
    food_jar = vitals.food_jar.store_overflow(overflow).add_direct(
        reserve_addition
    )
    return PetVitals(satiety=satiety, food_jar=food_jar, mood=vitals.mood)


def apply_rating_reward(
    vitals: PetVitals,
    phase: RatingPhase | str,
    rating: object,
    prior_marker: ReviewRecoveryTag | str | None = None,
) -> RatingOutcome:
    marker = normalize_review_marker(prior_marker)
    reward = reward_for_rating(phase, rating, marker)
    updated = apply_vital_change(
        vitals,
        satiety_gain=reward.satiety_gain,
        food_reserve_gain=reward.food_reserve_gain,
    )
    return RatingOutcome(
        vitals=updated,
        prior_marker=marker,
        next_marker=reward.next_marker,
        satiety_gain=reward.satiety_gain,
        food_reserve_gain=reward.food_reserve_gain,
    )


# Naming alias for application code that treats a rating as an answer outcome.
apply_answer_reward = apply_rating_reward
