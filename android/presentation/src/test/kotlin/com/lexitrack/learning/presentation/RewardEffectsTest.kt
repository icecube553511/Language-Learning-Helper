package com.lexitrack.learning.presentation

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.geometry.Rect
import com.lexitrack.learning.domain.PetPoint
import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.float
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.hypot

class RewardEffectsTest {
    private val golden by lazy {
        Json.parseToJsonElement(
            File(requireNotNull(System.getProperty("pet.vitals.golden.path"))).readText(),
        ).jsonObject
    }
    private val flightGolden by lazy { golden.getValue("rewardFlight").jsonObject }
    private val flightVectors by lazy { golden.getValue("rewardFlightVectors").jsonObject }

    @Test
    fun `animation tuning and study color match shared contract`() {
        assertEquals(flightGolden.long("frameMs"), RewardFlightTuning.FRAME_MS)
        assertEquals(flightGolden.long("spiralDurationMs"), RewardFlightTuning.SPIRAL_DURATION_MS)
        assertEquals(flightGolden.float("spiralTurns"), RewardFlightTuning.SPIRAL_TURNS, 0f)
        assertEquals(flightGolden.float("spiralRadiusStart"), RewardFlightTuning.SPIRAL_RADIUS_START, 0f)
        assertEquals(flightGolden.float("spiralRadiusEnd"), RewardFlightTuning.SPIRAL_RADIUS_END, 0f)
        assertEquals(flightGolden.float("homingInitialSpeed"), RewardFlightTuning.HOMING_INITIAL_SPEED, 0f)
        assertEquals(flightGolden.float("homingAcceleration"), RewardFlightTuning.HOMING_ACCELERATION, 0f)
        assertEquals(flightGolden.float("homingMaximumSpeed"), RewardFlightTuning.HOMING_MAXIMUM_SPEED, 0f)
        assertEquals(flightGolden.float("orbRadius"), RewardFlightTuning.ORB_RADIUS, 0f)
        assertEquals(flightGolden.long("trailLifetimeMs"), RewardFlightTuning.TRAIL_LIFETIME_MS)
        assertEquals(flightGolden.int("trailMaximumPoints"), RewardFlightTuning.TRAIL_MAXIMUM_POINTS)
        assertEquals(flightGolden.int("burstParticleCount"), RewardFlightTuning.BURST_PARTICLE_COUNT)
        assertEquals(flightGolden.long("burstDurationMs"), RewardFlightTuning.BURST_DURATION_MS)
        assertEquals(flightGolden.long("maximumLifetimeMs"), RewardFlightTuning.MAXIMUM_LIFETIME_MS)
        assertEquals(flightGolden.long("missingTargetTimeoutMs"), RewardFlightTuning.MISSING_TARGET_TIMEOUT_MS)
        assertEquals(Color(0xFFF4C542), StudyRewardGold)
        assertEquals("#F4C542", flightGolden.string("studyColor"))
        assertEquals(Color(0xFF087E8B), BrandTeal)
    }

    @Test
    fun `more than minimum verified flights coexist without replacement`() {
        val engine = RewardEffectsEngine()
        val count = flightGolden.int("minimumVerifiedConcurrentFlights") + 8

        repeat(count) { index ->
            engine.emit(
                RewardEffectRequest(
                    kind = if (index % 2 == 0) RewardEffectKind.STUDY else RewardEffectKind.REVIEW,
                    origin = RewardEffectOrigin(index.toFloat(), (index * 2).toFloat()),
                ),
            )
        }

        assertEquals(count, engine.snapshot().flights.size)
        assertEquals(count, engine.snapshot().flights.map { it.id }.distinct().size)
        engine.step(RewardFlightTuning.FRAME_MS, RewardTarget(PetPoint(2_000f, 2_000f), 56f))
        assertEquals(count, engine.snapshot().flights.size)
    }

    @Test
    fun `flight spirals then accelerates toward the target sampled each frame`() {
        val engine = RewardEffectsEngine()
        val origin = RewardEffectOrigin(100f, 100f)
        engine.emit(RewardEffectRequest(RewardEffectKind.STUDY, origin))
        assertEquals(PetPoint(100f, 100f), engine.snapshot().flights.single().position)

        engine.step(
            RewardFlightTuning.SPIRAL_DURATION_MS,
            RewardTarget(PetPoint(1_000f, 100f), 0f),
        )
        val afterSpiral = engine.snapshot().flights.single()
        assertEquals(RewardFlightStage.HOMING, afterSpiral.stage)
        assertTrue(afterSpiral.position.x > origin.x)

        engine.step(RewardFlightTuning.FRAME_MS, RewardTarget(PetPoint(1_000f, 100f), 0f))
        val firstHoming = engine.snapshot().flights.single()
        assertTrue(firstHoming.position.x > afterSpiral.position.x)

        engine.step(RewardFlightTuning.FRAME_MS, RewardTarget(PetPoint(100f, 1_000f), 0f))
        val redirected = engine.snapshot().flights.single()
        assertTrue(redirected.velocity.y > firstHoming.velocity.y)
    }

