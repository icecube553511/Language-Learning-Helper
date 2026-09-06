package com.lexitrack.learning.presentation

import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.IntSize
import java.io.File
import com.lexitrack.learning.domain.BubbleDefinition
import com.lexitrack.learning.domain.PetPoint
import com.lexitrack.learning.domain.PetRect
import com.lexitrack.learning.domain.PetTarget
import com.lexitrack.learning.domain.PetTargetKind
import com.lexitrack.learning.domain.PetMode
import com.lexitrack.learning.domain.PetFacing
import com.lexitrack.learning.domain.PET_FLING_GRAVITY
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.float
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.sqrt

class PetPresentationTest {
    private val golden by lazy {
        Json.parseToJsonElement(
            File(requireNotNull(System.getProperty("pet.companion.golden.path"))).readText(),
        ).jsonObject
    }

    private fun point(value: kotlinx.serialization.json.JsonElement): PetPoint {
        val coordinates = value.jsonArray.map { it.jsonPrimitive.float }
        return PetPoint(coordinates[0], coordinates[1])
    }

    private fun rect(value: kotlinx.serialization.json.JsonElement): PetRect {
        val coordinates = value.jsonArray.map { it.jsonPrimitive.float }
        return PetRect(coordinates[0], coordinates[1], coordinates[2], coordinates[3])
    }

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

    @Test
    fun `pet portal maps a fling through the right edge`() {
        val entry = mapPetEntry(
            sourceRect = PetRect(0f, 0f, 400f, 300f),
            targetRect = PetRect(400f, 0f, 400f, 300f),
            positionInSource = PetPoint(390f, 150f),
            direction = "left",
            petHalfSize = 56f,
            mode = PetMode.FLING,
            velocity = PetPoint(420f, 0f),
            facing = PetFacing.RIGHT,
        )
        assertEquals(PetPoint(56f, 150f), entry.position)
        assertEquals(PetMode.FLING, entry.mode)
        assertEquals(PetPoint(420f, 0f), entry.velocity)
    }

    @Test
    fun `top portal starts a falling entry outside the target viewport`() {
        val entry = mapPetEntry(
            PetRect(0f, -320f, 400f, 300f),
            PetRect(0f, 0f, 400f, 300f),
            PetPoint(200f, -76f),
            "top",
            56f,
            mode = PetMode.FLING,
            velocity = PetPoint(0f, 125f),
        )
        assertEquals(PetPoint(200f, -56f), entry.position)
        assertEquals(PetMode.FALL, entry.mode)
    }

    @Test
    fun `bottom portal enters through the destination bottom edge`() {
        val entry = mapPetEntry(
            sourceRect = PetRect(0f, -300f, 400f, 300f),
            targetRect = PetRect(0f, 0f, 400f, 300f),
            positionInSource = PetPoint(200f, 296f),
            direction = "bottom",
            petHalfSize = 56f,
            mode = PetMode.FLING,
            velocity = PetPoint(0f, 320f),
        )
        assertEquals(PetPoint(200f, 356f), entry.position)
        assertEquals(PetMode.FLING, entry.mode)
    }

    @Test
    fun `adjacent window selection ignores unmapped windows and keeps registration order`() {
        val source = PetWindow("main", PetRect(0f, 0f, 400f, 300f), order = 0)
        val hidden = PetWindow("hidden", PetRect(400f, 0f, 400f, 300f), order = 0, mapped = false)
        val first = PetWindow("first", PetRect(400f, 0f, 400f, 300f), order = 1)
        val second = PetWindow("second", PetRect(400f, 0f, 400f, 300f), order = 2)
        assertEquals(
            "first",
            selectAdjacentWindow(source, listOf(hidden, second, first), "right", PetPoint(390f, 150f))?.id,
        )
    }

    @Test
    fun `window selection rejects overlap for autonomy but allows explicit drag`() {
        val source = PetWindow("main", PetRect(100f, 100f, 400f, 300f), order = 0)
        val overlapping = PetWindow("dialog", PetRect(200f, 100f, 400f, 300f), order = 1)
        val position = PetPoint(399f, 150f)

        assertNull(selectAdjacentWindow(source, listOf(overlapping), "right", position))
        assertEquals(
            "dialog",
            selectAdjacentWindow(
                source,
                listOf(overlapping),
                "right",
                position,
                allowOverlap = true,
            )?.id,
        )
    }

