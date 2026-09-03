package com.lexitrack.learning.domain

import kotlin.math.max
import kotlin.math.min

/**
 * Balance parameters are centralized because product tuning will change these
 * values later. Keep reward and threshold numbers out of use cases and UI code.
 */
object PetVitalsBalance {
    const val DEFAULT_SATIETY = 50.0
    const val DEFAULT_FOOD_RESERVE = 0.0
    const val MIN_SATIETY = 0.0
    const val MAX_SATIETY = 100.0
    const val MIN_FOOD_RESERVE = 0.0
    const val MAX_FOOD_RESERVE = 200.0
    const val HUNGRY_BELOW = 30.0
    const val SATISFIED_FROM = 70.0
    const val RESERVE_REFILL_TARGET = 50.0
    const val SATIETY_OVERFLOW_TO_RESERVE_RATIO = 0.20

    const val STUDY_GOOD_SATIETY = 2.0
    const val STUDY_EASY_SATIETY = 3.0

    const val REVIEW_GOOD_SATIETY = 0.2
    const val REVIEW_GOOD_RESERVE = 0.5
    const val REVIEW_EASY_SATIETY = 0.3
    const val REVIEW_EASY_RESERVE = 0.8

    const val REVIEW_VAGUE_GOOD_SATIETY = 1.0
    const val REVIEW_VAGUE_GOOD_RESERVE = 0.7
    const val REVIEW_VAGUE_EASY_SATIETY = 1.2
    const val REVIEW_VAGUE_EASY_RESERVE = 1.0

    const val REVIEW_FORGOT_GOOD_SATIETY = 1.5
    const val REVIEW_FORGOT_GOOD_RESERVE = 0.9
    const val REVIEW_FORGOT_EASY_SATIETY = 2.0
    const val REVIEW_FORGOT_EASY_RESERVE = 1.4
}

enum class Mood(val persistedValue: String, val label: String) {
    SAD("sad", "悲伤"),
    WORRIED("worried", "担忧"),
    HAPPY("happy", "开心"),
    EXCITED("excited", "兴奋"),
    BORED("bored", "无聊"),
    CALM("calm", "平静");

    companion object {
        fun fromPersisted(value: String?): Mood? = entries.firstOrNull {
            it.persistedValue == value?.trim()?.lowercase()
        }
    }
}

enum class HungerState(val persistedValue: String) {
    HUNGRY("hungry"),
    SATED("sated"),
    SATISFIED("satisfied"),
}

enum class ReviewRecoveryTag(val persistedValue: String) {
    FORGOT("ToBeReviewed_Forgot"),
    VAGUE("ToBeReviewed_Vague");

    companion object {
        fun fromPersisted(value: String?): ReviewRecoveryTag? = entries.firstOrNull {
            it.persistedValue == value
        }

        /** Forgot wins when malformed legacy data contains both markers. */
        fun decodePersisted(values: Iterable<String>): ReviewRecoveryTag? {
            val candidates = values.toSet()
            return when {
                FORGOT.persistedValue in candidates -> FORGOT
                VAGUE.persistedValue in candidates -> VAGUE
                else -> null
            }
        }
    }
}

enum class RatingPhase {
    STUDY,
    REVIEW,
}

