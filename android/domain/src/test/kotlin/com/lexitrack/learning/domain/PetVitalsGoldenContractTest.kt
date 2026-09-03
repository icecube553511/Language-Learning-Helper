package com.lexitrack.learning.domain

import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.math.max
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class PetVitalsGoldenContractTest {
    private val golden: JsonObject by lazy {
        Json.parseToJsonElement(
            File(requireNotNull(System.getProperty("pet.vitals.golden.path"))).readText(),
        ).jsonObject
    }

    @Test
    fun `defaults moods and hunger boundaries match the shared contract`() {
        val defaults = golden.getValue("defaults").jsonObject
        val restored = PetVitals.restore()
        assertEquals(defaults.double("satiety"), restored.satiety, 0.0)
        assertEquals(defaults.double("foodReserve"), restored.foodReserve, 0.0)
        assertEquals(defaults.double("foodReserve"), restored.foodJar.storedSatiety, 0.0)
        assertEquals(defaults.string("mood"), restored.mood.persistedValue)

        val expectedMoods = golden.getValue("moods").jsonArray.associate { value ->
            val item = value.jsonObject
            item.string("name") to item.string("label")
        }
        assertEquals(expectedMoods, Mood.entries.associate { it.persistedValue to it.label })

        golden.getValue("hungerStateVectors").jsonArray.forEach { value ->
            val vector = value.jsonObject
            val vitals = PetVitals.restore(
                satiety = vector.double("satiety"),
                foodReserve = 0.0,
            )
            assertEquals(vector.string("expected"), vitals.hungerState.persistedValue)
        }
    }

    @Test
    fun `food jar is the immutable aggregate value object from the shared contract`() {
        val foodJarContract = golden.getValue("foodJar").jsonObject
        val bounds = golden.getValue("bounds").jsonObject
        val overflowPolicy = golden.getValue("overflow").jsonObject
        assertEquals("value-object", foodJarContract.string("model"))
        assertEquals("pet-vitals", foodJarContract.string("aggregateOwner"))
        assertEquals("foodReserve", foodJarContract.string("persistedField"))
        assertEquals(bounds.double("foodReserveMaximum"), FoodJar.CAPACITY, 0.0)

        val vectors = golden.getValue("vitalChangeVectors").jsonArray
            .associateBy { it.jsonObject.string("name") }
        val overflow = vectors.getValue("satiety-overflow-converts-at-twenty-percent").jsonObject
        val original = FoodJar.restore(overflow.double("foodReserve"))
        val rawOverflow = max(
            0.0,
            overflow.double("satiety") + overflow.double("satietyGain") -
                bounds.double("satietyMaximum"),
        )
        val overflowStored = original.storeOverflow(rawOverflow)
        assertEquals(overflow.double("expectedFoodReserve"), overflowStored.storedSatiety, 1e-12)
        assertEquals(overflow.double("foodReserve"), original.storedSatiety, 0.0)

        val direct = vectors.getValue("direct-food-reserve-is-not-discounted").jsonObject
        assertEquals(
            direct.double("expectedFoodReserve"),
            FoodJar.restore(direct.double("foodReserve"))
                .addDirect(direct.double("foodReserveGain"))
                .storedSatiety,
            1e-12,
        )
        assertEquals(
            FoodJar.CAPACITY,
            FoodJar.restore(FoodJar.CAPACITY - 1.0).addDirect(FoodJar.CAPACITY).storedSatiety,
            0.0,
        )

        val refill = vectors.getValue("hungry-state-refills-to-fifty").jsonObject
        val requested = golden.getValue("hunger").jsonObject.double("reserveRefillTarget") -
            refill.double("satiety")
        val withdrawal = FoodJar.restore(refill.double("foodReserve")).withdraw(requested)
        assertEquals(requested, withdrawal.withdrawn, 0.0)
        assertEquals(refill.double("expectedFoodReserve"), withdrawal.foodJar.storedSatiety, 0.0)
        assertEquals(
            overflowPolicy.double("satietyToFoodReserveRatio"),
            PetVitalsBalance.SATIETY_OVERFLOW_TO_RESERVE_RATIO,
            0.0,
        )
        assertFailsWith<IllegalArgumentException> { FoodJar.Empty.addDirect(-1.0) }
        assertFailsWith<IllegalArgumentException> { FoodJar.Empty.storeOverflow(-1.0) }
        assertFailsWith<IllegalArgumentException> { FoodJar.Empty.withdraw(-1.0) }
        assertFailsWith<IllegalArgumentException> { PetVitalChange(0.0, -1.0) }
    }

    @Test
    fun `every shared reward rule is implemented`() {
        val defaults = golden.getValue("defaults").jsonObject
        golden.getValue("rewardRules").jsonArray.forEach { value ->
            val rule = value.jsonObject
            val priorTag = ReviewRecoveryTag.fromPersisted(rule.optionalString("priorTag"))
            val outcome = reduceRatingReward(
                vitals = PetVitals.restore(
                    satiety = defaults.double("satiety"),
                    foodReserve = defaults.double("foodReserve"),
                ),
                phase = when (rule.string("phase")) {
                    "study" -> RatingPhase.STUDY
                    "review" -> RatingPhase.REVIEW
                    else -> error("Unknown phase")
                },
                rating = when (rule.string("rating")) {
                    "again" -> ReviewRating.AGAIN
                    "hard" -> ReviewRating.HARD
                    "good" -> ReviewRating.GOOD
                    "easy" -> ReviewRating.EASY
                    else -> error("Unknown rating")
                },
                priorTag = priorTag,
            )

            assertEquals(rule.double("satietyGain"), outcome.change.satietyGain, 1e-12)
            assertEquals(rule.double("foodReserveGain"), outcome.change.foodReserveGain, 1e-12)
            assertEquals(rule.optionalString("nextTag"), outcome.nextTag?.persistedValue)
            assertEquals(
                defaults.double("satiety") + rule.double("satietyGain"),
                outcome.vitals.satiety,
                1e-12,
            )
            assertEquals(rule.double("foodReserveGain"), outcome.vitals.foodReserve, 1e-12)
        }
    }

    @Test
    fun `vital mutation order and bounds match every shared vector`() {
        golden.getValue("vitalChangeVectors").jsonArray.forEach { value ->
            val vector = value.jsonObject
            val initial = PetVitals.restore(
                satiety = vector.double("satiety"),
                foodReserve = vector.double("foodReserve"),
            )
            val result = applyVitalChange(
                initial,
                PetVitalChange(
                    satietyGain = vector.double("satietyGain"),
                    foodReserveGain = vector.double("foodReserveGain"),
                ),
            )
            assertEquals(vector.double("expectedSatiety"), result.satiety, 1e-9, vector.string("name"))
            assertEquals(
                vector.double("expectedFoodReserve"),
                result.foodReserve,
                1e-9,
                vector.string("name"),
            )
        }
    }

    @Test
    fun `restore rejects nonfinite state and malformed marker conflict prefers forgot`() {
        assertEquals(PetVitals.Default, PetVitals.restore(Double.NaN, Double.POSITIVE_INFINITY, null))
        assertEquals(
            ReviewRecoveryTag.FORGOT,
            ReviewRecoveryTag.decodePersisted(
                listOf(ReviewRecoveryTag.VAGUE.persistedValue, ReviewRecoveryTag.FORGOT.persistedValue),
            ),
        )
    }

    private fun JsonObject.double(key: String): Double = getValue(key).jsonPrimitive.double
    private fun JsonObject.string(key: String): String = getValue(key).jsonPrimitive.content
    private fun JsonObject.optionalString(key: String): String? = getValue(key).jsonPrimitive.contentOrNull
}
