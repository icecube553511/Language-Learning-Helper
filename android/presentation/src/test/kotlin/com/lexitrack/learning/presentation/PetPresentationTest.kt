package com.lexitrack.learning.presentation

import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.IntSize
import com.lexitrack.learning.domain.BubbleDefinition
import com.lexitrack.learning.domain.PetPoint
import com.lexitrack.learning.domain.PetRect
import com.lexitrack.learning.domain.PetTarget
import com.lexitrack.learning.domain.PetTargetKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PetPresentationTest {
    private fun bubble(word: String) = BubbleDefinition(
        wordId = word,
        word = word,
        partOfSpeech = "n.",
        meaning = "释义",
        examples = listOf("A $word example."),
    )

    @Test
    fun `pet presentation uses the shared logical size and tick rate`() {
        assertEquals(112, PET_DISPLAY_SIZE_DP)
        assertEquals(16L, PET_TICK_MS)
    }

    @Test
    fun `registry prefixes live targets and removes disposed targets`() {
        val registry = linkedMapOf<String, PetTarget>()
        val target = PetTarget("search", PetTargetKind.CONTROL, PetRect(10f, 20f, 100f, 40f))

        updatePetTargetRegistry(registry, "library", target)

        assertEquals(setOf("library:search"), registry.keys)
        assertEquals("library:search", registry.getValue("library:search").id)

        updatePetTargetRegistry(
            registry,
            "library",
            target.copy(rect = PetRect(0f, 0f, 0f, 0f), visible = false),
        )

        assertTrue(registry.isEmpty())
    }

    @Test
    fun `disposing one dialog target does not remove another registry prefix`() {
        val registry = linkedMapOf<String, PetTarget>()
        val target = PetTarget("confirm", PetTargetKind.CONTROL, PetRect(0f, 0f, 80f, 48f))
        updatePetTargetRegistry(registry, "dialog-a", target)
        updatePetTargetRegistry(registry, "dialog-b", target)

        updatePetTargetRegistry(registry, "dialog-a", target.copy(visible = false))

        assertFalse("dialog-a:confirm" in registry)
        assertTrue("dialog-b:confirm" in registry)
    }

    @Test
    fun `window stack exposes only the newest window and restores the previous one`() {
        val stack = mutableListOf<String>()

        updatePetWindowStack(stack, "dialog", active = true)
        updatePetWindowStack(stack, "popup", active = true)

        assertEquals(listOf("dialog", "popup"), stack)
        assertEquals("popup", stack.lastOrNull())

        updatePetWindowStack(stack, "popup", active = false)

        assertEquals(listOf("dialog"), stack)
        assertEquals("dialog", stack.lastOrNull())

        updatePetWindowStack(stack, "dialog", active = false)

        assertTrue(stack.isEmpty())
        assertEquals(null, stack.lastOrNull())
    }

    @Test
    fun `reactivating a window promotes it without duplicating it`() {
        val stack = mutableListOf("dialog", "popup")

        updatePetWindowStack(stack, "dialog", active = true)

        assertEquals(listOf("popup", "dialog"), stack)

        updatePetWindowStack(stack, "popup", active = false)

        assertEquals(listOf("dialog"), stack)
        assertEquals("dialog", stack.lastOrNull())
    }

    @Test
    fun `word bubble retains the host pet and dialog targets stay localized`() {
        val stack = mutableListOf<Any>()

        assertEquals("trigger-window-retained", WORD_BUBBLE_PET_SCOPE)
        assertTrue(isMainPetWindowVisible(stack))

        val viewport = PetRect(0f, 0f, 300f, 160f)
        val localized = localizePetTargets(
            listOf(
                PetTarget("frame", PetTargetKind.SURFACE, PetRect(100f, 200f, 300f, 160f)),
                PetTarget("clipped-close", PetTargetKind.CONTROL, PetRect(360f, 210f, 60f, 40f)),
                PetTarget("outside", PetTargetKind.CONTROL, PetRect(50f, 50f, 20f, 20f)),
            ),
            origin = PetPoint(100f, 200f),
            viewport = viewport,
        )

        assertEquals(setOf("frame", "clipped-close"), localized.map(PetTarget::id).toSet())
        assertEquals(PetRect(0f, 0f, 300f, 160f), localized.first { it.id == "frame" }.rect)
        assertEquals(PetRect(260f, 10f, 40f, 40f), localized.first { it.id == "clipped-close" }.rect)
        assertTrue(localized.all { target ->
            target.rect.left >= viewport.left && target.rect.top >= viewport.top &&
                target.rect.right <= viewport.right && target.rect.bottom <= viewport.bottom
        })
    }

    @Test
    fun `word bubble positioning stays inside its host window`() {
        val viewport = PetRect(0f, 0f, 300f, 220f)
        val hostOrigin = PetPoint(100f, 200f)
        val size = IntSize(180, 100)

        val below = wordBubbleOffset(
            anchor = IntRect(220, 230, 260, 250),
            hostOrigin = hostOrigin,
            viewport = viewport,
            bubbleSize = size,
            gapPx = 6,
        )
        val aboveAndClamped = wordBubbleOffset(
            anchor = IntRect(380, 390, 430, 410),
            hostOrigin = hostOrigin,
            viewport = viewport,
            bubbleSize = size,
            gapPx = 6,
        )

        assertEquals(50, below.x)
        assertEquals(56, below.y)
        assertEquals(120, aboveAndClamped.x)
        assertEquals(84, aboveAndClamped.y)
    }

    @Test
    fun `word bubbles reserve a full pet corridor in a small reminder viewport`() {
        val viewport = PetRect(0f, 0f, 280f, 220f)

        val reachability = wordBubbleReachability(viewport, petDiameterPx = 112f)

        assertEquals(PetRect(0f, 0f, 168f, 220f), reachability.placementViewport)
        assertEquals(PetRect(168f, 0f, 112f, 220f), reachability.petCorridor)
    }

    @Test
    fun `every bubble depth stays left of the shared pet corridor`() {
        val viewport = PetRect(0f, 0f, 300f, 220f)
        val reachability = wordBubbleReachability(viewport, petDiameterPx = 112f)
        val bubbleSize = IntSize(180, 140)
        val anchors = listOf(
            IntRect(8, 20, 48, 40),
            IntRect(140, 80, 180, 100),
            IntRect(260, 170, 296, 190),
        )

        val offsets = anchors.map { anchor ->
            wordBubbleOffset(
                anchor = anchor,
                hostOrigin = PetPoint(0f, 0f),
                viewport = reachability.placementViewport,
                bubbleSize = bubbleSize,
                gapPx = 6,
            )
        }

        assertTrue(offsets.all { it.x + bubbleSize.width <= reachability.petCorridor.left })
        assertTrue(offsets.all { it.y >= viewport.top && it.y + bubbleSize.height <= viewport.bottom })
    }

    @Test
    fun `learning reminder replaces main pet and closing it restores main pet`() {
        val reminder = Any()
        val stack = mutableListOf<Any>()

        updatePetWindowStack(stack, reminder, active = true)
        assertFalse(isMainPetWindowVisible(stack))
        assertTrue(isPetWindowVisible(stack, reminder))
        assertEquals(1, listOf(isMainPetWindowVisible(stack), isPetWindowVisible(stack, reminder)).count { it })

        updatePetWindowStack(stack, reminder, active = false)
        assertTrue(isMainPetWindowVisible(stack))
        assertFalse(isPetWindowVisible(stack, reminder))
        assertEquals(1, listOf(isMainPetWindowVisible(stack), isPetWindowVisible(stack, reminder)).count { it })
    }

    @Test
    fun `reminder word bubbles use an independent host without replacing the reminder pet`() {
        val anchor = IntRect(20, 30, 60, 50)
        val rootHost = openWordBubbleHost(WordBubbleHostState(), bubble("root"), -1, anchor)
        var reminderHost = openWordBubbleHost(WordBubbleHostState(), bubble("reminder"), -1, anchor)
        reminderHost = openWordBubbleHost(reminderHost, bubble("child"), 0, anchor)

        assertEquals(listOf("root"), rootHost.bubbles.map { it.data.word })
        assertEquals(listOf("reminder", "child"), reminderHost.bubbles.map { it.data.word })

        val reminder = Any()
        val stack = mutableListOf<Any>()
        updatePetWindowStack(stack, reminder, active = true)
        assertTrue(isPetWindowVisible(stack, reminder))
        assertFalse(isMainPetWindowVisible(stack))
        assertEquals(listOf(reminder), stack)
        assertEquals(listOf("reminder"), closeWordBubbleHostAt(reminderHost, 1).bubbles.map { it.data.word })
    }
}
