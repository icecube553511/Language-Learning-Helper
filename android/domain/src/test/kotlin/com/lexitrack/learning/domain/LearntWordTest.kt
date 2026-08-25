package com.lexitrack.learning.domain

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

class LearntWordTest {
    @Test
    fun `weights match shared golden contract`() {
        val path = requireNotNull(System.getProperty("weighted.review.golden.path"))
        val root = Json.parseToJsonElement(File(path).readText()).jsonObject

        root.getValue("ratings").jsonArray.forEach { element ->
            val vector = element.jsonObject
            val rating = ReviewRating.fromContractName(
                vector.getValue("rating").jsonPrimitive.content,
            )
            assertEquals(
                vector.getValue("initialWeight").jsonPrimitive.double,
                initialWeightFor(rating),
            )
            assertEquals(
                vector.getValue("reviewWeight").jsonPrimitive.double,
                updatedWeightForReview(
                    vector.getValue("previousWeight").jsonPrimitive.double,
                    rating,
                ),
            )
        }
    }

    @Test
    fun `initial weights follow four rating contract`() {
        assertEquals(1.0, initialWeightFor(ReviewRating.AGAIN))
        assertEquals(0.8, initialWeightFor(ReviewRating.HARD))
        assertEquals(0.2, initialWeightFor(ReviewRating.GOOD))
        assertEquals(0.05, initialWeightFor(ReviewRating.EASY))
    }

    @Test
    fun `review again and hard retain current weight`() {
        assertEquals(0.8, updatedWeightForReview(0.8, ReviewRating.AGAIN))
        assertEquals(0.8, updatedWeightForReview(0.8, ReviewRating.HARD))
    }

    @Test
    fun `review good and easy replace current weight`() {
        assertEquals(0.2, updatedWeightForReview(1.0, ReviewRating.GOOD))
        assertEquals(0.05, updatedWeightForReview(1.0, ReviewRating.EASY))
    }
}
