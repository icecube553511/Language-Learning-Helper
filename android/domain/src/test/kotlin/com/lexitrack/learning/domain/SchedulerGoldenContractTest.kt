package com.lexitrack.learning.domain

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

class SchedulerGoldenContractTest {
    @Test
    fun `scheduler matches shared golden vectors`() {
        val path = requireNotNull(System.getProperty("scheduler.golden.path"))
        val root = Json.parseToJsonElement(File(path).readText()).jsonObject
        assertEquals(SCHEDULER_VERSION, root.getValue("algorithmVersion").jsonPrimitive.content)

        val initialJson = root.getValue("initial").jsonObject
        val initial = ScheduleState(
            phase = CardPhase.fromContractName(initialJson.getValue("state").jsonPrimitive.content),
            intervalDays = initialJson.getValue("intervalDays").jsonPrimitive.double,
            ease = initialJson.getValue("ease").jsonPrimitive.double,
            repetitions = initialJson.getValue("repetitions").jsonPrimitive.int,
            lapses = initialJson.getValue("lapses").jsonPrimitive.int,
        )

        root.getValue("vectors").jsonArray.forEach { vectorElement ->
            val vector = vectorElement.jsonObject
            val expected = vector.getValue("expected").jsonObject
            val actual = LexiSm2Scheduler.review(
                current = initial,
                rating = ReviewRating.fromContractName(vector.getValue("rating").jsonPrimitive.content),
                reviewedAtUtc = vector.getValue("reviewedAtUtc").jsonPrimitive.double,
            )

            assertEquals(
                CardPhase.fromContractName(expected.getValue("state").jsonPrimitive.content),
                actual.phase,
                vector.getValue("name").jsonPrimitive.content,
            )
            assertClose(expected.getValue("intervalDays").jsonPrimitive.double, actual.intervalDays)
            assertClose(expected.getValue("ease").jsonPrimitive.double, actual.ease)
            assertEquals(expected.getValue("repetitions").jsonPrimitive.int, actual.repetitions)
            assertEquals(expected.getValue("lapses").jsonPrimitive.int, actual.lapses)
            assertClose(expected.getValue("dueAtUtc").jsonPrimitive.double, actual.dueAtUtc)
        }
    }

    @Test
    fun `retention decreases over time`() {
        val today = LexiSm2Scheduler.retention(0.0, 3.0)
        val tomorrow = LexiSm2Scheduler.retention(1.0, 3.0)
        val nextWeek = LexiSm2Scheduler.retention(7.0, 3.0)
        assertTrue(today > tomorrow)
        assertTrue(tomorrow > nextWeek)
    }

    private fun assertClose(expected: Double, actual: Double) {
        assertEquals(expected, actual, absoluteTolerance = 1e-9)
    }
}