    @Test
    fun `window coordinator keeps one pet state while activating a neighbor`() {
        val coordinator = PetWindowCoordinator(
            com.lexitrack.learning.domain.PetState(
                PetPoint(390f, 150f),
                PetMode.FLING,
                targetId = "source-only-target",
                idleTicksRemaining = 17,
                avoidTargetId = "source-only-avoid",
                horizontalVelocity = 420f,
                curveVelocity = 1.5f,
            ),
        )
        coordinator.registerWindow(PetWindow("main", PetRect(0f, 0f, 400f, 300f)), active = true, petHalfSize = 56f)
        coordinator.registerWindow(PetWindow("study", PetRect(400f, 0f, 400f, 300f)), active = false)
        assertTrue(coordinator.activate("study", petHalfSize = 56f))
        assertEquals("study", coordinator.activeWindowId)
        assertEquals(PetPoint(56f, 150f), coordinator.state.position)
        assertEquals(420f, coordinator.state.horizontalVelocity)
        assertNull(coordinator.state.targetId)
        assertEquals(0, coordinator.state.idleTicksRemaining)
        assertNull(coordinator.state.avoidTargetId)
        assertNull(coordinator.state.curveVelocity)
    }

    @Test
    fun `same-window target refresh clears stale references without resetting motion`() {
        val initial = com.lexitrack.learning.domain.PetState(
            position = PetPoint(180f, 90f),
            mode = PetMode.ROLL,
            targetId = "study-card",
            idleTicksRemaining = 7,
            pathIndex = 3,
            pathDirection = -1,
            rollCorners = 1,
            avoidTargetId = "old-target",
            movementSpeed = 6.5f,
            verticalVelocity = 12f,
            facing = PetFacing.LEFT,
            horizontalVelocity = 44f,
            curveVelocity = 2.25f,
            bouncesRemaining = 2,
        )
        val coordinator = PetWindowCoordinator(initial)
        coordinator.registerWindow(
            PetWindow("main", PetRect(0f, 0f, 400f, 300f)),
            active = true,
        )

        coordinator.updateTargets(
            "main",
            listOf(PetTarget("replacement", PetTargetKind.CONTROL, PetRect(40f, 40f, 120f, 48f))),
        )

        val updated = coordinator.state
        assertEquals(initial.position, updated.position)
        assertEquals(initial.mode, updated.mode)
        assertEquals(initial.movementSpeed, updated.movementSpeed, 0f)
        assertEquals(initial.verticalVelocity, updated.verticalVelocity, 0f)
        assertEquals(initial.horizontalVelocity, updated.horizontalVelocity, 0f)
        assertEquals(initial.bouncesRemaining, updated.bouncesRemaining)
        assertEquals(initial.facing, updated.facing)
        assertNull(updated.targetId)
        assertEquals(initial.idleTicksRemaining, updated.idleTicksRemaining)
        assertEquals(0, updated.pathIndex)
        assertEquals(1, updated.pathDirection)
        assertEquals(0, updated.rollCorners)
        assertNull(updated.avoidTargetId)
        assertNull(updated.curveVelocity)
    }

    @Test
    fun `window coordinator predicts a fast fling before local wall reflection`() {
        val coordinator = PetWindowCoordinator(
            com.lexitrack.learning.domain.PetState(
                PetPoint(320f, 150f),
                PetMode.FLING,
                horizontalVelocity = 1_800f,
            ),
        )
        coordinator.registerWindow(
            PetWindow("main", PetRect(0f, 0f, 400f, 300f)),
            active = true,
            petHalfSize = 56f,
        )
        coordinator.registerWindow(
            PetWindow("study", PetRect(400f, 0f, 400f, 300f)),
            active = false,
        )

        assertTrue(
            coordinator.migrateIfNeeded(
                "main",
                petHalfSize = 56f,
                lookaheadSeconds = 0.016f,
            ),
        )
        assertEquals("study", coordinator.activeWindowId)
        val crossingTime = (344f - 320f) / 1_800f
        assertEquals(56f, coordinator.state.position.x, 1e-4f)
        assertEquals(
            150f + 0.5f * PET_FLING_GRAVITY * crossingTime * crossingTime,
            coordinator.state.position.y,
            1e-3f,
        )
        assertEquals(1_800f, coordinator.state.horizontalVelocity)
        assertEquals(PET_FLING_GRAVITY * crossingTime, coordinator.state.verticalVelocity, 1e-3f)
        assertEquals(PetMode.FLING, coordinator.state.mode)
    }