    @Test
    fun `spiral endpoint matches the shared flight vector`() {
        val vector = flightVectors.getValue("spiralEndpoint").jsonObject
        val origin = RewardEffectOrigin(100f, 200f)
        val engine = RewardEffectsEngine()
        engine.emit(RewardEffectRequest(RewardEffectKind.STUDY, origin))

        engine.step(
            vector.long("elapsedMs"),
            RewardTarget(PetPoint(2_000f, 2_000f), 0f),
        )

        val endpoint = engine.snapshot().flights.single().position
        assertEquals(vector.float("relativeX"), endpoint.x - origin.x, 1e-4f)
        assertEquals(vector.float("relativeY"), endpoint.y - origin.y, 1e-4f)
    }

    @Test
    fun `visible trail interpolates the exact shared polyline boundary`() {
        val vector = flightVectors.getValue("trailClip").jsonObject
        val input = vector.getValue("inputX").jsonArray.map { it.jsonPrimitive.float }
        val points = input.mapIndexed { index, x ->
            RewardTrailPoint(PetPoint(x, 0f), ageMs = (input.lastIndex - index) * 16L)
        }

        val clipped = visibleTrail(points, trailLengthForSpeed(vector.float("speed")))
        val length = clipped.zipWithNext().sumOf { (start, end) ->
            hypot(
                (end.position.x - start.position.x).toDouble(),
                (end.position.y - start.position.y).toDouble(),
            )
        }

        assertEquals(vector.float("expectedStartX"), clipped.first().position.x, 1e-5f)
        assertEquals(vector.float("expectedEndX"), clipped.last().position.x, 1e-5f)
        assertEquals(vector.float("expectedLength").toDouble(), length, 1e-5)
    }

    @Test
    fun `rating origin uses a fresh pointer down and otherwise falls back to button center`() {
        val bounds = Rect(left = 100f, top = 200f, right = 300f, bottom = 260f)
        val pointer = RewardEffectOrigin(125f, 225f)
        val capturedAt = 10_000L
        val sample = RatingPointerDown(pointer, capturedAt)

        assertEquals(pointer, resolveRatingOrigin(sample, bounds, capturedAt))
        assertEquals(
            pointer,
            resolveRatingOrigin(sample, bounds, capturedAt + RATING_POINTER_ORIGIN_FRESHNESS_MS),
        )
        val center = RewardEffectOrigin(200f, 230f)
        assertEquals(
            center,
            resolveRatingOrigin(sample, bounds, capturedAt + RATING_POINTER_ORIGIN_FRESHNESS_MS + 1L),
        )
        assertEquals(center, resolveRatingOrigin(null, bounds, capturedAt))
        assertEquals(center, resolveRatingOrigin(sample, bounds, capturedAt - 1L))
    }

    @Test
    fun `speed controls trail length and contact emits exactly eighteen particles`() {
        assertEquals(18f, trailLengthForSpeed(0f), 0f)
        assertEquals(40f, trailLengthForSpeed(1_000f), 0f)
        assertEquals(96f, trailLengthForSpeed(2_800f), 0f)

        val engine = RewardEffectsEngine()
        engine.emit(RewardEffectRequest(RewardEffectKind.REVIEW, RewardEffectOrigin(0f, 0f)))
        val target = RewardTarget(PetPoint(14f, 0f), 56f)
        engine.step(RewardFlightTuning.SPIRAL_DURATION_MS, target)
        engine.step(1L, target)

        val snapshot = engine.snapshot()
        assertTrue(snapshot.flights.isEmpty())
        assertEquals(RewardFlightTuning.BURST_PARTICLE_COUNT, snapshot.particles.size)
        assertTrue(snapshot.particles.all { it.kind == RewardEffectKind.REVIEW })
    }

    @Test
    fun `missing target timeout cancels only the affected flight`() {
        val engine = RewardEffectsEngine()
        engine.emit(RewardEffectRequest(RewardEffectKind.STUDY, RewardEffectOrigin(0f, 0f)))

        engine.step(RewardFlightTuning.MISSING_TARGET_TIMEOUT_MS - 1L, null)
        assertEquals(1, engine.snapshot().flights.size)

        engine.step(1L, null)
        assertTrue(engine.snapshot().flights.isEmpty())
    }

    private fun kotlinx.serialization.json.JsonObject.float(key: String): Float =
        getValue(key).jsonPrimitive.float

    private fun kotlinx.serialization.json.JsonObject.int(key: String): Int =
        getValue(key).jsonPrimitive.int

    private fun kotlinx.serialization.json.JsonObject.long(key: String): Long =
        getValue(key).jsonPrimitive.long

    private fun kotlinx.serialization.json.JsonObject.string(key: String): String =
        getValue(key).jsonPrimitive.content
}
