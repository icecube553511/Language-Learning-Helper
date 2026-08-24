package com.lexitrack.learning.domain

import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min

const val SCHEDULER_VERSION = "lexi-sm2-v1"
private const val SECONDS_PER_DAY = 86_400.0

enum class ReviewRating(val contractName: String) {
    AGAIN("again"),
    HARD("hard"),
    GOOD("good"),
    EASY("easy"),
    ;

    companion object {
        fun fromContractName(value: String): ReviewRating = entries.first {
            it.contractName == value.lowercase()
        }
    }
}

enum class CardPhase(val contractName: String) {
    NEW("new"),
    LEARNING("learning"),
    REVIEW("review"),
    RELEARNING("relearning"),
    ;

    companion object {
        fun fromContractName(value: String): CardPhase = entries.first {
            it.contractName == value.lowercase()
        }
    }
}

data class ScheduleState(
    val phase: CardPhase = CardPhase.NEW,
    val intervalDays: Double = 0.0,
    val ease: Double = 2.5,
    val repetitions: Int = 0,
    val lapses: Int = 0,
    val dueAtUtc: Double = 0.0,
    val lastReviewedAtUtc: Double? = null,
) {
    companion object {
        val Initial = ScheduleState()
    }
}

data class ReviewEvent(
    val wordId: String,
    val reviewedAtUtc: Double,
    val rating: ReviewRating,
    val resultingIntervalDays: Double,
)

object LexiSm2Scheduler {
    fun review(
        current: ScheduleState,
        rating: ReviewRating,
        reviewedAtUtc: Double,
    ): ScheduleState {
        require(reviewedAtUtc.isFinite() && reviewedAtUtc >= 0.0) {
            "reviewedAtUtc must be a non-negative finite epoch value"
        }
        val firstSuccessfulReview = current.repetitions == 0
        val next = when (rating) {
            ReviewRating.AGAIN -> current.copy(
                phase = CardPhase.RELEARNING,
                intervalDays = 10.0 / 1440.0,
                ease = max(1.3, current.ease - 0.20),
                repetitions = 0,
                lapses = current.lapses + 1,
            )

            ReviewRating.HARD -> current.copy(
                phase = if (firstSuccessfulReview) CardPhase.LEARNING else CardPhase.REVIEW,
                intervalDays = if (firstSuccessfulReview) {
                    1.0
                } else {
                    max(1.0, current.intervalDays * 1.2)
                },
                ease = max(1.3, current.ease - 0.15),
                repetitions = current.repetitions + 1,
            )

            ReviewRating.GOOD -> current.copy(
                phase = CardPhase.REVIEW,
                intervalDays = if (firstSuccessfulReview) 3.0 else current.intervalDays * current.ease,
                repetitions = current.repetitions + 1,
            )

            ReviewRating.EASY -> current.copy(
                phase = CardPhase.REVIEW,
                intervalDays = if (firstSuccessfulReview) {
                    7.0
                } else {
                    current.intervalDays * current.ease * 1.3
                },
                ease = min(3.0, current.ease + 0.15),
                repetitions = current.repetitions + 1,
            )
        }
        return next.copy(
            dueAtUtc = reviewedAtUtc + next.intervalDays * SECONDS_PER_DAY,
            lastReviewedAtUtc = reviewedAtUtc,
        )
    }

    fun retention(
        elapsedDays: Double,
        intervalDays: Double,
    ): Double = exp(-max(0.0, elapsedDays) / max(intervalDays, 1.0 / 144.0))
}