@ConsistentCopyVisibility
data class FoodJar private constructor(
    val storedSatiety: Double,
) {
    init {
        require(storedSatiety.isFinite() && storedSatiety in 0.0..CAPACITY) {
            "Stored satiety must be finite and within 0..$CAPACITY"
        }
    }

    val remainingCapacity: Double
        get() = CAPACITY - storedSatiety

    val isEmpty: Boolean
        get() = storedSatiety == 0.0

    fun addDirect(amount: Double): FoodJar {
        require(amount.isFinite() && amount >= 0.0) {
            "Direct food reserve addition must be finite and non-negative"
        }
        return restore(storedSatiety + amount)
    }

    fun storeOverflow(satietyOverflow: Double): FoodJar {
        require(satietyOverflow.isFinite() && satietyOverflow >= 0.0) {
            "Satiety overflow must be finite and non-negative"
        }
        return addDirect(satietyOverflow * PetVitalsBalance.SATIETY_OVERFLOW_TO_RESERVE_RATIO)
    }

    fun withdraw(requested: Double): FoodJarWithdrawal {
        require(requested.isFinite() && requested >= 0.0) {
            "Food reserve withdrawal must be finite and non-negative"
        }
        val withdrawn = min(requested, storedSatiety)
        return FoodJarWithdrawal(
            foodJar = FoodJar(storedSatiety - withdrawn),
            withdrawn = withdrawn,
        )
    }

    companion object {
        const val CAPACITY = PetVitalsBalance.MAX_FOOD_RESERVE

        val Empty: FoodJar
            get() = FoodJar(PetVitalsBalance.DEFAULT_FOOD_RESERVE)

        fun restore(storedSatiety: Double?): FoodJar = FoodJar(
            storedSatiety
                ?.takeIf(Double::isFinite)
                ?.coerceIn(PetVitalsBalance.MIN_FOOD_RESERVE, CAPACITY)
                ?: PetVitalsBalance.DEFAULT_FOOD_RESERVE,
        )
    }
}

data class FoodJarWithdrawal(
    val foodJar: FoodJar,
    val withdrawn: Double,
) {
    init {
        require(withdrawn.isFinite() && withdrawn >= 0.0) {
            "Withdrawn food reserve must be finite and non-negative"
        }
    }
}

@ConsistentCopyVisibility
data class PetVitals private constructor(
    val satiety: Double,
    val foodJar: FoodJar,
    val mood: Mood,
) {
    init {
        require(satiety.isFinite() && satiety in PetVitalsBalance.MIN_SATIETY..PetVitalsBalance.MAX_SATIETY) {
            "Satiety must be finite and within 0..100"
        }
        require(satiety >= PetVitalsBalance.HUNGRY_BELOW || foodJar.isEmpty) {
            "Hungry vitals must transfer all available reserve before construction"
        }
    }

    /** Stable scalar compatibility for callers and the persisted wire shape. */
    val foodReserve: Double
        get() = foodJar.storedSatiety

    val hungerState: HungerState
        get() = when {
            satiety < PetVitalsBalance.HUNGRY_BELOW -> HungerState.HUNGRY
            satiety < PetVitalsBalance.SATISFIED_FROM -> HungerState.SATED
            else -> HungerState.SATISFIED
        }

    companion object {
        val Default: PetVitals
            get() = PetVitals(
                satiety = PetVitalsBalance.DEFAULT_SATIETY,
                foodJar = FoodJar.Empty,
                mood = Mood.CALM,
            )

        /**
         * Restores untrusted persisted values, clamps them, and immediately
         * applies the automatic hungry-state reserve transfer.
         */
        fun restore(
            satiety: Double? = null,
            foodReserve: Double? = null,
            mood: Mood? = null,
        ): PetVitals = restore(
            satiety = satiety,
            foodJar = FoodJar.restore(foodReserve),
            mood = mood,
        )

        fun restore(
            satiety: Double?,
            foodJar: FoodJar,
            mood: Mood? = null,
        ): PetVitals {
            var restoredSatiety = satiety
                ?.takeIf(Double::isFinite)
                ?.coerceIn(PetVitalsBalance.MIN_SATIETY, PetVitalsBalance.MAX_SATIETY)
                ?: PetVitalsBalance.DEFAULT_SATIETY
            var restoredJar = foodJar

            if (restoredSatiety < PetVitalsBalance.HUNGRY_BELOW) {
                val withdrawal = restoredJar.withdraw(
                    PetVitalsBalance.RESERVE_REFILL_TARGET - restoredSatiety,
                )
                restoredSatiety += withdrawal.withdrawn
                restoredJar = withdrawal.foodJar
            }
            return PetVitals(restoredSatiety, restoredJar, mood ?: Mood.CALM)
        }
    }
}

