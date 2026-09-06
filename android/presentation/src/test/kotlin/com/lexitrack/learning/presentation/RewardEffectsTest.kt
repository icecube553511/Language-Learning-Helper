package com.lexitrack.learning.presentation

import androidx.compose.ui.geometry.Offset
import com.lexitrack.learning.domain.PetPoint
import com.lexitrack.learning.domain.PetRect
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RewardEffectsTest {
    @Test
    fun `study and review use the contract colors`() {
        assertEquals(StudyRewardGold, rewardColor(RewardEffectMode.STUDY))
        assertEquals(ReviewRewardCyan, rewardColor(RewardEffectMode.REVIEW))
    }

    @Test
    fun `flight accelerates and reaches target`() {
        val request = RewardEffectRequest(1L, Offset.Zero, Offset(400f, 0f), StudyRewardGold)
        val halfway = rewardOrbPosition(request, rewardProgress(request.durationMillis / 2f, request.durationMillis))
        val complete = rewardOrbPosition(request, rewardProgress(request.durationMillis.toFloat(), request.durationMillis))

        assertTrue(halfway.x < 200f)
        assertEquals(400f, complete.x, 0.001f)
        assertEquals(0f, complete.y, 0.001f)
        assertTrue(
            rewardSpeedPxPerSecond(400f, request.durationMillis / 2f, request.durationMillis) <
                rewardSpeedPxPerSecond(400f, request.durationMillis.toFloat(), request.durationMillis),
        )
    }

    @Test
    fun `duration and trail stay within energy ball bounds`() {
        assertEquals(360, rewardDurationMillis(0f))
        assertTrue(rewardDurationMillis(10_000f) <= 650)
        assertEquals(PET_ENERGY_BALL_MIN_TRAIL_PX, rewardTrailLength(0f), 0.001f)
        assertEquals(PET_ENERGY_BALL_MAX_TRAIL_PX, rewardTrailLength(100_000f), 0.001f)
        assertTrue(rewardTrailLength(1_200f) > rewardTrailLength(200f))
    }

    @Test
    fun `energy ball contract keeps collision and burst values stable`() {
        assertEquals("pet-energy-ball-v1", PET_ENERGY_BALL_CONTRACT)
        assertEquals(1_800f, PET_ENERGY_BALL_MAX_SPEED_PX_PER_SECOND, 0.001f)
        assertEquals(36f, PET_ENERGY_BALL_HIT_RADIUS_PX, 0.001f)
        assertEquals(18, PET_ENERGY_BALL_PARTICLE_COUNT)
        assertEquals(260f, PET_ENERGY_BALL_BURST_DURATION_MS, 0.001f)
        assertEquals(3, PET_ENERGY_BALL_MAX_CONCURRENT)
    }

    @Test
    fun `missing pet registration still gives a visible viewport destination`() {
        val destination = rewardTargetOrViewportCenter(
            target = null,
            viewportOrigin = PetPoint(10f, 20f),
            viewport = PetRect(0f, 0f, 300f, 500f),
        )

        assertEquals(Offset(160f, 270f), destination)
    }

    @Test
    fun `registered pet destination wins over fallback`() {
        val destination = rewardTargetOrViewportCenter(
            target = PetPoint(42f, 84f),
            viewportOrigin = PetPoint(10f, 20f),
            viewport = PetRect(0f, 0f, 300f, 500f),
        )

        assertEquals(Offset(42f, 84f), destination)
    }
}