    @Test
    fun `window coordinator predicts a downward fling before viewport landing`() {
        val coordinator = PetWindowCoordinator(
            com.lexitrack.learning.domain.PetState(
                PetPoint(200f, 320f),
                PetMode.FLING,
                verticalVelocity = 1_800f,
            ),
        )
        coordinator.registerWindow(
            PetWindow("main", PetRect(0f, 0f, 400f, 400f)),
            active = true,
            petHalfSize = 56f,
        )
        coordinator.registerWindow(
            PetWindow("reminder", PetRect(0f, 400f, 400f, 400f)),
            active = false,
        )

        assertTrue(
            coordinator.migrateIfNeeded(
                "main",
                petHalfSize = 56f,
                lookaheadSeconds = 0.016f,
            ),
        )
        assertEquals("reminder", coordinator.activeWindowId)
        assertEquals(PetPoint(200f, -56f), coordinator.state.position)
        assertEquals(PetMode.FALL, coordinator.state.mode)
        val gravity = PET_FLING_GRAVITY
        val crossingTime = (-1_800f + sqrt(1_800f * 1_800f + 2f * gravity * 24f)) / gravity
        assertEquals(1_800f + gravity * crossingTime, coordinator.state.verticalVelocity, 1e-3f)
    }

    @Test
    fun `predicted portal crossings are ordered by continuous contact time`() {
        val crossings = predictedExitTimes(
            state = com.lexitrack.learning.domain.PetState(
                PetPoint(330f, 230f),
                PetMode.FLING,
                horizontalVelocity = 1_800f,
                verticalVelocity = 3_000f,
            ),
            viewport = PetRect(0f, 0f, 400f, 300f),
            petHalfSize = 56f,
            durationSeconds = 0.016f,
        )

        assertEquals(listOf("bottom", "right"), crossings.map { it.second })
        assertTrue(crossings[0].first < crossings[1].first)
    }

    @Test
    fun `window coordinator chooses the earliest diagonal portal`() {
        val coordinator = PetWindowCoordinator(
            com.lexitrack.learning.domain.PetState(
                PetPoint(330f, 230f),
                PetMode.FLING,
                horizontalVelocity = 1_800f,
                verticalVelocity = 3_000f,
            ),
        )
        coordinator.registerWindow(
            PetWindow("main", PetRect(0f, 0f, 400f, 300f)),
            active = true,
            petHalfSize = 56f,
        )
        coordinator.registerWindow(PetWindow("right", PetRect(400f, 0f, 400f, 300f)))
        coordinator.registerWindow(PetWindow("below", PetRect(0f, 300f, 400f, 300f)))

        assertTrue(coordinator.migrateIfNeeded("main", petHalfSize = 56f, lookaheadSeconds = 0.016f))
        assertEquals("below", coordinator.activeWindowId)
        val gravity = PET_FLING_GRAVITY
        val crossingTime = (-3_000f + sqrt(3_000f * 3_000f + 2f * gravity * 14f)) / gravity
        assertEquals(330f + 1_800f * crossingTime, coordinator.state.position.x, 1e-3f)
        assertEquals(-56f, coordinator.state.position.y, 1e-4f)
        assertEquals(PetMode.FALL, coordinator.state.mode)
    }

