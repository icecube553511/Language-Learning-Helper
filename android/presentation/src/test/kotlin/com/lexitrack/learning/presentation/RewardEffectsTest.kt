package com.lexitrack.learning.presentation

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import com.lexitrack.learning.domain.PetPoint
import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RewardEffectsTest {
    private val golden by lazy {
        Json.parseToJsonElement(File(requireNotNull(System.getProperty("pet.energy.ball.golden.path"))).readText()).jsonObject
    }
    private val origin = RewardPoint(0.0, 0.0)
    private val distantTarget = RewardTarget(RewardPoint(1e9, 0.0), 56.0, "main")

    private fun point(value: JsonElement): RewardPoint = value.jsonArray.let {
        RewardPoint(it[0].jsonPrimitive.double, it[1].jsonPrimitive.double)
    }

    @Test
    fun `colors and visual parameters match the shared contract`() {
        assertEquals(StudyRewardGold, rewardColor(RewardEffectMode.STUDY))
        assertEquals(ReviewRewardCyan, rewardColor(RewardEffectMode.REVIEW))
        assertEquals(golden.getValue("contractVersion").jsonPrimitive.content, PET_ENERGY_BALL_CONTRACT)
        assertEquals(golden.getValue("behaviorRevision").jsonPrimitive.int, PET_ENERGY_BALL_BEHAVIOR_REVISION)
        val motion = golden.getValue("motion").jsonObject
        assertEquals(motion.getValue("initialSpeedLogicalPxPerSecond").jsonPrimitive.double, PET_ENERGY_BALL_INITIAL_SPEED_PX_PER_SECOND, 0.0)
        assertEquals(motion.getValue("accelerationLogicalPxPerSecondSquared").jsonPrimitive.double, PET_ENERGY_BALL_ACCELERATION_PX_PER_SECOND_SQUARED, 0.0)
        assertEquals(motion.getValue("orbRadiusLogicalPx").jsonPrimitive.double, PET_ENERGY_BALL_ORB_RADIUS_PX, 0.0)
        val visual = golden.getValue("visual").jsonObject
        assertEquals(visual.getValue("trailSamples").jsonPrimitive.int, PET_ENERGY_BALL_TRAIL_SAMPLES)
        assertEquals(visual.getValue("trailSampleStride").jsonPrimitive.int, PET_ENERGY_BALL_TRAIL_SAMPLE_STRIDE)
        assertEquals(visual.getValue("coreRadiusLogicalPx").jsonPrimitive.double, PET_ENERGY_BALL_CORE_RADIUS_PX, 0.0)
        assertEquals(visual.getValue("glowRadiusLogicalPx").jsonPrimitive.double, PET_ENERGY_BALL_GLOW_RADIUS_PX, 0.0)
        assertEquals(visual.getValue("glowPeakAlpha").jsonPrimitive.int, PET_ENERGY_BALL_GLOW_PEAK_ALPHA)
        assertEquals(golden.getValue("burst").jsonObject.getValue("particleCount").jsonPrimitive.int, PET_ENERGY_BALL_PARTICLE_COUNT)
        assertEquals(golden.getValue("burst").jsonObject.getValue("lifetimeMs").jsonPrimitive.double / 1000.0, PET_ENERGY_BALL_BURST_DURATION_SECONDS, 0.0)
    }

    @Test
    fun `shared motion vectors retain unlimited acceleration and lifetime`() {
        golden.getValue("motionVectors").jsonArray.forEach { value ->
            val vector = value.jsonObject
            val simulation = RewardPursuit()
            simulation.spawn(origin, RewardEffectMode.STUDY)
            repeat((vector.getValue("seconds").jsonPrimitive.double * 120).toInt()) {
                simulation.advance(PET_ENERGY_BALL_FIXED_STEP_SECONDS, distantTarget)
            }
            val orb = simulation.snapshot().orbs.single()
            assertEquals(vector.getValue("name").jsonPrimitive.content, vector.getValue("distance").jsonPrimitive.double, orb.position.x, 1e-7)
            assertEquals(vector.getValue("speed").jsonPrimitive.double, orb.speed, 1e-7)
            assertEquals(42, orb.trail.size)
        }
    }

    @Test
    fun `shared relative collision vectors prevent orb and target tunneling`() {
        golden.getValue("collisionVectors").jsonArray.forEach { value ->
            val vector = value.jsonObject
            val fraction = rewardCollisionFraction(
                point(vector.getValue("orbStart")), point(vector.getValue("orbEnd")),
                point(vector.getValue("targetStart")), point(vector.getValue("targetEnd")),
                vector.getValue("targetRadius").jsonPrimitive.double,
            )
            val expected = vector.getValue("fraction")
            if (expected == JsonNull) assertNull(fraction)
            else assertEquals(expected.jsonPrimitive.double, requireNotNull(fraction), 1e-10)
        }
    }

    @Test
    fun `fractional frames accumulate and long frames accept only one tenth second`() {
        val fragmented = RewardPursuit()
        val regular = RewardPursuit()
        fragmented.spawn(origin, RewardEffectMode.STUDY)
        regular.spawn(origin, RewardEffectMode.STUDY)
        repeat(1000) { fragmented.advance(0.001, distantTarget) }
        repeat(120) { regular.advance(1.0 / 120, distantTarget) }
        assertEquals(regular.snapshot(), fragmented.snapshot())
        val delayed = RewardPursuit()
        delayed.spawn(origin, RewardEffectMode.STUDY)
        delayed.advance(60.0, distantTarget)
        assertEquals(7.65, delayed.snapshot().orbs.single().position.x, 1e-9)
    }

    @Test
    fun `all independent orbs survive section changes and offscreen starts`() {
        val controller = RewardEffectsController()
        repeat(80) { controller.emit(RewardEffectMode.STUDY, Offset(-100000f, 0f), 2f) }
        controller.updateTarget(distantTarget)
        controller.frame(0L, "main", true)
        controller.frame(100_000_000L, "main", true)
        assertEquals(80, controller.snapshot.orbs.size)
        assertEquals(80, controller.snapshot.orbs.map { it.id }.distinct().size)
        val before = controller.snapshot
        controller.frame(200_000_000L, null, true)
        controller.frame(10_000_000_000L, "main", true)
        assertEquals(before, controller.snapshot)
        controller.clear()
        assertEquals(RewardSnapshot(), controller.snapshot)
    }

    @Test
    fun `missing target and background freeze motion trails and impacts without catchup`() {
        val simulation = RewardPursuit()
        val target = RewardTarget(RewardPoint(100.0, 0.0), 56.0, "main")
        simulation.spawn(target.center, RewardEffectMode.STUDY)
        simulation.spawn(origin, RewardEffectMode.REVIEW)
        simulation.frame(0, target)
        simulation.frame(100_000_000, target)
        val frozen = simulation.snapshot()
        assertEquals(1, frozen.impacts.size)
        assertEquals(1, frozen.orbs.size)
        simulation.frame(500_000_000, target, active = false)
        simulation.frame(10_000_000_000, null)
        simulation.frame(20_000_000_000, target.copy(center = RewardPoint(1000.0, 0.0)))
        assertEquals(frozen, simulation.snapshot())
        simulation.frame(20_100_000_000, target.copy(center = RewardPoint(1000.0, 0.0)))
        assertTrue(simulation.snapshot().orbs.single().speed > frozen.orbs.single().speed)
        assertEquals(frozen.impacts.single().position, simulation.snapshot().impacts.single().position)
    }

    @Test
    fun `host transfer preserves speed and trail but never sweeps a relocation`() {
        val simulation = RewardPursuit()
        simulation.spawn(origin, RewardEffectMode.REVIEW)
        val main = RewardTarget(RewardPoint(100.0, 0.0), 18.0, "main")
        simulation.frame(0, main)
        simulation.frame(100_000_000, main)
        val before = simulation.snapshot().orbs.single()
        simulation.frame(200_000_000, main.copy(center = RewardPoint(-100.0, 0.0), hostId = "dialog"))
        val after = simulation.snapshot().orbs.single()
        assertEquals(before.id, after.id)
        assertTrue(after.speed > before.speed)
        assertTrue(after.position.x < before.position.x)
        assertTrue(before.trail.all { it in after.trail })
        assertTrue(simulation.snapshot().impacts.isEmpty())
    }

    @Test
    fun `moving target contact creates a fixed impact at interpolated contact center`() {
        val simulation = RewardPursuit()
        simulation.spawn(origin, RewardEffectMode.REVIEW)
        val target = RewardTarget(RewardPoint(100.0, 0.0), 18.0, "main")
        simulation.frame(0, target)
        simulation.frame(100_000_000, target.copy(center = RewardPoint(-100.0, 0.0)))
        assertTrue(simulation.snapshot().orbs.isEmpty())
        val impact = simulation.snapshot().impacts.single()
        assertTrue(impact.position.x in 20.0..35.0)
        simulation.frame(200_000_000, target)
        assertEquals(impact.position, simulation.snapshot().impacts.single().position)
        simulation.frame(300_000_000, target)
        simulation.frame(400_000_000, target)
        simulation.frame(500_000_000, target)
        assertTrue(simulation.snapshot().impacts.isEmpty())
    }

    @Test
    fun `screen density and dialog origin preserve the same logical flight`() {
        val logical = rewardPointFromScreen(Offset(500f, 750f), 2.5f)
        assertEquals(RewardPoint(200.0, 300.0), logical)
        assertEquals(Offset(100f, 150f), rewardPointOnHost(logical, PetPoint(400f, 600f), 2.5f))
        assertEquals(Offset(200f, 300f), rewardPointOnHost(logical, PetPoint(0f, 0f), 1f))
        val first = RewardEffectsController()
        val dense = RewardEffectsController()
        first.emit(RewardEffectMode.REVIEW, Offset(20f, 30f), 1f)
        dense.emit(RewardEffectMode.REVIEW, Offset(60f, 90f), 3f)
        assertEquals(first.snapshot, dense.snapshot)
    }

    @Test
    fun `accepted command emits once at button center and rejected command emits nothing`() {
        var rated = false
        val emitted = mutableListOf<Pair<RewardEffectMode, Offset>>()
        activateRewardRating(Rect(10f, 20f, 110f, 80f), RewardEffectMode.STUDY, { rated = true; true }) { mode, point ->
            assertTrue(rated)
            emitted += mode to point
        }
        assertEquals(listOf(RewardEffectMode.STUDY to Offset(60f, 50f)), emitted)
        activateRewardRating(Rect(10f, 20f, 110f, 80f), RewardEffectMode.REVIEW, { false }) { mode, point -> emitted += mode to point }
        assertEquals(1, emitted.size)
        assertFalse(emitted.any { it.first == RewardEffectMode.REVIEW })
    }
}
