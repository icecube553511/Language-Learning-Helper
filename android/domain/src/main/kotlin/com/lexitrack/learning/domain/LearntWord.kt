package com.lexitrack.learning.domain

data class LearntWord(
    val wordId: String,
    val weight: Double,
    val learntAtUtc: Double,
    val lastReviewedAtUtc: Double,
    val reviewCount: Int = 0,
) {
    init {
        require(wordId.isNotBlank()) { "Learnt word id cannot be blank" }
        require(weight.isFinite() && weight in MIN_WEIGHT..MAX_WEIGHT) {
            "Learnt word weight must be between $MIN_WEIGHT and $MAX_WEIGHT"
        }
        require(learntAtUtc.isFinite() && learntAtUtc >= 0.0) {
            "learntAtUtc must be a non-negative finite epoch value"
        }
        require(lastReviewedAtUtc.isFinite() && lastReviewedAtUtc >= learntAtUtc) {
            "lastReviewedAtUtc must be no earlier than learntAtUtc"
        }
        require(reviewCount >= 0) { "Learnt word review count cannot be negative" }
    }

    companion object {
        const val MIN_WEIGHT = 0.05
        const val MAX_WEIGHT = 1.0
    }
}

object LearntWordWeights {
    const val AGAIN = 1.0
    const val HARD = 0.8
    const val GOOD = 0.2
    const val EASY = 0.05
    const val LEGACY_DEFAULT = GOOD
}

fun initialWeightFor(rating: ReviewRating): Double = when (rating) {
    ReviewRating.AGAIN -> LearntWordWeights.AGAIN
    ReviewRating.HARD -> LearntWordWeights.HARD
    ReviewRating.GOOD -> LearntWordWeights.GOOD
    ReviewRating.EASY -> LearntWordWeights.EASY
}

fun updatedWeightForReview(currentWeight: Double, rating: ReviewRating): Double {
    require(currentWeight.isFinite() && currentWeight in LearntWord.MIN_WEIGHT..LearntWord.MAX_WEIGHT) {
        "Current learnt word weight is invalid"
    }
    return when (rating) {
        ReviewRating.AGAIN,
        ReviewRating.HARD -> currentWeight

        ReviewRating.GOOD -> LearntWordWeights.GOOD
        ReviewRating.EASY -> LearntWordWeights.EASY
    }
}