    @Test
    fun `closing active window preserves world position in a nonadjacent fallback`() {
        val coordinator = PetWindowCoordinator(
            com.lexitrack.learning.domain.PetState(
                PetPoint(120f, 80f),
                PetMode.FLING,
                targetId = "dialog-local",
                idleTicksRemaining = 4,
                avoidTargetId = "old-target",
                horizontalVelocity = 180f,
            ),
        )
        coordinator.registerWindow(
            PetWindow("main", PetRect(0f, 0f, 400f, 300f)),
            active = true,
            petHalfSize = 56f,
        )
        coordinator.registerWindow(
            PetWindow("dialog", PetRect(900f, 700f, 400f, 300f)),
            active = true,
            petHalfSize = 56f,
        )
        coordinator.updateState(coordinator.state.copy(curveVelocity = -1.25f))

        coordinator.unregisterWindow("dialog", petHalfSize = 56f)

        assertEquals("main", coordinator.activeWindowId)
        // The world centre (1020, 780) is clamped into the 400x300 main host.
        assertEquals(PetPoint(344f, 244f), coordinator.state.position)
        assertNull(coordinator.state.targetId)
        assertEquals(0, coordinator.state.idleTicksRemaining)
        assertNull(coordinator.state.avoidTargetId)
        assertNull(coordinator.state.curveVelocity)
    }

    @Test
    fun `activating a nonadjacent window clears source curve velocity`() {
        val coordinator = PetWindowCoordinator(
            com.lexitrack.learning.domain.PetState(
                position = PetPoint(120f, 80f),
                mode = PetMode.SLIDE,
                targetId = "main:chart",
                curveVelocity = 2.5f,
            ),
        )
        coordinator.registerWindow(
            PetWindow("main", PetRect(0f, 0f, 400f, 300f)),
            active = true,
            petHalfSize = 56f,
        )
        coordinator.registerWindow(PetWindow("dialog", PetRect(900f, 700f, 400f, 300f)))

        assertTrue(coordinator.activate("dialog", petHalfSize = 56f))

        assertEquals("dialog", coordinator.activeWindowId)
        assertEquals(PetPoint(56f, 56f), coordinator.state.position)
        assertNull(coordinator.state.targetId)
        assertNull(coordinator.state.curveVelocity)
    }

    @Test
    fun `window coordinator migrates a fling through the top edge`() {
        val coordinator = PetWindowCoordinator(
            com.lexitrack.learning.domain.PetState(
                PetPoint(200f, 56f),
                PetMode.FLING,
                verticalVelocity = -320f,
            ),
        )
        coordinator.registerWindow(
            PetWindow("main", PetRect(0f, 300f, 400f, 300f)),
            active = true,
            petHalfSize = 56f,
        )
        coordinator.registerWindow(
            PetWindow("above", PetRect(0f, 0f, 400f, 300f)),
            active = false,
        )

        assertTrue(coordinator.migrateIfNeeded("main", petHalfSize = 56f))
        assertEquals("above", coordinator.activeWindowId)
        // Moving upward exits the source top and enters the destination's
        // bottom edge; the destination reducer continues the projectile.
        assertEquals(PetPoint(200f, 356f), coordinator.state.position)
        assertEquals(PetMode.FLING, coordinator.state.mode)
        assertEquals(-320f, coordinator.state.verticalVelocity)
    }

    @Test
    fun `dragging can cross the top portal without losing its grab offset`() {
        val grabOffset = PetPoint(12f, -8f)
        val coordinator = PetWindowCoordinator(
            com.lexitrack.learning.domain.PetState(
                PetPoint(200f, 56f),
                PetMode.DRAGGING,
                dragOffset = grabOffset,
            ),
        )
        coordinator.registerWindow(
            PetWindow("main", PetRect(0f, 300f, 400f, 300f)),
            active = true,
            petHalfSize = 56f,
        )
        coordinator.registerWindow(
            PetWindow("above", PetRect(0f, 0f, 400f, 300f)),
            active = false,
        )

        assertTrue(coordinator.migrateIfNeeded("main", petHalfSize = 56f))
        assertEquals("above", coordinator.activeWindowId)
        assertEquals(PetMode.DRAGGING, coordinator.state.mode)
        assertEquals(grabOffset, coordinator.state.dragOffset)
        assertEquals(PetPoint(200f, 356f), coordinator.state.position)
    }

