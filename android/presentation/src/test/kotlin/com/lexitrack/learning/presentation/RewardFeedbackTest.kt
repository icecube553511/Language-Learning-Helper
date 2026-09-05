package com.lexitrack.learning.presentation

import androidx.compose.ui.geometry.Rect
import com.lexitrack.learning.domain.PetPoint
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RewardFeedbackTest {
    @Test fun `events keep independent identities and orbit first`() {
        val engine = FeedbackEngine()
        val a = engine.emit(FeedbackRequest(FeedbackKind.STUDY, FeedbackOrigin(0f, 0f)))
        val b = engine.emit(FeedbackRequest(FeedbackKind.REVIEW, FeedbackOrigin(10f, 10f)))
        assertTrue(a != b)
        engine.step(100, FeedbackTarget(PetPoint(500f, 500f), 20f))
        assertEquals(2, engine.snapshot().orbs.size)
    }

    @Test fun `contact creates impact and particles`() {
        val engine = FeedbackEngine()
        engine.emit(FeedbackRequest(FeedbackKind.STUDY, FeedbackOrigin(0f, 0f)))
        engine.step(220, FeedbackTarget(PetPoint(0f, 0f), 8f))
        val snapshot = engine.snapshot()
        assertTrue(snapshot.impacts.isNotEmpty() || snapshot.particles.isNotEmpty())
        assertEquals(FeedbackKind.STUDY, snapshot.impacts.firstOrNull()?.kind ?: snapshot.particles.first().kind)
    }

    @Test fun `pointer origin falls back to button center when stale`() {
        val bounds = Rect(10f, 20f, 30f, 60f)
        val origin = resolveRatingOrigin(RatingPointerDown(FeedbackOrigin(1f, 2f), 0L), bounds, 1601L)
        assertEquals(FeedbackOrigin(20f, 40f), origin)
    }
}


