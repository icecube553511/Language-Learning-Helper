package com.lexitrack.learning.presentation

import com.lexitrack.learning.domain.PetRect
import com.lexitrack.learning.domain.PetTarget
import com.lexitrack.learning.domain.PetTargetKind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PetPresentationTest {
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
}