    @Test
    fun `window transfer clears source bookkeeping but preserves drag offset`() {
        val grabOffset = PetPoint(-12f, 7f)
        val coordinator = PetWindowCoordinator(
            com.lexitrack.learning.domain.PetState(
                PetPoint(344f, 150f),
                PetMode.DRAGGING,
                targetId = "source-target",
                idleTicksRemaining = 8,
                avoidTargetId = "source-avoid",
                dragOffset = grabOffset,
            ),
        )
        coordinator.registerWindow(
            PetWindow("main", PetRect(0f, 0f, 400f, 300f)),
            active = true,
            petHalfSize = 56f,
        )
        coordinator.registerWindow(PetWindow("dialog", PetRect(400f, 0f, 400f, 300f)))

        assertTrue(coordinator.migrateIfNeeded("main", petHalfSize = 56f))
        assertEquals(PetMode.DRAGGING, coordinator.state.mode)
        assertNull(coordinator.state.targetId)
        assertEquals(0, coordinator.state.idleTicksRemaining)
        assertNull(coordinator.state.avoidTargetId)
        assertEquals(grabOffset, coordinator.state.dragOffset)
    }

    @Test
    fun `overlay ownership renders only active host while source keeps drag capture`() {
        val source = petOverlayOwnership("dialog", "main", dragCaptureActive = true)
        val target = petOverlayOwnership("dialog", "dialog", dragCaptureActive = false)

        assertFalse(source.renders)
        assertTrue(source.capturesGesture)
        assertTrue(target.renders)
        assertFalse(target.capturesGesture)
        assertEquals(1, listOf(source, target).count(PetOverlayOwnership::renders))
    }

    @Test
    fun `window ray rejects near miss and selects first hit within lookahead`() {
        val vector = golden.getValue("windowRayVectors").jsonArray.single().jsonObject
        val sourceValue = vector.getValue("sourceWindow").jsonObject
        val sourceRect = rect(sourceValue.getValue("rect"))
        val source = PetWindow(sourceValue.getValue("id").jsonPrimitive.content, sourceRect)
        val worldOrigin = point(vector.getValue("rayOriginWorld"))
        val positionInSource = PetPoint(worldOrigin.x - sourceRect.left, worldOrigin.y - sourceRect.top)
        val motion = point(vector.getValue("velocity"))
        val lookahead = vector.getValue("lookaheadSeconds").jsonPrimitive.float
        val candidates = vector.getValue("candidates").jsonArray.map { raw ->
            val item = raw.jsonObject
            PetWindow(
                id = item.getValue("id").jsonPrimitive.content,
                rect = rect(item.getValue("rect")),
                order = item.getValue("order").jsonPrimitive.int,
            )
        }
        val rejectedId = vector.getValue("expectedRejected").jsonArray.single().jsonPrimitive.content
        val rejected = candidates.single { it.id == rejectedId }

        assertNull(
            selectAdjacentWindow(
                source,
                listOf(rejected),
                "right",
                positionInSource,
                motion = motion,
                maxTime = lookahead,
            ),
        )
        val selected = selectAdjacentWindow(
            source,
            candidates,
            "right",
            positionInSource,
            motion = motion,
            maxTime = lookahead,
        )
        assertEquals(vector.getValue("expectedHost").jsonPrimitive.content, selected?.id)

        val expectedTime = vector.getValue("expectedIntersectionTimeSeconds").jsonPrimitive.float
        val actualTime = rayRectEntryTime(worldOrigin, motion, requireNotNull(selected).rect, lookahead)
        assertEquals(expectedTime, requireNotNull(actualTime), 1e-6f)
        val expectedPoint = point(vector.getValue("expectedIntersectionPoint"))
        assertEquals(expectedPoint.x, worldOrigin.x + motion.x * actualTime, 1e-4f)
        assertEquals(expectedPoint.y, worldOrigin.y + motion.y * actualTime, 1e-4f)
    }