data class PetVitalChange(
    val satietyGain: Double,
    val foodReserveGain: Double,
) {
    init {
        require(satietyGain.isFinite()) { "Satiety gain must be finite" }
        require(foodReserveGain.isFinite() && foodReserveGain >= 0.0) {
            "Food reserve gain must be finite and non-negative"
        }
    }

    companion object {
        val None = PetVitalChange(0.0, 0.0)
    }
}

data class PetRewardOutcome(
    val vitals: PetVitals,
    val nextTag: ReviewRecoveryTag?,
    val change: PetVitalChange,
)

fun applyVitalChange(vitals: PetVitals, change: PetVitalChange): PetVitals {
    val rawSatiety = vitals.satiety + change.satietyGain
    val overflow = max(0.0, rawSatiety - PetVitalsBalance.MAX_SATIETY)
    val nextSatiety = rawSatiety.coerceIn(
        PetVitalsBalance.MIN_SATIETY,
        PetVitalsBalance.MAX_SATIETY,
    )
    val nextJar = vitals.foodJar
        .storeOverflow(overflow)
        .addDirect(change.foodReserveGain)
    return PetVitals.restore(nextSatiety, nextJar, vitals.mood)
}

fun reduceRatingReward(
    vitals: PetVitals,
    phase: RatingPhase,
    rating: ReviewRating,
    priorTag: ReviewRecoveryTag?,
): PetRewardOutcome {
    val (change, nextTag) = resolveRatingReward(phase, rating, priorTag)
    return PetRewardOutcome(
        vitals = applyVitalChange(vitals, change),
        nextTag = nextTag,
        change = change,
    )
}

private fun resolveRatingReward(
    phase: RatingPhase,
    rating: ReviewRating,
    priorTag: ReviewRecoveryTag?,
): Pair<PetVitalChange, ReviewRecoveryTag?> = when (rating) {
    ReviewRating.AGAIN -> PetVitalChange.None to ReviewRecoveryTag.FORGOT
    ReviewRating.HARD -> PetVitalChange.None to ReviewRecoveryTag.VAGUE
    ReviewRating.GOOD -> when (phase) {
        RatingPhase.STUDY -> PetVitalChange(PetVitalsBalance.STUDY_GOOD_SATIETY, 0.0) to null
        RatingPhase.REVIEW -> reviewSuccessReward(priorTag, easy = false) to null
    }
    ReviewRating.EASY -> when (phase) {
        RatingPhase.STUDY -> PetVitalChange(PetVitalsBalance.STUDY_EASY_SATIETY, 0.0) to null
        RatingPhase.REVIEW -> reviewSuccessReward(priorTag, easy = true) to null
    }
}

private fun reviewSuccessReward(tag: ReviewRecoveryTag?, easy: Boolean): PetVitalChange = when (tag) {
    null -> if (easy) {
        PetVitalChange(PetVitalsBalance.REVIEW_EASY_SATIETY, PetVitalsBalance.REVIEW_EASY_RESERVE)
    } else {
        PetVitalChange(PetVitalsBalance.REVIEW_GOOD_SATIETY, PetVitalsBalance.REVIEW_GOOD_RESERVE)
    }
    ReviewRecoveryTag.VAGUE -> if (easy) {
        PetVitalChange(
            PetVitalsBalance.REVIEW_VAGUE_EASY_SATIETY,
            PetVitalsBalance.REVIEW_VAGUE_EASY_RESERVE,
        )
    } else {
        PetVitalChange(
            PetVitalsBalance.REVIEW_VAGUE_GOOD_SATIETY,
            PetVitalsBalance.REVIEW_VAGUE_GOOD_RESERVE,
        )
    }
    ReviewRecoveryTag.FORGOT -> if (easy) {
        PetVitalChange(
            PetVitalsBalance.REVIEW_FORGOT_EASY_SATIETY,
            PetVitalsBalance.REVIEW_FORGOT_EASY_RESERVE,
        )
    } else {
        PetVitalChange(
            PetVitalsBalance.REVIEW_FORGOT_GOOD_SATIETY,
            PetVitalsBalance.REVIEW_FORGOT_GOOD_RESERVE,
        )
    }
}
