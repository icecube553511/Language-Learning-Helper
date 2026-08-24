from __future__ import annotations

from math import exp

from .models import ReviewRating, ReviewState


SECONDS_PER_DAY = 86_400.0


def schedule_review(
    current: ReviewState,
    rating: ReviewRating | str,
    reviewed_at_utc: float,
) -> ReviewState:
    resolved = rating if isinstance(rating, ReviewRating) else ReviewRating(rating)
    first = current.repetitions == 0
    ease = current.ease
    repetitions = current.repetitions
    lapses = current.lapses

    if resolved is ReviewRating.AGAIN:
        interval = 10.0 / 1440.0
        ease = max(1.3, ease - 0.20)
        repetitions = 0
        lapses += 1
        state = "relearning"
    elif resolved is ReviewRating.HARD:
        interval = 1.0 if first else max(1.0, current.interval_days * 1.2)
        ease = max(1.3, ease - 0.15)
        repetitions += 1
        state = "learning" if first else "review"
    elif resolved is ReviewRating.GOOD:
        interval = 3.0 if first else current.interval_days * ease
        repetitions += 1
        state = "review"
    else:
        interval = 7.0 if first else current.interval_days * ease * 1.3
        ease = min(3.0, ease + 0.15)
        repetitions += 1
        state = "review"

    return ReviewState(
        word_id=current.word_id,
        state=state,
        interval_days=interval,
        ease=ease,
        repetitions=repetitions,
        lapses=lapses,
        due_at_utc=reviewed_at_utc + interval * SECONDS_PER_DAY,
        last_reviewed_at_utc=reviewed_at_utc,
    )


def retention_at(state: ReviewState, at_utc: float) -> float:
    if state.last_reviewed_at_utc is None:
        return 0.0
    elapsed_days = max(0.0, at_utc - state.last_reviewed_at_utc) / SECONDS_PER_DAY
    stability = max(state.interval_days, 1.0 / 144.0)
    return exp(-elapsed_days / stability)