    @Test
    fun `window coordinator maps a gapped diagonal ray at the target intersection`() {
        val vector = golden.getValue("windowRayVectors").jsonArray.single().jsonObject
        val sourceValue = vector.getValue("sourceWindow").jsonObject
        val sourceRect = rect(sourceValue.getValue("rect"))
        val worldOrigin = point(vector.getValue("rayOriginWorld"))
        val motion = point(vector.getValue("velocity"))
        val coordinator = PetWindowCoordinator(
            com.lexitrack.learning.domain.PetState(
                position = PetPoint(worldOrigin.x - sourceRect.left, worldOrigin.y - sourceRect.top),
                mode = PetMode.FLING,
                horizontalVelocity = motion.x,
                verticalVelocity = motion.y,
            ),
        )
        coordinator.registerWindow(
            PetWindow(sourceValue.getValue("id").jsonPrimitive.content, sourceRect),
            active = true,
        )
        vector.getValue("candidates").jsonArray.forEach { raw ->
            val item = raw.jsonObject
            coordinator.registerWindow(
                PetWindow(
                    id = item.getValue("id").jsonPrimitive.content,
                    rect = rect(item.getValue("rect")),
                    order = item.getValue("order").jsonPrimitive.int,
                ),
            )
        }

        assertTrue(
            coordinator.migrateIfNeeded(
                sourceValue.getValue("id").jsonPrimitive.content,
                petHalfSize = 0f,
                lookaheadSeconds = vector.getValue("lookaheadSeconds").jsonPrimitive.float,
            ),
        )
        assertEquals(vector.getValue("expectedHost").jsonPrimitive.content, coordinator.activeWindowId)
        assertEquals(point(vector.getValue("expectedIntersectionPoint")), coordinator.worldPosition())
        assertEquals(motion.x, coordinator.state.horizontalVelocity, 1e-6f)
        assertEquals(motion.y, coordinator.state.verticalVelocity, 1e-6f)
    }

    @Test
    fun `captured drag continues in coordinator active host after portal`() {
        val grabOffset = PetPoint(5f, -3f)
        val coordinator = PetWindowCoordinator(
            com.lexitrack.learning.domain.PetState(
                position = PetPoint(330f, 150f),
                mode = PetMode.DRAGGING,
                dragOffset = grabOffset,
            ),
        )
        coordinator.registerWindow(
            PetWindow("main", PetRect(0f, 0f, 400f, 300f)),
            active = true,
            petHalfSize = 56f,
        )
        coordinator.registerWindow(PetWindow("dialog", PetRect(400f, 0f, 600f, 300f)))

        assertTrue(coordinator.dragActiveBy(PetPoint(20f, 0f), petHalfSize = 56f))
        assertEquals("dialog", coordinator.activeWindowId)
        assertEquals(PetPoint(56f, 150f), coordinator.state.position)
        assertEquals(grabOffset, coordinator.state.dragOffset)

        assertTrue(coordinator.dragActiveBy(PetPoint(20f, 0f), petHalfSize = 56f))
        assertEquals(PetPoint(76f, 150f), coordinator.state.position)
        assertEquals(PetMode.DRAGGING, coordinator.state.mode)
    }

    @Test
    fun `single drag event preserves overshoot after crossing a portal`() {
        val grabOffset = PetPoint(9f, -4f)
        val coordinator = PetWindowCoordinator(
            com.lexitrack.learning.domain.PetState(
                position = PetPoint(330f, 150f),
                mode = PetMode.DRAGGING,
                dragOffset = grabOffset,
            ),
        )
        coordinator.registerWindow(
            PetWindow("main", PetRect(0f, 0f, 400f, 300f)),
            active = true,
            petHalfSize = 56f,
        )
        coordinator.registerWindow(PetWindow("dialog", PetRect(400f, 0f, 600f, 300f)))

        assertTrue(coordinator.dragActiveBy(PetPoint(200f, 0f), petHalfSize = 56f))

        assertEquals("dialog", coordinator.activeWindowId)
        assertEquals(PetPoint(130f, 150f), coordinator.state.position)
        assertEquals(PetPoint(530f, 150f), coordinator.worldPosition())
        assertEquals(grabOffset, coordinator.state.dragOffset)
        assertEquals(PetMode.DRAGGING, coordinator.state.mode)
    }
}
