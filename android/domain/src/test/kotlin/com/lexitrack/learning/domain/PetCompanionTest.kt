package com.lexitrack.learning.domain

import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.float
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class PetCompanionTest {
    private val viewport = PetRect(0f, 0f, 800f, 700f)

    @Test
    fun `nearest target ignores zero sized regions and keeps registration order on ties`() {
        val targets = listOf(
            PetTarget("zero", PetTargetKind.CONTROL, PetRect(20f, 20f, 0f, 10f)),
            PetTarget("first", PetTargetKind.SURFACE, PetRect(300f, 300f, 40f, 40f)),
            PetTarget("second", PetTargetKind.CONTROL, PetRect(300f, 300f, 40f, 40f)),
        )

        assertEquals("first", nearestPetTarget(PetPoint(100f, 100f), targets)?.id)
    }

    @Test
    fun `navigation enters fall mode and clears previous target`() {
        val state = PetState(PetPoint(100f, 120f), PetMode.SLIDE, "chart")

        assertEquals(PetState(PetPoint(100f, 120f), PetMode.FALL, null), onNavigation(state))
    }

    @Test
    fun `drag clamps center to viewport and release keeps position`() {
        val state = beginDrag(PetState(PetPoint(50f, 50f)), PetPoint(40f, 50f))
        val moved = moveDrag(state, PetPoint(810f, -20f), viewport, halfSize = 40f)
        val released = releaseDrag(moved)

        assertEquals(PetMode.DRAGGING, moved.mode)
        assertEquals(PetPoint(760f, 40f), moved.position)
        assertEquals(PetPoint(760f, 40f), released.position)
        assertEquals(PetMode.IDLE, released.mode)
    }

    @Test
    fun `point inside a target has zero distance`() {
        val rect = PetRect(10f, 20f, 50f, 40f)
        assertTrue(rect.contains(PetPoint(30f, 40f)))
        assertEquals(0f, rect.distanceSquared(PetPoint(30f, 40f)))
    }

    @Test
    fun `advance slides along a registered chart path`() {
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(100f, 100f, 300f, 200f),
            path = listOf(PetPoint(120f, 120f), PetPoint(180f, 150f), PetPoint(240f, 190f)),
        )

        val entered = advancePet(
            PetState(PetPoint(120f, 120f)),
            listOf(chart),
            viewport,
            halfSize = 20f,
            step = 10f,
        )
        val advanced = advancePet(entered, listOf(chart), viewport, halfSize = 20f, step = 10f)

        assertEquals(PetMode.SLIDE, advanced.mode)
        assertEquals("curve", advanced.targetId)
        assertTrue(advanced.position.x > 120f)
        assertTrue(advanced.position.y > 120f)
    }

    @Test
    fun `advance preserves fall until target landing`() {
        val target = PetTarget("card", PetTargetKind.SURFACE, PetRect(300f, 400f, 120f, 80f))
        val advanced = advancePet(
            PetState(PetPoint(340f, 100f), PetMode.FALL),
            listOf(target),
            viewport,
            halfSize = 20f,
            step = 12f,
        )

        assertEquals(PetMode.FALL, advanced.mode)
        assertTrue(advanced.position.y > 100f)
    }

    @Test
    fun `shared golden vectors select target and preserve drag release`() {
        val golden = Json.parseToJsonElement(
            File(requireNotNull(System.getProperty("pet.companion.golden.path"))).readText(),
        ).jsonObject
        val vectors = golden.getValue("vectors").jsonArray.associateBy {
            it.jsonObject.getValue("name").jsonPrimitive.content
        }
        val nearest = vectors.getValue("nearest-control").jsonObject
        val position = nearest.getValue("position").jsonArray.map { it.jsonPrimitive.float }
        val targets = nearest.getValue("targets").jsonArray.map { item ->
            val target = item.jsonObject
            val rect = target.getValue("rect").jsonArray.map { it.jsonPrimitive.float }
            PetTarget(
                target.getValue("id").jsonPrimitive.content,
                PetTargetKind.CONTROL,
                PetRect(rect[0], rect[1], rect[2], rect[3]),
            )
        }
        assertEquals(
            nearest.getValue("expectedTarget").jsonPrimitive.content,
            nearestPetTarget(PetPoint(position[0], position[1]), targets)?.id,
        )

        val drag = vectors.getValue("drag-release").jsonObject
        val release = drag.getValue("release").jsonArray.map { it.jsonPrimitive.float }
        val viewportSize = drag.getValue("viewport").jsonArray.map { it.jsonPrimitive.float }
        val moved = moveDrag(
            PetState(PetPoint(0f, 0f), PetMode.DRAGGING),
            PetPoint(release[0], release[1]),
            PetRect(0f, 0f, viewportSize[0], viewportSize[1]),
            halfSize = 0f,
        )
        val expected = drag.getValue("expectedPosition").jsonArray.map { it.jsonPrimitive.float }
        assertEquals(PetPoint(expected[0], expected[1]), releaseDrag(moved).position)
        assertTrue(golden.getValue("drag").jsonObject.getValue("preserveGrabOffset").jsonPrimitive.boolean)
    }

    @Test
    fun `shared behavior vectors cover borders paths and vertical navigation`() {
        val golden = Json.parseToJsonElement(
            File(requireNotNull(System.getProperty("pet.companion.golden.path"))).readText(),
        ).jsonObject
        val vectors = golden.getValue("behaviorVectors").jsonArray.associateBy {
            it.jsonObject.getValue("name").jsonPrimitive.content
        }
        fun point(value: kotlinx.serialization.json.JsonElement): PetPoint {
            val items = value.jsonArray.map { it.jsonPrimitive.float }
            return PetPoint(items[0], items[1])
        }
        fun target(value: kotlinx.serialization.json.JsonElement): PetTarget {
            val item = value.jsonObject
            val rect = item.getValue("rect").jsonArray.map { it.jsonPrimitive.float }
            val kind = PetTargetKind.valueOf(item.getValue("kind").jsonPrimitive.content.uppercase())
            val path = item["path"]?.jsonArray?.map(::point).orEmpty()
            return PetTarget(item.getValue("id").jsonPrimitive.content, kind, PetRect(rect[0], rect[1], rect[2], rect[3]), path)
        }

        val surface = vectors.getValue("surface-inside-moves-to-border").jsonObject
        val surfaceTarget = target(surface.getValue("target"))
        val surfaceStep = surface.getValue("step").jsonPrimitive.float
        val surfaceResult = advancePet(
            PetState(point(surface.getValue("position"))),
            listOf(surfaceTarget),
            viewport,
            halfSize = 0f,
            step = surfaceStep,
        )
        assertEquals(point(surface.getValue("expectedPosition")), surfaceResult.position)
        assertEquals(PetMode.valueOf(surface.getValue("expectedMode").jsonPrimitive.content.uppercase()), surfaceResult.mode)

        val rolling = vectors.getValue("border-rolls-clockwise").jsonObject
        val rollingTarget = target(rolling.getValue("target"))
        val rollingResult = advancePet(
            PetState(point(rolling.getValue("position")), PetMode.IDLE, rollingTarget.id),
            listOf(rollingTarget),
            viewport,
            halfSize = 0f,
            step = rolling.getValue("step").jsonPrimitive.float,
        )
        assertEquals(PetMode.valueOf(rolling.getValue("expectedMode").jsonPrimitive.content.uppercase()), rollingResult.mode)

        val chart = vectors.getValue("chart-path-reverses").jsonObject
        val chartTarget = target(chart.getValue("target"))
        var chartState = PetState(point(chart.getValue("position")))
        var reversed = false
        var sawSlide = false
        repeat(chart.getValue("ticks").jsonPrimitive.content.toInt()) {
            chartState = advancePet(chartState, listOf(chartTarget), viewport, 0f, chart.getValue("step").jsonPrimitive.float)
            if (chartState.pathDirection < 0) reversed = true
            if (chartState.mode == PetMode.SLIDE) sawSlide = true
        }
        assertTrue(sawSlide)
        assertEquals(chart.getValue("mustReverse").jsonPrimitive.boolean, reversed)

        val flight = vectors.getValue("flight-is-vertical-first").jsonObject
        val flightResult = advancePet(
            PetState(
                point(flight.getValue("position")),
                PetMode.valueOf(flight.getValue("mode").jsonPrimitive.content.uppercase()),
            ),
            listOf(target(flight.getValue("target"))),
            viewport,
            0f,
            flight.getValue("step").jsonPrimitive.float,
        )
        assertEquals(point(flight.getValue("expectedPosition")), flightResult.position)
        assertEquals(PetMode.valueOf(flight.getValue("expectedMode").jsonPrimitive.content.uppercase()), flightResult.mode)

        val navigation = vectors.getValue("navigation-prefers-below").jsonObject
        val navigationTargets = navigation.getValue("targets").jsonArray.map(::target)
        val navigationResult = advancePet(
            onNavigation(PetState(point(navigation.getValue("position")), PetMode.SLIDE)),
            navigationTargets,
            viewport,
            0f,
            navigation.getValue("step").jsonPrimitive.float,
        )
        assertEquals(navigation.getValue("expectedTarget").jsonPrimitive.content, navigationResult.targetId)
        assertEquals(point(navigation.getValue("expectedPosition")), navigationResult.position)
        assertEquals(PetMode.FALL, navigationResult.mode)
    }

    @Test
    fun `completed chart cycle pauses then visits another target`() {
        val curve = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 40f, 40f),
            listOf(PetPoint(10f, 10f), PetPoint(20f, 20f), PetPoint(30f, 10f)),
        )
        val other = PetTarget("other", PetTargetKind.CONTROL, PetRect(60f, 10f, 20f, 20f))
        var state = PetState(PetPoint(10f, 10f))
        repeat(8) { state = advancePet(state, listOf(curve, other), viewport, 0f, step = 30f) }

        assertEquals("curve", state.avoidTargetId)
        assertEquals(null, state.targetId)
        assertTrue(state.idleTicksRemaining > 0)

        repeat(state.idleTicksRemaining + 1) {
            state = advancePet(state, listOf(curve, other), viewport, 0f, step = 5f)
        }
        assertEquals("other", state.targetId)
    }
}
