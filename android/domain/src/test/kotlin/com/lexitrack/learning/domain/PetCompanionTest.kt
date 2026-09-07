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
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class PetCompanionTest {
    private val viewport = PetRect(0f, 0f, 800f, 700f)
    private val sharedGolden by lazy {
        Json.parseToJsonElement(
            File(requireNotNull(System.getProperty("pet.companion.golden.path"))).readText(),
        ).jsonObject
    }

    private fun sharedPoint(value: kotlinx.serialization.json.JsonElement): PetPoint {
        val coordinates = value.jsonArray.map { it.jsonPrimitive.float }
        return PetPoint(coordinates[0], coordinates[1])
    }

    private fun assertPointClose(expected: PetPoint, actual: PetPoint) {
        assertEquals(expected.x, actual.x, 1e-4f)
        assertEquals(expected.y, actual.y, 1e-4f)
    }

    private fun sharedVector(section: String, name: String) =
        sharedGolden.getValue(section).jsonArray
            .map { it.jsonObject }
            .single { it.getValue("name").jsonPrimitive.content == name }

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
    fun `nearest target prefers content over screen edge`() {
        val position = PetPoint(40f, 220f)
        val edge = PetTarget("edge:bottom", PetTargetKind.EDGE, PetRect(0f, 240f, 100f, 3f))
        val control = PetTarget("study:new-card", PetTargetKind.CONTROL, PetRect(10f, 60f, 80f, 24f))
        val viewport = PetRect(0f, 0f, 100f, 250f)

        assertEquals(
            "study:new-card",
            nearestPetTarget(position, listOf(edge, control), viewport = viewport)?.id,
        )
        // With no content available, an edge remains a valid fallback target.
        assertEquals("edge:bottom", nearestPetTarget(position, listOf(edge), viewport = viewport)?.id)
    }

    @Test
    fun `retained edge target yields to content next tick`() {
        val state = PetState(
            position = PetPoint(59f, 120f),
            mode = PetMode.ROLL,
            targetId = "edge:left",
            movementSpeed = 1.2f,
        )
        val targets = listOf(
            PetTarget("edge:left", PetTargetKind.EDGE, PetRect(0f, 0f, 3f, 700f)),
            PetTarget("study:card", PetTargetKind.SURFACE, PetRect(240f, 80f, 600f, 500f)),
        )
        val viewport = PetRect(0f, 0f, 960f, 700f)

        val advanced = advancePet(state, targets, viewport, halfSize = 56f)

        assertNotEquals("edge:left", advanced.targetId)
        assertEquals("study:card", advanced.targetId)
    }

    @Test
    fun `edge remains retained when no content exists`() {
        val state = PetState(
            position = PetPoint(59f, 120f),
            mode = PetMode.ROLL,
            targetId = "edge:left",
            movementSpeed = 1.2f,
        )
        val targets = listOf(PetTarget("edge:left", PetTargetKind.EDGE, PetRect(0f, 0f, 3f, 700f)))
        val viewport = PetRect(0f, 0f, 960f, 700f)

        val advanced = advancePet(state, targets, viewport, halfSize = 56f)

        assertEquals("edge:left", advanced.targetId)
    }

    @Test
    fun `navigation enters fall mode and clears previous target`() {
        val state = PetState(
            PetPoint(100f, 120f),
            PetMode.BOUNCE,
            "chart",
            movementSpeed = 3f,
            verticalVelocity = -4f,
            bouncesRemaining = 1,
            curveVelocity = 2f,
        )

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
        assertEquals(PetMode.FALL, released.mode)
    }

    @Test
    fun `drag release stays put on support and falls when suspended`() {
        val support = PetTarget("card", PetTargetKind.SURFACE, PetRect(20f, 100f, 120f, 40f))
        val onSupport = releaseDrag(
            PetState(PetPoint(60f, 80f), PetMode.DRAGGING),
            listOf(support),
            viewport,
            halfSize = 20f,
        )
        val suspended = releaseDrag(
            PetState(PetPoint(60f, 40f), PetMode.DRAGGING),
            listOf(support),
            viewport,
            halfSize = 20f,
        )

        assertEquals(PetMode.IDLE, onSupport.mode)
        assertEquals("card", onSupport.targetId)
        assertEquals(PetMode.FALL, suspended.mode)
        assertEquals(null, suspended.targetId)
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
        var advanced = entered
        repeat(12) {
            advanced = advancePet(advanced, listOf(chart), viewport, halfSize = 20f, step = 10f)
        }

        assertEquals(PetMode.FLY, entered.mode)
        assertEquals(PetMode.SLIDE, advanced.mode)
        assertEquals("curve", advanced.targetId)
        assertTrue(advanced.position.x > 120f)
        assertTrue(advanced.position.y < 120f)
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
    fun `fall velocity uses seconds and has no artificial cap`() {
        val target = PetTarget("card", PetTargetKind.SURFACE, PetRect(300f, 400f, 120f, 80f))
        val advanced = advancePet(
            PetState(PetPoint(340f, 100f), PetMode.FALL, verticalVelocity = 1_000f),
            listOf(target),
            viewport,
            halfSize = 20f,
        )

        assertEquals(1_055f, advanced.verticalVelocity)
        assertEquals(PetPoint(340f, 116.44f), advanced.position)
    }

    @Test
    fun `fall uses constant acceleration displacement with one four nine cumulative ratio`() {
        val target = PetTarget("landing", PetTargetKind.SURFACE, PetRect(20f, 400f, 120f, 40f))
        var state = PetState(PetPoint(60f, 10f), PetMode.FALL)
        val startY = state.position.y
        val distances = mutableListOf<Float>()

        repeat(3) {
            state = advancePet(state, listOf(target), viewport, halfSize = 0f)
            distances += state.position.y - startY
        }

        val unit = 0.5f * PET_FALL_GRAVITY * PET_FALL_TIME_STEP_SECONDS * PET_FALL_TIME_STEP_SECONDS
        assertEquals(unit, distances[0], 1e-6f)
        assertEquals(unit * 4f, distances[1], 1e-6f)
        assertEquals(unit * 9f, distances[2], 1e-6f)
    }

    @Test
    fun `top portal fall preserves outside y and an upward entry arc`() {
        val viewport = PetRect(0f, 0f, 400f, 300f)
        val support = PetTarget("landing", PetTargetKind.SURFACE, PetRect(0f, 180f, 400f, 20f))
        val entry = PetState(
            PetPoint(200f, -56f),
            PetMode.FALL,
            verticalVelocity = -320f,
        )

        val first = advancePet(entry, listOf(support), viewport, halfSize = 56f)

        assertEquals(PetMode.FALL, first.mode)
        assertTrue(first.position.y < entry.position.y)
        assertEquals(entry.position.x, first.position.x)

        var descending = first
        repeat(30) {
            if (descending.verticalVelocity >= 0f) return@repeat
            descending = advancePet(descending, listOf(support), viewport, halfSize = 56f)
        }
        assertTrue(descending.verticalVelocity >= 0f, "entry arc should turn downward")
        assertTrue(descending.position.y < viewport.top + 56f)
    }

    @Test
    fun `top portal fall keeps a positive entry velocity outside viewport`() {
        val viewport = PetRect(0f, 0f, 400f, 300f)
        val support = PetTarget("landing", PetTargetKind.SURFACE, PetRect(0f, 180f, 400f, 20f))
        val entry = PetState(
            PetPoint(200f, -56f),
            PetMode.FALL,
            verticalVelocity = 125f,
        )

        val first = advancePet(entry, listOf(support), viewport, halfSize = 56f)

        assertEquals(PetMode.FALL, first.mode)
        assertTrue(first.position.y > entry.position.y)
        assertTrue(first.position.y < viewport.top + 56f)
        assertEquals(entry.position.x, first.position.x)
    }

    @Test
    fun `fall never seeks upward support and target loss continues toward viewport bottom`() {
        val above = PetTarget("above", PetTargetKind.SURFACE, PetRect(20f, 20f, 120f, 20f))
        val falling = advancePet(
            PetState(PetPoint(60f, 100f), PetMode.FALL),
            listOf(above),
            viewport,
            halfSize = 0f,
        )
        assertEquals(PetMode.FALL, falling.mode)
        assertTrue(falling.position.y > 100f)
        assertEquals(null, falling.targetId)

        val removed = advancePet(
            PetState(
                PetPoint(60f, 100f),
                PetMode.IDLE,
                targetId = "removed",
                idleTicksRemaining = PET_IDLE_TICKS,
            ),
            emptyList(),
            viewport,
            halfSize = 0f,
        )
        assertEquals(PetMode.FALL, removed.mode)
        assertTrue(removed.position.y > 100f)
        assertEquals(null, removed.targetId)
    }

    @Test
    fun `fall reselects the nearest vertical support on every tick`() {
        val distant = PetTarget("distant", PetTargetKind.SURFACE, PetRect(20f, 400f, 120f, 20f))
        val nearer = PetTarget("nearer", PetTargetKind.SURFACE, PetRect(20f, 180f, 120f, 20f))
        val first = advancePet(
            PetState(PetPoint(60f, 100f), PetMode.FALL, targetId = distant.id),
            listOf(distant),
            viewport,
            halfSize = 0f,
        )

        val afterNearerAppears = advancePet(
            first,
            listOf(distant, nearer),
            viewport,
            halfSize = 0f,
        )

        assertEquals("nearer", afterNearerAppears.targetId)
        assertEquals(PetMode.FALL, afterNearerAppears.mode)
        assertTrue(afterNearerAppears.position.y > first.position.y)
        assertTrue(afterNearerAppears.position.y < nearer.rect.top)
    }

    @Test
    fun `fall lands when already touching the nearest support`() {
        val support = PetTarget("touching", PetTargetKind.SURFACE, PetRect(20f, 100f, 120f, 20f))

        val landed = advancePet(
            PetState(PetPoint(60f, 100f), PetMode.FALL, verticalVelocity = 120f),
            listOf(support),
            viewport,
            halfSize = 0f,
        )

        assertEquals(PetPoint(60f, 100f), landed.position)
        assertEquals(PetMode.IDLE, landed.mode)
        assertEquals("touching", landed.targetId)
    }

    @Test
    fun `fall ignores laterally disjoint support and synthetic bottom still bounces`() {
        val disjoint = PetTarget("disjoint", PetTargetKind.SURFACE, PetRect(300f, 200f, 80f, 20f))
        val first = advancePet(
            PetState(PetPoint(60f, 100f), PetMode.FALL),
            listOf(disjoint),
            viewport,
            halfSize = 0f,
        )
        assertEquals(null, first.targetId)
        assertEquals(PetPoint(60f, 100.44f), first.position)

        val shortViewport = PetRect(0f, 0f, 120f, 100f)
        var bouncing = advancePet(
            PetState(PetPoint(60f, 95f), PetMode.FALL, verticalVelocity = 500f),
            emptyList(),
            shortViewport,
            halfSize = 0f,
        )
        assertEquals(PetMode.BOUNCE, bouncing.mode)
        assertEquals(PET_BOUNCE_COUNT, bouncing.bouncesRemaining)

        repeat(100) {
            if (bouncing.mode == PetMode.BOUNCE) {
                bouncing = advancePet(bouncing, emptyList(), shortViewport, halfSize = 0f)
                assertEquals(60f, bouncing.position.x)
            }
        }
        assertEquals(PetMode.IDLE, bouncing.mode)
        assertEquals(PetPoint(60f, 100f), bouncing.position)
        assertEquals(0, bouncing.bouncesRemaining)
    }

    @Test
    fun `landing threshold uses velocity at contact instead of end of tick`() {
        val target = PetTarget("nearby", PetTargetKind.SURFACE, PetRect(0f, 100f, 200f, 20f))
        val state = advancePet(
            PetState(PetPoint(50f, 99.5f), PetMode.FALL, verticalVelocity = 430f),
            listOf(target),
            PetRect(0f, 0f, 200f, 160f),
            halfSize = 0f,
        )

        assertEquals(PetPoint(50f, 100f), state.position)
        assertEquals(PetMode.IDLE, state.mode)
        assertEquals(0, state.bouncesRemaining)
    }

    @Test
    fun `fall physics scales logical units at the presentation boundary`() {
        val target = PetTarget("landing", PetTargetKind.SURFACE, PetRect(20f, 400f, 120f, 40f))
        val state = advancePet(
            PetState(PetPoint(60f, 10f), PetMode.FALL),
            listOf(target),
            viewport,
            halfSize = 0f,
            fallUnitScale = 2f,
        )

        assertEquals(PetPoint(60f, 10.88f), state.position)
        assertEquals(110f, state.verticalVelocity, 1e-4f)
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
        val support = PetTarget(
            "release-support",
            PetTargetKind.SURFACE,
            PetRect(expected[0] - 40f, expected[1], 80f, 20f),
        )
        val released = releaseDrag(
            moved,
            listOf(support),
            PetRect(0f, 0f, viewportSize[0], viewportSize[1]),
            halfSize = 0f,
        )
        assertEquals(PetPoint(expected[0], expected[1]), released.position)
        assertEquals(PetMode.valueOf(drag.getValue("expectedMode").jsonPrimitive.content.uppercase()), released.mode)
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

        val motion = golden.getValue("motion").jsonObject
        assertEquals(PET_MOTION_ACCELERATION, motion.getValue("acceleration").jsonPrimitive.float)
        assertEquals(PET_CRUISE_SPEED, motion.getValue("cruiseSpeed").jsonPrimitive.float)
        assertEquals(PET_IDLE_TICKS, motion.getValue("idleTicks").jsonPrimitive.content.toInt())
        assertEquals(PET_FALL_TIME_STEP_SECONDS, motion.getValue("fallTimeStepSeconds").jsonPrimitive.float)
        assertEquals(
            PET_FALL_GRAVITY,
            motion.getValue("fallGravityLogicalUnitsPerSecondSquared").jsonPrimitive.float,
        )
        assertEquals("null", motion.getValue("maxFallSpeed").toString())
        assertEquals(PET_HARD_LANDING_SPEED, motion.getValue("hardLandingSpeed").jsonPrimitive.float)
        assertEquals(PET_BOUNCE_COUNT, motion.getValue("bounceCount").jsonPrimitive.content.toInt())
        assertEquals(PET_MAX_BOUNCE_SPEED, motion.getValue("maxBounceSpeed").jsonPrimitive.float)
        assertEquals(PET_MIN_BOUNCE_SPEED, motion.getValue("minBounceSpeed").jsonPrimitive.float)
        assertEquals(PET_BOUNCE_DECAY, motion.getValue("bounceDecay").jsonPrimitive.float)
        assertEquals(PET_BOUNCE_TOP_RESTITUTION, motion.getValue("bounceTopRestitution").jsonPrimitive.float)
        assertEquals("impact-speed-with-restitution", motion.getValue("bounceSpeedPolicy").jsonPrimitive.content)
        assertEquals(PET_CENTER_BIAS_WEIGHT, motion.getValue("centerBiasWeight").jsonPrimitive.float)
        assertEquals(PET_EDGE_PENALTY_RATIO, motion.getValue("edgePenaltyRatio").jsonPrimitive.float)

        val surface = vectors.getValue("surface-inside-moves-to-upper-support").jsonObject
        val surfaceTarget = target(surface.getValue("target"))
        val surfaceStep = surface.getValue("step").jsonPrimitive.float
        val surfaceResult = advancePet(
            PetState(point(surface.getValue("position"))),
            listOf(surfaceTarget),
            viewport,
            halfSize = 0f,
            step = surfaceStep,
        )
        assertPointClose(point(surface.getValue("expectedPosition")), surfaceResult.position)
        assertEquals(PetMode.valueOf(surface.getValue("expectedMode").jsonPrimitive.content.uppercase()), surfaceResult.mode)

        val rolling = vectors.getValue("upper-support-reverses").jsonObject
        val rollingTarget = target(rolling.getValue("target"))
        val rollingResult = advancePet(
            PetState(
                point(rolling.getValue("position")),
                PetMode.IDLE,
                rollingTarget.id,
                movementSpeed = rolling.getValue("movementSpeed").jsonPrimitive.float,
            ),
            listOf(rollingTarget),
            viewport,
            halfSize = 0f,
            step = rolling.getValue("step").jsonPrimitive.float,
        )
        assertPointClose(point(rolling.getValue("expectedPosition")), rollingResult.position)
        assertEquals(PetMode.valueOf(rolling.getValue("expectedMode").jsonPrimitive.content.uppercase()), rollingResult.mode)
        assertEquals(PetFacing.valueOf(rolling.getValue("expectedFacing").jsonPrimitive.content.uppercase()), rollingResult.facing)

        val verticalEdge = vectors.getValue("vertical-screen-edge-remains-traversable").jsonObject
        val verticalEdgeTarget = target(verticalEdge.getValue("target"))
        val verticalEdgeResult = advancePet(
            PetState(
                point(verticalEdge.getValue("position")),
                PetMode.IDLE,
                verticalEdgeTarget.id,
                movementSpeed = verticalEdge.getValue("movementSpeed").jsonPrimitive.float,
            ),
            listOf(verticalEdgeTarget),
            viewport,
            0f,
            verticalEdge.getValue("step").jsonPrimitive.float,
        )
        assertPointClose(point(verticalEdge.getValue("expectedPosition")), verticalEdgeResult.position)
        assertEquals(PetMode.valueOf(verticalEdge.getValue("expectedMode").jsonPrimitive.content.uppercase()), verticalEdgeResult.mode)

        val horizontalEdge = vectors.getValue("horizontal-edge-moves-to-upper-support").jsonObject
        val horizontalEdgeTarget = target(horizontalEdge.getValue("target"))
        val horizontalEdgeResult = advancePet(
            PetState(point(horizontalEdge.getValue("position"))),
            listOf(horizontalEdgeTarget),
            viewport,
            0f,
            horizontalEdge.getValue("step").jsonPrimitive.float,
        )
        assertPointClose(point(horizontalEdge.getValue("expectedPosition")), horizontalEdgeResult.position)
        assertEquals(
            PetMode.valueOf(horizontalEdge.getValue("expectedMode").jsonPrimitive.content.uppercase()),
            horizontalEdgeResult.mode,
        )

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
                movementSpeed = flight.getValue("movementSpeed").jsonPrimitive.float,
            ),
            listOf(target(flight.getValue("target"))),
            viewport,
            0f,
            flight.getValue("step").jsonPrimitive.float,
        )
        assertPointClose(point(flight.getValue("expectedPosition")), flightResult.position)
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
        assertPointClose(point(navigation.getValue("expectedPosition")), navigationResult.position)
        assertEquals(PetMode.FALL, navigationResult.mode)

        val fallback = vectors.getValue("fall-without-below-target-uses-viewport-bottom").jsonObject
        val fallbackViewport = fallback.getValue("viewport").jsonArray.map { it.jsonPrimitive.float }
        val fallbackResult = advancePet(
            PetState(
                point(fallback.getValue("position")),
                PetMode.FALL,
                verticalVelocity = fallback.getValue("verticalVelocity").jsonPrimitive.float,
            ),
            fallback.getValue("targets").jsonArray.map(::target),
            PetRect(0f, 0f, fallbackViewport[0], fallbackViewport[1]),
            halfSize = fallback.getValue("petHalfSize").jsonPrimitive.float,
        )
        assertEquals(null, fallbackResult.targetId)
        assertPointClose(point(fallback.getValue("expectedPositionAfterOneTick")), fallbackResult.position)
        assertEquals(fallback.getValue("expectedVerticalVelocity").jsonPrimitive.float, fallbackResult.verticalVelocity, 1e-4f)
        assertEquals(PetMode.FALL, fallbackResult.mode)

        val fall = vectors.getValue("fall-accelerates").jsonObject
        val fallResult = advancePet(
            PetState(
                point(fall.getValue("position")),
                PetMode.valueOf(fall.getValue("mode").jsonPrimitive.content.uppercase()),
                verticalVelocity = fall.getValue("verticalVelocity").jsonPrimitive.float,
            ),
            listOf(target(fall.getValue("target"))),
            viewport,
            0f,
            fall.getValue("step").jsonPrimitive.float,
        )
        assertPointClose(point(fall.getValue("expectedPosition")), fallResult.position)
        assertEquals(fall.getValue("expectedVerticalVelocity").jsonPrimitive.float, fallResult.verticalVelocity, 1e-4f)
        assertEquals(PetMode.valueOf(fall.getValue("expectedMode").jsonPrimitive.content.uppercase()), fallResult.mode)

        val hardLanding = vectors.getValue("hard-landing-elastic-bounces").jsonObject
        val hardLandingResult = advancePet(
            PetState(
                point(hardLanding.getValue("position")),
                PetMode.valueOf(hardLanding.getValue("mode").jsonPrimitive.content.uppercase()),
                verticalVelocity = hardLanding.getValue("verticalVelocity").jsonPrimitive.float,
            ),
            listOf(target(hardLanding.getValue("target"))),
            viewport,
            0f,
            hardLanding.getValue("step").jsonPrimitive.float,
        )
        assertPointClose(point(hardLanding.getValue("expectedPosition")), hardLandingResult.position)
        assertEquals(PetMode.valueOf(hardLanding.getValue("expectedMode").jsonPrimitive.content.uppercase()), hardLandingResult.mode)
        assertEquals(
            hardLanding.getValue("expectedBouncesRemaining").jsonPrimitive.content.toInt(),
            hardLandingResult.bouncesRemaining,
        )
        assertEquals(
            hardLanding.getValue("expectedBounceVerticalVelocity").jsonPrimitive.float,
            hardLandingResult.verticalVelocity,
            1e-4f,
        )

        val offsetFall = vectors.getValue("fall-skips-horizontally-offset-support").jsonObject
        val offsetViewport = offsetFall.getValue("viewport").jsonArray.map { it.jsonPrimitive.float }
        val offsetResult = advancePet(
            PetState(
                point(offsetFall.getValue("position")),
                PetMode.FALL,
                verticalVelocity = offsetFall.getValue("verticalVelocity").jsonPrimitive.float,
            ),
            offsetFall.getValue("targets").jsonArray.map(::target),
            PetRect(0f, 0f, offsetViewport[0], offsetViewport[1]),
            halfSize = offsetFall.getValue("petHalfSize").jsonPrimitive.float,
        )
        assertEquals(offsetFall.getValue("expectedTarget").jsonPrimitive.content, offsetResult.targetId)
        assertPointClose(point(offsetFall.getValue("expectedPositionAfterOneTick")), offsetResult.position)
        assertEquals(offsetFall.getValue("expectedVerticalVelocity").jsonPrimitive.float, offsetResult.verticalVelocity, 1e-4f)
        assertEquals(PetMode.FALL, offsetResult.mode)

        val retarget = vectors.getValue("fall-retargets-new-nearest-support-every-tick").jsonObject
        val retargetViewport = retarget.getValue("viewport").jsonArray.map { it.jsonPrimitive.float }
        val retargetResult = advancePet(
            PetState(
                point(retarget.getValue("position")),
                PetMode.FALL,
                targetId = retarget.getValue("previousTarget").jsonPrimitive.content,
                verticalVelocity = retarget.getValue("verticalVelocity").jsonPrimitive.float,
            ),
            retarget.getValue("targets").jsonArray.map(::target),
            PetRect(0f, 0f, retargetViewport[0], retargetViewport[1]),
            halfSize = retarget.getValue("petHalfSize").jsonPrimitive.float,
        )
        assertEquals(retarget.getValue("expectedTarget").jsonPrimitive.content, retargetResult.targetId)
        assertPointClose(point(retarget.getValue("expectedPositionAfterOneTick")), retargetResult.position)
        assertEquals(retarget.getValue("expectedVerticalVelocity").jsonPrimitive.float, retargetResult.verticalVelocity, 1e-4f)
        assertEquals(PetMode.FALL, retargetResult.mode)

        val touching = vectors.getValue("fall-already-touching-support-lands").jsonObject
        val touchingViewport = touching.getValue("viewport").jsonArray.map { it.jsonPrimitive.float }
        val touchingResult = advancePet(
            PetState(
                point(touching.getValue("position")),
                PetMode.valueOf(touching.getValue("mode").jsonPrimitive.content.uppercase()),
                verticalVelocity = touching.getValue("verticalVelocity").jsonPrimitive.float,
            ),
            listOf(target(touching.getValue("target"))),
            PetRect(0f, 0f, touchingViewport[0], touchingViewport[1]),
            halfSize = touching.getValue("petHalfSize").jsonPrimitive.float,
        )
        assertPointClose(point(touching.getValue("expectedPosition")), touchingResult.position)
        assertEquals(touching.getValue("expectedTarget").jsonPrimitive.content, touchingResult.targetId)
        assertEquals(
            PetMode.valueOf(touching.getValue("expectedMode").jsonPrimitive.content.uppercase()),
            touchingResult.mode,
        )
        assertEquals(touching.getValue("expectedVerticalVelocity").jsonPrimitive.float, touchingResult.verticalVelocity)

        val synthetic = vectors.getValue("synthetic-bottom-elastic-bounces").jsonObject
        val syntheticViewport = synthetic.getValue("viewport").jsonArray.map { it.jsonPrimitive.float }
        val syntheticResult = advancePet(
            PetState(
                point(synthetic.getValue("position")),
                PetMode.FALL,
                verticalVelocity = synthetic.getValue("verticalVelocity").jsonPrimitive.float,
            ),
            emptyList(),
            PetRect(0f, 0f, syntheticViewport[0], syntheticViewport[1]),
            halfSize = synthetic.getValue("petHalfSize").jsonPrimitive.float,
        )
        assertPointClose(point(synthetic.getValue("expectedPosition")), syntheticResult.position)
        assertEquals(PetMode.BOUNCE, syntheticResult.mode)
        assertEquals(synthetic.getValue("expectedBounceVerticalVelocity").jsonPrimitive.float, syntheticResult.verticalVelocity, 1e-4f)
        assertEquals(
            synthetic.getValue("expectedBouncesRemaining").jsonPrimitive.content.toInt(),
            syntheticResult.bouncesRemaining,
        )

        val suspended = vectors.getValue("suspended-drag-release-enters-fall").jsonObject
        val suspendedViewport = suspended.getValue("viewport").jsonArray.map { it.jsonPrimitive.float }
        val suspendedResult = releaseDrag(
            PetState(point(suspended.getValue("position")), PetMode.DRAGGING),
            suspended.getValue("targets").jsonArray.map(::target),
            PetRect(0f, 0f, suspendedViewport[0], suspendedViewport[1]),
            suspended.getValue("petHalfSize").jsonPrimitive.float,
        )
        assertEquals(PetMode.FALL, suspendedResult.mode)
        assertEquals(null, suspendedResult.targetId)
        assertEquals(0f, suspendedResult.verticalVelocity)

        listOf("center-bias-prefers-interior", "center-bias-measures-nearest-support").forEach { name ->
            val centerBias = vectors.getValue(name).jsonObject
            val centerViewport = centerBias.getValue("viewport").jsonArray.map { it.jsonPrimitive.float }
            val centerTarget = nearestPetTarget(
                point(centerBias.getValue("position")),
                centerBias.getValue("targets").jsonArray.map(::target),
                viewport = PetRect(0f, 0f, centerViewport[0], centerViewport[1]),
            )
            assertEquals(centerBias.getValue("expectedTarget").jsonPrimitive.content, centerTarget?.id)
        }

        val fallPhysics = golden.getValue("fallPhysicsVectors").jsonArray.single().jsonObject
        var physicsState = PetState(
            PetPoint(50f, fallPhysics.getValue("initialPositionY").jsonPrimitive.float),
            PetMode.FALL,
            verticalVelocity = fallPhysics.getValue("initialVerticalVelocity").jsonPrimitive.float,
        )
        val distantLanding = PetTarget("distant", PetTargetKind.SURFACE, PetRect(0f, 600f, 100f, 20f))
        fallPhysics.getValue("samples").jsonArray.forEach { sampleElement ->
            val sample = sampleElement.jsonObject
            physicsState = advancePet(physicsState, listOf(distantLanding), viewport, halfSize = 0f)
            assertEquals(sample.getValue("expectedY").jsonPrimitive.float, physicsState.position.y, 1e-5f)
            assertEquals(
                sample.getValue("expectedVerticalVelocity").jsonPrimitive.float,
                physicsState.verticalVelocity,
                1e-5f,
            )
        }
    }

    @Test
    fun `chart path is offset upward by the pet half size`() {
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(80f, 100f, 120f, 80f),
            listOf(PetPoint(100f, 120f), PetPoint(160f, 140f)),
        )

        val moved = advancePet(
            PetState(PetPoint(100f, 64f)),
            listOf(chart),
            viewport,
            halfSize = 56f,
            step = 4f,
        )

        assertEquals(0f, chart.distanceTo(PetPoint(100f, 64f), margin = 56f))
        assertTrue(moved.position.y in 64f..<120f)
        assertEquals(PetMode.SLIDE, moved.mode)
    }

    @Test
    fun `chart segment midpoint is a legal release support`() {
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 200f, 160f),
            listOf(PetPoint(20f, 100f), PetPoint(100f, 140f)),
        )
        val released = releaseDrag(
            PetState(PetPoint(60f, 110f), PetMode.DRAGGING),
            listOf(chart),
            PetRect(0f, 0f, 200f, 160f),
            halfSize = 10f,
        )
        assertEquals(PetMode.SLIDE, released.mode)
        assertEquals("curve", released.targetId)
        assertEquals(PetPoint(60f, 110f), released.position)
        assertEquals(0f, released.curveVelocity)
        assertEquals(1, released.pathDirection)

        val advanced = advancePet(
            released,
            listOf(chart),
            PetRect(0f, 0f, 200f, 160f),
            halfSize = 10f,
        )
        assertEquals(0.39354795f, advanced.curveVelocity!!, 1e-6f)
        assertTrue(advanced.position.x > released.position.x)
        assertTrue(advanced.position.y > released.position.y)
    }

    @Test
    fun `vertical fall projects world velocity onto descending curve tangent`() {
        val vector = sharedVector(
            "curveLandingVectors",
            "vertical-fall-projects-onto-descending-tangent",
        )
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 200f, 200f),
            vector.getValue("segment").jsonArray.map(::sharedPoint),
        )
        val incoming = sharedPoint(vector.getValue("incomingVelocity"))
        val landed = advancePet(
            PetState(
                position = sharedPoint(vector.getValue("contactPoint")),
                mode = PetMode.FALL,
                targetId = chart.id,
                verticalVelocity = incoming.y,
            ),
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )

        assertEquals(vector.getValue("expectedMode").jsonPrimitive.content, landed.mode.name.lowercase())
        assertEquals(
            vector.getValue("expectedInitialCurveVelocity").jsonPrimitive.float,
            landed.curveVelocity!!,
            1e-5f,
        )
        assertEquals(vector.getValue("expectedPathDirection").jsonPrimitive.float.toInt(), landed.pathDirection)

        val advanced = advancePet(
            landed,
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )
        val expectedPosition = sharedPoint(vector.getValue("expectedNextPosition"))
        assertEquals(
            vector.getValue("expectedNextCurveVelocity").jsonPrimitive.float,
            advanced.curveVelocity!!,
            1e-5f,
        )
        assertEquals(expectedPosition.x, advanced.position.x, 1e-4f)
        assertEquals(expectedPosition.y, advanced.position.y, 1e-4f)
    }

    @Test
    fun `zero speed release starts downhill from exact curve contact`() {
        val vector = sharedVector(
            "curveLandingVectors",
            "zero-speed-mid-segment-starts-downhill-without-vertex-snap",
        )
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 200f, 200f),
            vector.getValue("segment").jsonArray.map(::sharedPoint),
        )
        val contact = sharedPoint(vector.getValue("contactPoint"))
        val landed = releaseDrag(
            PetState(contact, PetMode.DRAGGING),
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )

        assertEquals(contact, landed.position)
        assertEquals(
            vector.getValue("expectedInitialCurveVelocity").jsonPrimitive.float,
            landed.curveVelocity!!,
            1e-6f,
        )
        assertEquals(vector.getValue("expectedPathDirection").jsonPrimitive.float.toInt(), landed.pathDirection)

        val advanced = advancePet(
            landed,
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )
        val expectedPosition = sharedPoint(vector.getValue("expectedNextPosition"))
        assertEquals(
            vector.getValue("expectedNextCurveVelocity").jsonPrimitive.float,
            advanced.curveVelocity!!,
            1e-6f,
        )
        assertEquals(expectedPosition.x, advanced.position.x, 1e-4f)
        assertEquals(expectedPosition.y, advanced.position.y, 1e-4f)
    }

    @Test
    fun `flat curve release ignores stale direction`() {
        val vector = sharedVector(
            "curveLandingVectors",
            "flat-segment-rest-uses-registration-direction",
        )
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 200f, 200f),
            vector.getValue("segment").jsonArray.map(::sharedPoint),
        )
        val contact = sharedPoint(vector.getValue("contactPoint"))
        val landed = releaseDrag(
            PetState(
                position = contact,
                mode = PetMode.DRAGGING,
                pathDirection = vector.getValue("initialPathDirection").jsonPrimitive.float.toInt(),
            ),
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )

        assertEquals(vector.getValue("expectedMode").jsonPrimitive.content, landed.mode.name.lowercase())
        assertEquals(
            vector.getValue("expectedInitialCurveVelocity").jsonPrimitive.float,
            landed.curveVelocity!!,
            1e-6f,
        )
        assertEquals(vector.getValue("expectedPathDirection").jsonPrimitive.float.toInt(), landed.pathDirection)

        val advanced = advancePet(
            landed,
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )
        val expectedPosition = sharedPoint(vector.getValue("expectedNextPosition"))
        assertEquals(
            vector.getValue("expectedNextCurveVelocity").jsonPrimitive.float,
            advanced.curveVelocity!!,
            1e-6f,
        )
        assertEquals(expectedPosition.x, advanced.position.x, 1e-4f)
        assertEquals(expectedPosition.y, advanced.position.y, 1e-4f)
    }

    @Test
    fun `curve uphill endpoint stops and reverses downhill`() {
        val vectors = sharedGolden.getValue("curveEndpointVectors").jsonArray.map { it.jsonObject }
        vectors.forEach { vector ->
            val segment = vector.getValue("segment").jsonArray.map(::sharedPoint)
            val width = segment.maxOf(PetPoint::x) + 100f
            val viewport = PetRect(0f, 0f, width, 200f)
            val chart = PetTarget("curve", PetTargetKind.CHART, viewport, segment)
            var state = PetState(
                position = sharedPoint(vector.getValue("initialPosition")),
                mode = PetMode.SLIDE,
                targetId = chart.id,
                pathIndex = 0,
                pathDirection = vector.getValue("initialPathDirection").jsonPrimitive.float.toInt(),
                curveVelocity = vector.getValue("initialCurveVelocity").jsonPrimitive.float,
            )

            repeat(vector.getValue("expectedEndpointTick").jsonPrimitive.float.toInt()) {
                state = advancePet(state, listOf(chart), viewport, halfSize = 0f)
            }

            val expectedEndpoint = sharedPoint(vector.getValue("expectedEndpointPosition"))
            assertEquals(
                vector.getValue("expectedEndpointMode").jsonPrimitive.content,
                state.mode.name.lowercase(),
                vector.getValue("name").jsonPrimitive.content,
            )
            assertEquals(expectedEndpoint.x, state.position.x, 1e-4f)
            assertEquals(expectedEndpoint.y, state.position.y, 1e-4f)
            assertEquals(
                vector.getValue("expectedEndpointCurveVelocity").jsonPrimitive.float,
                state.curveVelocity!!,
                1e-6f,
            )
            assertEquals(
                vector.getValue("expectedEndpointPathDirection").jsonPrimitive.float.toInt(),
                state.pathDirection,
            )

            state = advancePet(state, listOf(chart), viewport, halfSize = 0f)

            val expectedNext = sharedPoint(vector.getValue("expectedNextPosition"))
            assertEquals(vector.getValue("expectedNextMode").jsonPrimitive.content, state.mode.name.lowercase())
            assertEquals(
                vector.getValue("expectedNextCurveVelocity").jsonPrimitive.float,
                state.curveVelocity!!,
                1e-6f,
            )
            assertEquals(expectedNext.x, state.position.x, 1e-4f)
            assertEquals(expectedNext.y, state.position.y, 1e-4f)
        }
    }

    @Test
    fun `density scale preserves logical curve velocity and scales path budget`() {
        val vector = sharedGolden.getValue("curveScaleVectors").jsonArray.single().jsonObject
        val scale = vector.getValue("unitScale").jsonPrimitive.float
        fun scaled(point: PetPoint) = PetPoint(point.x * scale, point.y * scale)
        val segment = vector.getValue("logicalSegment").jsonArray.map(::sharedPoint).map(::scaled)
        val contact = scaled(sharedPoint(vector.getValue("logicalContactPoint")))
        val incoming = scaled(sharedPoint(vector.getValue("logicalIncomingVelocity")))
        val viewport = PetRect(0f, 0f, 400f, 400f)
        val chart = PetTarget("curve", PetTargetKind.CHART, viewport, segment)
        val landed = advancePet(
            PetState(
                position = contact,
                mode = PetMode.FALL,
                verticalVelocity = incoming.y,
            ),
            listOf(chart),
            viewport,
            halfSize = 0f,
            fallUnitScale = scale,
        )

        assertEquals(vector.getValue("expectedMode").jsonPrimitive.content, landed.mode.name.lowercase())
        assertEquals(
            vector.getValue("expectedInitialLogicalCurveVelocity").jsonPrimitive.float,
            landed.curveVelocity!!,
            1e-5f,
        )

        val advanced = advancePet(
            landed,
            listOf(chart),
            viewport,
            halfSize = 0f,
            fallUnitScale = scale,
        )
        val expectedPosition = sharedPoint(vector.getValue("expectedNextPhysicalPosition"))

        assertEquals(
            vector.getValue("expectedNextLogicalCurveVelocity").jsonPrimitive.float,
            advanced.curveVelocity!!,
            1e-5f,
        )
        assertEquals(expectedPosition.x, advanced.position.x, 1e-4f)
        assertEquals(expectedPosition.y, advanced.position.y, 1e-4f)
    }

    @Test
    fun `curve landing projection clamps uphill speed`() {
        val vector = sharedVector(
            "curveLandingVectors",
            "fling-projection-clamps-uphill-speed",
        )
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 200f, 200f),
            vector.getValue("segment").jsonArray.map(::sharedPoint),
        )
        val incoming = sharedPoint(vector.getValue("incomingVelocity"))
        val landed = advancePet(
            PetState(
                position = sharedPoint(vector.getValue("contactPoint")),
                mode = PetMode.FLING,
                horizontalVelocity = incoming.x,
                verticalVelocity = incoming.y,
            ),
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )

        assertEquals(vector.getValue("expectedMode").jsonPrimitive.content, landed.mode.name.lowercase())
        assertEquals(
            vector.getValue("expectedInitialCurveVelocity").jsonPrimitive.float,
            landed.curveVelocity!!,
            1e-5f,
        )
        assertEquals(vector.getValue("expectedPathDirection").jsonPrimitive.float.toInt(), landed.pathDirection)

        val advanced = advancePet(
            landed,
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )
        val expectedPosition = sharedPoint(vector.getValue("expectedNextPosition"))
        assertEquals(
            vector.getValue("expectedNextCurveVelocity").jsonPrimitive.float,
            advanced.curveVelocity!!,
            1e-5f,
        )
        assertEquals(expectedPosition.x, advanced.position.x, 1e-4f)
        assertEquals(expectedPosition.y, advanced.position.y, 1e-4f)
    }

    @Test
    fun `uphill fling slows and reverses downhill by shared tick limit`() {
        val vector = sharedVector(
            "curveLandingVectors",
            "uphill-fling-slows-before-reversing-downhill",
        )
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 200f, 200f),
            vector.getValue("segment").jsonArray.map(::sharedPoint),
        )
        val incoming = sharedPoint(vector.getValue("incomingVelocity"))
        val landed = advancePet(
            PetState(
                position = sharedPoint(vector.getValue("contactPoint")),
                mode = PetMode.FLING,
                horizontalVelocity = incoming.x,
                verticalVelocity = incoming.y,
            ),
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )

        assertEquals(
            vector.getValue("expectedInitialCurveVelocity").jsonPrimitive.float,
            landed.curveVelocity!!,
            1e-5f,
        )
        assertEquals(vector.getValue("expectedPathDirection").jsonPrimitive.float.toInt(), landed.pathDirection)

        var state = advancePet(
            landed,
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )
        val expectedPosition = sharedPoint(vector.getValue("expectedNextPosition"))
        assertEquals(
            vector.getValue("expectedNextCurveVelocity").jsonPrimitive.float,
            state.curveVelocity!!,
            1e-5f,
        )
        assertEquals(expectedPosition.x, state.position.x, 1e-4f)
        assertEquals(expectedPosition.y, state.position.y, 1e-4f)
        assertTrue(state.position.x < landed.position.x)

        val tickLimit = vector.getValue("expectedDownhillByTick").jsonPrimitive.float.toInt()
        var reversedAt: Int? = if (state.curveVelocity!! >= 0f) 1 else null
        for (tick in 2..tickLimit) {
            state = advancePet(
                state,
                listOf(chart),
                PetRect(0f, 0f, 200f, 200f),
                halfSize = 0f,
            )
            if (reversedAt == null && state.curveVelocity!! >= 0f) reversedAt = tick
        }
        assertEquals(tickLimit, reversedAt)
        assertEquals(1, state.pathDirection)
    }

    @Test
    fun `vertical fall follows downhill when curve registration is reversed`() {
        val vector = sharedVector(
            "curveLandingVectors",
            "vertical-fall-uses-reverse-order-downhill-on-ascending-segment",
        )
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 200f, 200f),
            vector.getValue("segment").jsonArray.map(::sharedPoint),
        )
        val incoming = sharedPoint(vector.getValue("incomingVelocity"))
        val landed = advancePet(
            PetState(
                position = sharedPoint(vector.getValue("contactPoint")),
                mode = PetMode.FALL,
                targetId = chart.id,
                verticalVelocity = incoming.y,
            ),
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )

        assertEquals(
            vector.getValue("expectedInitialCurveVelocity").jsonPrimitive.float,
            landed.curveVelocity!!,
            1e-5f,
        )
        assertEquals(vector.getValue("expectedPathDirection").jsonPrimitive.float.toInt(), landed.pathDirection)

        val advanced = advancePet(
            landed,
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )
        assertEquals(
            vector.getValue("expectedNextCurveVelocity").jsonPrimitive.float,
            advanced.curveVelocity!!,
            1e-5f,
        )
        assertTrue(advanced.position.x < landed.position.x)
        assertTrue(advanced.position.y > landed.position.y)
    }

    @Test
    fun `curve downhill acceleration eases toward terminal speed independent of cruise step`() {
        val vector = sharedVector(
            "curveLandingVectors",
            "zero-speed-mid-segment-starts-downhill-without-vertex-snap",
        )
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 200f, 200f),
            vector.getValue("segment").jsonArray.map(::sharedPoint),
        )
        val landed = releaseDrag(
            PetState(sharedPoint(vector.getValue("contactPoint")), PetMode.DRAGGING),
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )
        val ordinaryStep = advancePet(
            landed,
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
            step = PET_CRUISE_SPEED,
        )
        val overriddenStep = advancePet(
            landed,
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
            step = 30f,
        )
        assertEquals(ordinaryStep.position.x, overriddenStep.position.x, 1e-6f)
        assertEquals(ordinaryStep.position.y, overriddenStep.position.y, 1e-6f)
        assertEquals(ordinaryStep.curveVelocity!!, overriddenStep.curveVelocity!!, 1e-6f)

        var state = landed
        var previousVelocity = 0f
        var previousAcceleration = Float.POSITIVE_INFINITY
        repeat(8) {
            state = advancePet(
                state,
                listOf(chart),
                PetRect(0f, 0f, 200f, 200f),
                halfSize = 0f,
            )
            val velocity = state.curveVelocity!!
            val acceleration = velocity - previousVelocity
            assertTrue(acceleration > 0f)
            assertTrue(acceleration < previousAcceleration)
            assertTrue(velocity < PET_CURVE_DOWNHILL_TERMINAL_SPEED)
            previousVelocity = velocity
            previousAcceleration = acceleration
        }
    }

    @Test
    fun `removing landed curve clears physical velocity before free fall`() {
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 200f, 200f),
            listOf(PetPoint(0f, 100f), PetPoint(100f, 120f)),
        )
        val landed = releaseDrag(
            PetState(PetPoint(50f, 110f), PetMode.DRAGGING),
            listOf(chart),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )

        val falling = advancePet(
            landed.copy(curveVelocity = 2f),
            emptyList(),
            PetRect(0f, 0f, 200f, 200f),
            halfSize = 0f,
        )
        assertEquals(PetMode.FALL, falling.mode)
        assertEquals(null, falling.targetId)
        assertEquals(null, falling.curveVelocity)
    }

    @Test
    fun `support above the viewport is clamped instead of stalling`() {
        val smallViewport = PetRect(0f, 0f, 200f, 160f)
        val target = PetTarget("header", PetTargetKind.CONTROL, PetRect(20f, 20f, 80f, 30f))
        var state = PetState(PetPoint(60f, 80f))

        repeat(40) {
            if (state.mode != PetMode.IDLE || state.targetId == null) {
                state = advancePet(state, listOf(target), smallViewport, halfSize = 56f)
            }
        }

        assertEquals(PetPoint(60f, 56f), state.position)
        assertEquals(PetMode.IDLE, state.mode)
    }

    @Test
    fun `single point chart uses the shared idle duration`() {
        val chart = PetTarget(
            "point",
            PetTargetKind.CHART,
            PetRect(80f, 100f, 40f, 40f),
            listOf(PetPoint(100f, 120f)),
        )

        val arrived = advancePet(
            PetState(PetPoint(100f, 120f)),
            listOf(chart),
            viewport,
            halfSize = 0f,
        )

        assertEquals(PetMode.IDLE, arrived.mode)
        assertEquals(PET_IDLE_TICKS, arrived.idleTicksRemaining)
    }

    @Test
    fun `hard landing performs up to five decaying vertical bounces without horizontal drift`() {
        val target = PetTarget("landing", PetTargetKind.SURFACE, PetRect(20f, 80f, 60f, 20f))
        var state = advancePet(
            PetState(PetPoint(50f, 75f), PetMode.FALL, verticalVelocity = 500f),
            listOf(target),
            viewport,
            halfSize = 0f,
        )
        val remainingCounts = mutableSetOf(state.bouncesRemaining)

        repeat(100) {
            if (state.mode == PetMode.BOUNCE) {
                state = advancePet(state, listOf(target), viewport, halfSize = 0f)
                remainingCounts += state.bouncesRemaining
                assertEquals(50f, state.position.x)
            }
        }

        assertEquals((0..PET_BOUNCE_COUNT).toSet(), remainingCounts)
        assertEquals(PetMode.IDLE, state.mode)
        assertEquals(0, state.bouncesRemaining)
        assertEquals(PetPoint(50f, 80f), state.position)
    }

    @Test
    fun `ordinary movement accelerates and decelerates near support endpoint`() {
        val target = PetTarget("control", PetTargetKind.CONTROL, PetRect(20f, 20f, 60f, 20f))
        var state = PetState(PetPoint(20f, 20f), targetId = target.id)
        val speeds = mutableListOf<Float>()

        repeat(30) {
            if (state.targetId == target.id) {
                state = advancePet(state, listOf(target), viewport, halfSize = 0f)
                speeds += state.movementSpeed
            }
        }

        assertTrue(speeds.max() > speeds.first())
        assertTrue(speeds.zipWithNext().any { (before, after) -> after in 0f..<before })
    }

    @Test
    fun `horizontal motion updates facing while vertical motion preserves it`() {
        val control = PetTarget("control", PetTargetKind.CONTROL, PetRect(20f, 20f, 60f, 20f))
        val left = advancePet(
            PetState(
                PetPoint(60f, 20f),
                targetId = control.id,
                pathDirection = -1,
                movementSpeed = 5f,
            ),
            listOf(control),
            viewport,
            halfSize = 0f,
            step = 5f,
        )
        assertEquals(PetFacing.LEFT, left.facing)

        val edge = PetTarget("left-edge", PetTargetKind.EDGE, PetRect(20f, 20f, 1f, 80f))
        val vertical = advancePet(
            PetState(PetPoint(20f, 40f), targetId = edge.id, movementSpeed = 5f, facing = PetFacing.LEFT),
            listOf(edge),
            viewport,
            halfSize = 0f,
            step = 5f,
        )
        assertEquals(PetFacing.LEFT, vertical.facing)
    }

    @Test
    fun `ordinary and horizontal edge targets never roll on their lower side`() {
        val control = PetTarget("control", PetTargetKind.CONTROL, PetRect(20f, 20f, 60f, 30f))
        val fromControlBottom = advancePet(
            PetState(PetPoint(40f, 50f), targetId = control.id),
            listOf(control),
            viewport,
            halfSize = 0f,
            step = 5f,
        )
        assertEquals(PetMode.FALL, fromControlBottom.mode)
        assertEquals(PetPoint(40f, 50.44f), fromControlBottom.position)

        val bottomEdge = PetTarget("screen-bottom", PetTargetKind.EDGE, PetRect(0f, 99f, 100f, 1f))
        val fromEdgeBottom = advancePet(
            PetState(PetPoint(40f, 100f), targetId = bottomEdge.id),
            listOf(bottomEdge),
            viewport,
            halfSize = 0f,
            step = 5f,
        )
        assertEquals(PetMode.FALL, fromEdgeBottom.mode)
        assertEquals(PetPoint(40f, 100.44f), fromEdgeBottom.position)
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
        repeat(100) {
            if (state.avoidTargetId == null) {
                state = advancePet(state, listOf(curve, other), viewport, 0f, step = 30f)
            }
        }

        assertEquals("curve", state.avoidTargetId)
        assertEquals(null, state.targetId)
        assertTrue(state.idleTicksRemaining > 0)

        repeat(state.idleTicksRemaining + 1) {
            state = advancePet(state, listOf(curve, other), viewport, 0f, step = 5f)
        }
        assertEquals("other", state.targetId)
    }

    @Test
    fun `drag release launches a projectile and preserves terminal tangent`() {
        val released = releaseDrag(
            PetState(PetPoint(320f, 420f), PetMode.DRAGGING),
            releaseVelocity = PetPoint(420f, -680f),
        )
        assertEquals(PetMode.FLING, released.mode)
        assertEquals(420f, released.horizontalVelocity)
        assertEquals(-680f, released.verticalVelocity)

        val tick = advancePet(released, emptyList(), viewport, halfSize = 0f)
        assertEquals(326.72f, tick.position.x, 1e-3f)
        assertEquals(409.56f, tick.position.y, 1e-3f)
        assertEquals(420f, tick.horizontalVelocity, 1e-3f)
        assertEquals(-625f, tick.verticalVelocity, 1e-3f)
    }

    @Test
    fun `release velocity is estimated from recent constrained centres and limited proportionally`() {
        val samples = listOf(
            PetMotionSample(0L, PetPoint(0f, 0f)),
            PetMotionSample(40L, PetPoint(40f, -40f)),
            PetMotionSample(80L, PetPoint(80f, -80f)),
            PetMotionSample(120L, PetPoint(120f, -120f)),
        )
        val velocity = estimateReleaseVelocity(samples)
        assertEquals(1_000f, velocity.x, 1e-3f)
        assertEquals(-1_000f, velocity.y, 1e-3f)
        val limited = limitFlingVelocity(PetPoint(1_800f, -2_400f))
        assertEquals(1_080f, limited.x, 1e-3f)
        assertEquals(-1_440f, limited.y, 1e-3f)
    }

    @Test
    fun `chart slide uses the gentle curve acceleration`() {
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 400f, 200f),
            listOf(PetPoint(20f, 80f), PetPoint(380f, 80f)),
        )
        var state = PetState(PetPoint(20f, 80f))
        val speeds = mutableListOf<Float>()
        repeat(5) {
            state = advancePet(state, listOf(chart), viewport, halfSize = 0f, step = PET_CRUISE_SPEED)
            speeds += state.movementSpeed
        }
        assertEquals(listOf(0.25f, 0.5f, 0.75f, 1f, 1.25f), speeds)
        assertTrue(speeds.zipWithNext().all { (a, b) -> b > a })
    }

    @Test
    fun `fling resolves support after a wall reflection using remaining substep time`() {
        val viewport = PetRect(0f, 0f, 200f, 300f)
        val support = PetTarget("narrow", PetTargetKind.SURFACE, PetRect(198f, 120f, 2f, 10f))
        val state = PetState(
            PetPoint(198f, 115f),
            PetMode.FLING,
            horizontalVelocity = 1_000f,
            verticalVelocity = 1_500f,
        )
        val landed = advancePet(state, listOf(support), viewport, halfSize = 0f)
        assertEquals("narrow", landed.targetId)
        assertEquals(PetMode.BOUNCE, landed.mode)
        assertTrue(landed.position.x > 198.5f)
    }

    @Test
    fun `non finite fling velocity is rejected`() {
        assertEquals(PetPoint(0f, 0f), limitFlingVelocity(PetPoint(Float.NaN, 10f)))
        assertEquals(PetPoint(0f, 0f), limitFlingVelocity(PetPoint(Float.POSITIVE_INFINITY, -10f)))
    }

    @Test
    fun `fling facing follows reflected velocity even when net displacement is forward`() {
        val viewport = PetRect(0f, 0f, 400f, 300f)
        val state = PetState(
            PetPoint(399.01f, 120f),
            PetMode.FLING,
            horizontalVelocity = 100f,
            verticalVelocity = 0f,
            facing = PetFacing.RIGHT,
        )

        val next = advancePet(state, emptyList(), viewport, halfSize = 0f)

        assertEquals(PetFacing.LEFT, next.facing)
        assertTrue(next.horizontalVelocity < 0f)
        assertTrue(next.position.x > state.position.x)
    }

    @Test
    fun `fling lands on the descending root after starting just below a support`() {
        val viewport = PetRect(0f, 0f, 400f, 300f)
        val support = PetTarget("support", PetTargetKind.SURFACE, PetRect(0f, 100f, 400f, 10f))
        val state = PetState(
            PetPoint(200f, 100.01f),
            PetMode.FLING,
            verticalVelocity = -16f,
        )

        val landed = advancePet(state, listOf(support), viewport, halfSize = 0f)

        assertEquals(PetMode.IDLE, landed.mode)
        assertEquals("support", landed.targetId)
        assertEquals(100f, landed.position.y, 1e-5f)
    }

    @Test
    fun `curve brakes near endpoint and consumes remaining budget after reversing`() {
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 40f, 200f),
            listOf(PetPoint(0f, 100f), PetPoint(40f, 100f)),
        )
        val next = advancePet(
            PetState(
                position = PetPoint(39f, 100f),
                mode = PetMode.SLIDE,
                targetId = chart.id,
                pathIndex = 1,
                pathDirection = 1,
                movementSpeed = 4f,
            ),
            listOf(chart),
            viewport,
            halfSize = 0f,
            step = PET_CRUISE_SPEED,
        )

        assertEquals(PetMode.SLIDE, next.mode)
        assertEquals(-1, next.pathDirection)
        assertEquals(3.75f, next.movementSpeed, 1e-5f)
        assertEquals(37.25f, next.position.x, 1e-5f)
    }

    @Test
    fun `curve acceleration stays contractual with a larger cruise budget`() {
        val vector = sharedVector(
            "curveMotionVectors",
            "curve-slide-step-override-keeps-contract-acceleration-and-corner-budget",
        )
        val remainingToCorner = vector.getValue("remainingToCorner").jsonPrimitive.float
        val chart = PetTarget(
            "curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 400f, 200f),
            listOf(PetPoint(0f, 80f), PetPoint(40f, 80f), PetPoint(80f, 80f)),
        )

        val next = advancePet(
            PetState(
                position = PetPoint(40f - remainingToCorner, 80f),
                mode = PetMode.SLIDE,
                targetId = chart.id,
                pathIndex = 1,
                pathDirection = 1,
                movementSpeed = vector.getValue("initialMovementSpeed").jsonPrimitive.float,
            ),
            listOf(chart),
            viewport,
            halfSize = 0f,
            step = vector.getValue("requestedStep").jsonPrimitive.float,
        )

        assertEquals(vector.getValue("expectedMode").jsonPrimitive.content, next.mode.name.lowercase())
        assertEquals(vector.getValue("expectedSpeedAfterCorner").jsonPrimitive.float, next.movementSpeed, 1e-6f)
        assertEquals(
            40f + vector.getValue("expectedBudgetAfterCorner").jsonPrimitive.float,
            next.position.x,
            1e-5f,
        )
    }

    @Test
    fun `horizontal fling touching support does not land at zero time`() {
        val support = PetTarget("support", PetTargetKind.SURFACE, PetRect(50f, 120f, 200f, 30f))
        var next = advancePet(
            PetState(
                position = PetPoint(100f, 100f),
                mode = PetMode.FLING,
                horizontalVelocity = 600f,
                verticalVelocity = 0f,
            ),
            listOf(support),
            viewport,
            halfSize = 20f,
        )

        assertEquals(PetMode.FLING, next.mode)
        assertTrue(next.position.x > 100f)
        assertEquals(100f, next.position.y, 1e-5f)
        assertEquals(600f, next.horizontalVelocity, 1e-5f)

        val supportEdge = support.rect.right + 20f
        while (next.position.x <= supportEdge + 1e-3f) {
            assertEquals(100f, next.position.y, 1e-5f)
            next = advancePet(next, listOf(support), viewport, halfSize = 20f)
        }
        assertTrue(next.position.y > 100f)
    }

    @Test
    fun `sloped chart collision uses relative contact derivative`() {
        val vector = sharedVector(
            "flingPhysicsVectors",
            "sloped-chart-contact-uses-relative-descending-derivative",
        )
        val segment = vector.getValue("chartSegment").jsonArray.map(::sharedPoint)
        val releaseVelocity = sharedPoint(vector.getValue("releaseVelocity"))
        val chart = PetTarget(
            "descending-curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 200f, 200f),
            segment,
        )
        val next = advancePet(
            PetState(
                position = sharedPoint(vector.getValue("initialPosition")),
                mode = PetMode.FLING,
                horizontalVelocity = releaseVelocity.x,
                verticalVelocity = releaseVelocity.y,
            ),
            listOf(chart),
            PetRect(0f, 0f, 400f, 400f),
            halfSize = 0f,
        )

        assertEquals(vector.getValue("expectedMode").jsonPrimitive.content, next.mode.name.lowercase())
        assertEquals(chart.id, next.targetId)
        assertEquals(0f, next.horizontalVelocity, 1e-6f)
        assertEquals(null, next.curveVelocity)
        val expectedContact = sharedPoint(vector.getValue("expectedContactPoint"))
        assertEquals(expectedContact.x, next.position.x, 1e-3f)
        assertEquals(expectedContact.y, next.position.y, 1e-3f)
    }

    @Test
    fun `sloped chart hard landing threshold uses world vertical speed`() {
        val chart = PetTarget(
            "descending-curve",
            PetTargetKind.CHART,
            PetRect(0f, 0f, 200f, 200f),
            listOf(PetPoint(0f, 200f), PetPoint(200f, 0f)),
        )

        val next = advancePet(
            PetState(
                position = PetPoint(100f, 99f),
                mode = PetMode.FLING,
                horizontalVelocity = 1_000f,
                verticalVelocity = -100f,
            ),
            listOf(chart),
            PetRect(0f, 0f, 400f, 400f),
            halfSize = 0f,
        )

        assertEquals(PetMode.SLIDE, next.mode)
        assertEquals(chart.id, next.targetId)
        assertEquals(0f, next.horizontalVelocity, 1e-6f)
        assertEquals(0f, next.verticalVelocity, 1e-6f)
        assertEquals(PET_CURVE_LANDING_SPEED_LIMIT, next.curveVelocity!!, 1e-6f)
        assertEquals(1, next.pathDirection)
    }

    @Test
    fun `hard fling landing clears horizontal velocity throughout bounce`() {
        val support = PetTarget("support", PetTargetKind.SURFACE, PetRect(50f, 120f, 200f, 30f))
        var state = advancePet(
            PetState(
                position = PetPoint(100f, 90f),
                mode = PetMode.FLING,
                horizontalVelocity = 600f,
                verticalVelocity = 1_000f,
            ),
            listOf(support),
            viewport,
            halfSize = 20f,
        )
        assertEquals(PetMode.BOUNCE, state.mode)
        assertEquals(0f, state.horizontalVelocity, 1e-6f)
        assertEquals(null, state.curveVelocity)

        repeat(100) {
            if (state.mode != PetMode.BOUNCE) return@repeat
            state = advancePet(state, listOf(support), viewport, halfSize = 20f)
            assertEquals(0f, state.horizontalVelocity, 1e-6f)
            assertEquals(null, state.curveVelocity)
        }
        assertEquals(PetMode.IDLE, state.mode)
        assertEquals(0f, state.horizontalVelocity, 1e-6f)
        assertEquals(null, state.curveVelocity)
    }

    @Test
    fun `same id support moving away invalidates idle before its countdown`() {
        val target = PetTarget("card", PetTargetKind.SURFACE, PetRect(20f, 150f, 100f, 40f))
        val next = advancePet(
            PetState(PetPoint(60f, 100f), PetMode.IDLE, target.id, idleTicksRemaining = 24),
            listOf(target), viewport, halfSize = 0f,
        )
        assertEquals(PetMode.FALL, next.mode)
        assertEquals(0, next.idleTicksRemaining)
        assertEquals(100.44f, next.position.y, 1e-5f)
        assertEquals(60f, next.position.x)
    }

    @Test
    fun `same id chart reflow begins fall instead of pulling onto the replacement path`() {
        val chart = PetTarget("curve", PetTargetKind.CHART, viewport,
            listOf(PetPoint(0f, 150f), PetPoint(200f, 200f)))
        val next = advancePet(
            PetState(PetPoint(60f, 100f), PetMode.SLIDE, chart.id, curveVelocity = 2f),
            listOf(chart), viewport, halfSize = 0f,
        )
        assertEquals(PetMode.FALL, next.mode)
        assertEquals(null, next.curveVelocity)
        assertEquals(100.44f, next.position.y, 1e-5f)
    }

    @Test
    fun `support rounding tolerance scales with density`() {
        val target = PetTarget("card", PetTargetKind.SURFACE, PetRect(20f, 100f, 200f, 40f))
        fun advance(y: Float) = advancePet(
            PetState(PetPoint(60f, y), PetMode.IDLE, target.id, idleTicksRemaining = 24),
            listOf(target), viewport, halfSize = 0f, fallUnitScale = 2f,
        )
        assertEquals(PetMode.IDLE, advance(99.2f).mode)
        assertEquals(PetMode.FALL, advance(98.8f).mode)
    }

    @Test
    fun `losing a bounce support preserves the upward projectile arc`() {
        val next = advancePet(
            PetState(PetPoint(60f, 100f), PetMode.BOUNCE, "removed",
                verticalVelocity = -100f, bouncesRemaining = 2),
            emptyList(), viewport, halfSize = 0f,
        )
        assertEquals(PetMode.FLING, next.mode)
        assertEquals(-45f, next.verticalVelocity, 1e-4f)
        assertEquals(98.84f, next.position.y, 1e-4f)
        assertEquals(0, next.bouncesRemaining)
    }

    @Test
    fun `orphan bounce retains signed velocity when no targets exist`() {
        val next = advancePet(
            PetState(PetPoint(100f, 100f), PetMode.BOUNCE,
                verticalVelocity = -100f, horizontalVelocity = 75f,
                bouncesRemaining = 2, idleTicksRemaining = 7),
            emptyList(), viewport, halfSize = 0f,
        )
        assertEquals(PetMode.FLING, next.mode)
        assertEquals(-45f, next.verticalVelocity, 1e-4f)
        assertEquals(75f, next.horizontalVelocity, 1e-4f)
        assertPointClose(PetPoint(101.2f, 98.84f), next.position)
        assertEquals(0, next.bouncesRemaining)
        assertEquals(0, next.idleTicksRemaining)
    }

    @Test
    fun `orphan or moved bounce support checks all targets for the first projectile contact`() {
        val behind = PetTarget("behind", PetTargetKind.SURFACE, PetRect(90f, 99f, 20f, 10f))
        val landing = PetTarget("landing", PetTargetKind.SURFACE, PetRect(0f, 110f, 300f, 10f))
        for (targetId in listOf(null, behind.id)) {
            val next = advancePet(
                PetState(PetPoint(100f, 100f), PetMode.BOUNCE, targetId,
                    verticalVelocity = 1_000f, bouncesRemaining = 1),
                listOf(behind, landing), viewport, halfSize = 0f,
            )
            assertEquals(PetMode.BOUNCE, next.mode)
            assertEquals(landing.id, next.targetId)
            assertPointClose(PetPoint(100f, 110f), next.position)
        }
    }

    @Test
    fun `retained edge bounce keeps its support when page content exists`() {
        val edge = PetTarget("edge:bottom", PetTargetKind.EDGE, PetRect(0f, 280f, 400f, 1f))
        val content = PetTarget("card", PetTargetKind.SURFACE, PetRect(0f, 100f, 300f, 20f))
        val next = advancePet(
            PetState(PetPoint(100f, 270f), PetMode.BOUNCE, edge.id,
                verticalVelocity = -100f, bouncesRemaining = 2),
            listOf(content, edge), viewport, halfSize = 0f,
        )
        assertEquals(PetMode.BOUNCE, next.mode)
        assertEquals(edge.id, next.targetId)
        assertPointClose(PetPoint(100f, 268.84f), next.position)
        assertEquals(-45f, next.verticalVelocity, 1e-4f)
    }

    @Test
    fun `completed chart bounce resumes physical sliding from rest`() {
        val chart = PetTarget("curve", PetTargetKind.CHART, viewport,
            listOf(PetPoint(0f, 300f), PetPoint(400f, 500f)))
        var state = advancePet(
            PetState(PetPoint(200f, 390f), PetMode.FALL, verticalVelocity = 800f),
            listOf(chart), viewport, halfSize = 0f,
        )
        assertEquals(PetMode.BOUNCE, state.mode)
        repeat(100) {
            if (state.mode == PetMode.BOUNCE) state = advancePet(state, listOf(chart), viewport, halfSize = 0f)
        }
        assertEquals(PetMode.SLIDE, state.mode)
        assertEquals(chart.id, state.targetId)
        assertEquals(0f, state.curveVelocity)
        assertEquals(0, state.idleTicksRemaining)
        assertPointClose(PetPoint(200f, 400f), state.position)
        val next = advancePet(state, listOf(chart), viewport, halfSize = 0f)
        assertTrue(next.curveVelocity!! > 0f)
        assertTrue(next.position.y > state.position.y)
    }

    @Test
    fun `curve acceleration follows gravity tangent and level contact remains still`() {
        fun advanceRise(rise: Float): PetState {
            val chart = PetTarget("curve", PetTargetKind.CHART, viewport,
                listOf(PetPoint(0f, 100f), PetPoint(200f, 100f + rise)))
            return advancePet(
                PetState(PetPoint(100f, 100f + rise / 2f), PetMode.SLIDE,
                    chart.id, pathIndex = 1, curveVelocity = 0f),
                listOf(chart), viewport, halfSize = 0f,
            )
        }
        val level = advanceRise(0f)
        assertEquals(PetPoint(100f, 100f), level.position)
        assertEquals(0f, level.curveVelocity)
        val shallow = advanceRise(20f)
        val steep = advanceRise(100f)
        assertTrue(steep.curveVelocity!! > shallow.curveVelocity!!)
        assertEquals(-steep.curveVelocity!!, advanceRise(-100f).curveVelocity!!, 1e-6f)
    }

    @Test
    fun `retained path cursor selects outgoing tangent at an exact vertex`() {
        val chart = PetTarget("curve", PetTargetKind.CHART, viewport,
            listOf(PetPoint(0f, 100f), PetPoint(100f, 100f), PetPoint(200f, 150f)))
        val next = advancePet(
            PetState(PetPoint(100f, 100f), PetMode.SLIDE, chart.id,
                pathIndex = 2, pathDirection = 1, curveVelocity = 0.5f),
            listOf(chart), viewport, halfSize = 0f,
        )
        assertTrue(next.curveVelocity!! > 0.5f)
        assertTrue(next.position.y > 100f)
    }

    @Test
    fun `low speed valley settles without facing flicker for successive ticks`() {
        val chart = PetTarget("curve", PetTargetKind.CHART, viewport,
            listOf(PetPoint(20f, 50f), PetPoint(100f, 130f), PetPoint(180f, 50f)))
        var state = PetState(PetPoint(98f, 128f), PetMode.SLIDE, chart.id,
            pathIndex = 1, curveVelocity = 0.1f, facing = PetFacing.RIGHT)
        repeat(180) { state = advancePet(state, listOf(chart), viewport, halfSize = 0f) }
        assertEquals(PetPoint(100f, 130f), state.position)
        assertEquals(0f, state.curveVelocity)
        val settled = state
        repeat(180) {
            state = advancePet(state, listOf(chart), viewport, halfSize = 0f)
            assertEquals(settled, state)
        }
    }

    @Test
    fun `fast valley crossing retains inertia instead of snapping to rest`() {
        val chart = PetTarget("curve", PetTargetKind.CHART, viewport,
            listOf(PetPoint(20f, 50f), PetPoint(100f, 130f), PetPoint(180f, 50f)))
        val next = advancePet(
            PetState(PetPoint(99.9f, 129.9f), PetMode.SLIDE, chart.id,
                pathIndex = 1, curveVelocity = 4f),
            listOf(chart), viewport, halfSize = 0f,
        )
        assertTrue(next.position.x > 100f)
        assertTrue(next.curveVelocity!! > 0f)
    }

    @Test
    fun `autonomous curve movement never exceeds its distance budget at a waypoint`() {
        val chart = PetTarget("curve", PetTargetKind.CHART, viewport,
            listOf(PetPoint(0f, 100f), PetPoint(10f, 100f), PetPoint(200f, 100f)))
        val next = advancePet(
            PetState(PetPoint(9.4f, 100f), PetMode.SLIDE, chart.id, pathIndex = 1),
            listOf(chart), viewport, halfSize = 0f,
        )
        assertEquals(9.65f, next.position.x, 1e-5f)
        assertEquals(0.25f, next.movementSpeed)
    }

    @Test
    fun `release velocity stays accurate after weeks of device uptime`() {
        val epoch = 3_000_000_000L
        val samples = (0..3).map { index ->
            PetMotionSample(epoch + index * 40, PetPoint(index * 40f, -index * 40f))
        }
        val velocity = estimateReleaseVelocity(samples, nowMs = epoch + 120)
        assertEquals(1_000f, velocity.x, 1e-3f)
        assertEquals(-1_000f, velocity.y, 1e-3f)
    }

    @Test
    fun `shared motion stability vectors cover rest gravity and held release`() {
        val valley = sharedVector("motionStabilityVectors", "low-energy-valley-remains-at-rest")
        val chart = PetTarget("curve", PetTargetKind.CHART, viewport,
            valley.getValue("path").jsonArray.map(::sharedPoint))
        var state = PetState(sharedPoint(valley.getValue("position")), PetMode.SLIDE,
            chart.id, pathIndex = 1, curveVelocity = valley.getValue("curveVelocity").jsonPrimitive.float)
        var facingChanges = 0
        repeat(valley.getValue("ticks").jsonPrimitive.content.toInt()) {
            val before = state.facing
            state = advancePet(state, listOf(chart), viewport, halfSize = 0f)
            if (before != state.facing) facingChanges += 1
        }
        assertEquals(sharedPoint(valley.getValue("expectedPosition")), state.position)
        assertEquals(valley.getValue("expectedCurveVelocity").jsonPrimitive.float, state.curveVelocity)
        assertEquals(valley.getValue("expectedFacingChanges").jsonPrimitive.content.toInt(), facingChanges)

        val slopes = sharedVector("motionStabilityVectors", "steeper-slopes-have-stronger-gravity")
        val expectedSpeeds = slopes.getValue("expectedNextCurveVelocities").jsonArray
        slopes.getValue("unitTangents").jsonArray.forEachIndexed { index, value ->
            val tangent = sharedPoint(value)
            val slope = PetTarget("slope", PetTargetKind.CHART, viewport,
                listOf(PetPoint(0f, 100f), PetPoint(tangent.x * 200f, 100f + tangent.y * 200f)))
            val next = advancePet(
                PetState(PetPoint(tangent.x * 100f, 100f + tangent.y * 100f), PetMode.SLIDE,
                    slope.id, pathIndex = 1,
                    curveVelocity = slopes.getValue("initialCurveVelocity").jsonPrimitive.float),
                listOf(slope), viewport, halfSize = 0f,
            )
            assertEquals(expectedSpeeds[index].jsonPrimitive.float, next.curveVelocity!!, 1e-5f)
        }
        val release = sharedVector("motionStabilityVectors", "held-release-discards-old-motion")
        val samples = release.getValue("samples").jsonArray.map { value ->
            val sample = value.jsonObject
            PetMotionSample(sample.getValue("timeMs").jsonPrimitive.content.toLong(), sharedPoint(sample.getValue("position")))
        }
        assertEquals(sharedPoint(release.getValue("expectedVelocity")), estimateReleaseVelocity(
            samples, nowMs = release.getValue("nowMs").jsonPrimitive.content.toLong()))
    }

    @Test
    fun `chart landing uses the original segment near viewport inset`() {
        val chart = PetTarget("curve", PetTargetKind.CHART, viewport,
            listOf(PetPoint(0f, 100f), PetPoint(100f, 200f)))
        val next = advancePet(
            PetState(PetPoint(80f, 123.9f), PetMode.FALL, verticalVelocity = 10f),
            listOf(chart), viewport, halfSize = 56f,
        )
        assertEquals(PetMode.SLIDE, next.mode)
        assertEquals(80f, next.position.x, 1e-4f)
        assertEquals(124f, next.position.y, 1e-4f)
    }

    @Test
    fun `bounce support moved above the arc detaches without snapping upward`() {
        val support = PetTarget("card", PetTargetKind.SURFACE, PetRect(0f, 20f, 200f, 20f))
        val next = advancePet(
            PetState(PetPoint(100f, 100f), PetMode.BOUNCE, support.id,
                verticalVelocity = -100f, bouncesRemaining = 2),
            listOf(support), viewport, halfSize = 0f,
        )
        assertEquals(PetMode.FLING, next.mode)
        assertEquals(98.84f, next.position.y, 1e-4f)
        assertEquals(-45f, next.verticalVelocity, 1e-4f)
    }

    @Test
    fun `physical and autonomous chart travel meet the viewport on the true segment`() {
        val viewport = PetRect(0f, 0f, 200f, 300f)
        val chart = PetTarget("curve", PetTargetKind.CHART, PetRect(0f, 0f, 400f, 300f),
            listOf(PetPoint(0f, 100f), PetPoint(400f, 300f)))
        for (velocity in listOf(8f, null)) {
            val next = advancePet(
                PetState(PetPoint(179f, 169.5f), PetMode.SLIDE, chart.id,
                    pathIndex = 1, curveVelocity = velocity, movementSpeed = 4f),
                listOf(chart), viewport, halfSize = 20f,
            )
            assertEquals(180f, next.position.x, 1e-4f)
            assertEquals(170f, next.position.y, 1e-4f)
            if (velocity != null) assertEquals(PetMode.IDLE, next.mode)
            else assertEquals(-1, next.pathDirection)
        }
    }

    @Test
    fun `fall skips chart contact outside the pet inset instead of clamping onto a false surface`() {
        val chart = PetTarget("curve", PetTargetKind.CHART, viewport,
            listOf(PetPoint(0f, 10f), PetPoint(200f, 10f)))
        val next = advancePet(
            PetState(PetPoint(100f, -12f), PetMode.FALL, verticalVelocity = 120f),
            listOf(chart), viewport, halfSize = 20f,
        )
        assertEquals(PetMode.FALL, next.mode)
        assertEquals(null, next.targetId)
        assertTrue(next.position.y < 0f)
    }

    @Test
    fun `bottom landing stays continuous through every bounce and recovery toward upper content`() {
        val vector = sharedVector("bounceStabilityVectors", "bottom-bounce-retains-anchor-before-upper-content-return")
        val size = sharedPoint(vector.getValue("viewport"))
        val viewport = PetRect(0f, 0f, size.x, size.y)
        fun target(key: String): PetTarget {
            val item = vector.getValue(key).jsonObject
            val rect = item.getValue("rect").jsonArray.map { it.jsonPrimitive.float }
            return PetTarget(item.getValue("id").jsonPrimitive.content,
                PetTargetKind.valueOf(item.getValue("kind").jsonPrimitive.content.uppercase()),
                PetRect(rect[0], rect[1], rect[2], rect[3]))
        }
        val upper = target("upperTarget")
        val bottom = target("bottomTarget")
        val initialPosition = sharedPoint(vector.getValue("position"))
        val targets = listOf(upper, bottom)
        var state = PetState(initialPosition, PetMode.FALL)
        var landed = false
        var recovered = false
        val bounceCounts = mutableSetOf<Int>()
        repeat(vector.getValue("ticks").jsonPrimitive.content.toInt()) {
            val next = advancePet(state, targets, viewport, halfSize = vector.getValue("petHalfSize").jsonPrimitive.float)
            if (next.position.y < state.position.y) {
                assertTrue(state.position.y - next.position.y <= vector.getValue("maxUpwardStep").jsonPrimitive.float)
            }
            if (next.mode == PetMode.BOUNCE) {
                landed = true
                bounceCounts += next.bouncesRemaining
                assertEquals(bottom.id, next.targetId)
                assertEquals(initialPosition.x, next.position.x)
                assertTrue(next.position.y <= vector.getValue("expectedBottomY").jsonPrimitive.float + 1e-3f)
            }
            if (landed && next.mode == PetMode.FLY && next.targetId == upper.id) recovered = true
            state = next
        }
        assertTrue(landed)
        assertEquals((1..vector.getValue("expectedRebounds").jsonPrimitive.content.toInt()).toSet(), bounceCounts)
        assertTrue(recovered)
    }

    @Test
    fun `faster impacts create taller rebounds with a bounded maximum speed`() {
        val viewport = PetRect(0f, 0f, 800f, 2000f)
        fun firstArc(impact: Float): Pair<Float, Float> {
            var state = advancePet(PetState(PetPoint(400f, 1999f), PetMode.FALL, verticalVelocity = impact),
                emptyList(), viewport, halfSize = 0f)
            val firstSpeed = -state.verticalVelocity
            var highestY = state.position.y
            repeat(100) {
                if (state.verticalVelocity < 0f) {
                    state = advancePet(state, emptyList(), viewport, halfSize = 0f)
                    highestY = minOf(highestY, state.position.y)
                }
            }
            return firstSpeed to (viewport.bottom - highestY)
        }
        val slower = firstArc(500f)
        val faster = firstArc(1500f)
        val capped = firstArc(5000f)
        assertTrue(faster.first > slower.first)
        assertTrue(faster.second > slower.second * 4f)
        assertEquals(PET_MAX_BOUNCE_SPEED, capped.first)
        assertTrue(capped.second <= PET_MAX_BOUNCE_SPEED * PET_MAX_BOUNCE_SPEED / (2f * PET_FALL_GRAVITY) + 1e-3f)
        val vector = sharedVector("bounceStabilityVectors", "rebound-speed-follows-impact-with-cap")
        val expected = vector.getValue("expectedReboundSpeeds").jsonArray
        vector.getValue("impactSpeeds").jsonArray.forEachIndexed { index, value ->
            val landed = advancePet(
                PetState(PetPoint(400f, 2000f), PetMode.FALL, verticalVelocity = value.jsonPrimitive.float),
                emptyList(), viewport, halfSize = 0f,
            )
            assertEquals(expected[index].jsonPrimitive.float, -landed.verticalVelocity, 1e-4f)
        }
    }

    @Test
    fun `successive rebound contacts dissipate energy and stop within five arcs`() {
        val viewport = PetRect(0f, 0f, 800f, 2000f)
        var state = advancePet(PetState(PetPoint(400f, 1999f), PetMode.FALL, verticalVelocity = 2000f),
            emptyList(), viewport, halfSize = 0f)
        fun energy(value: PetState) = 0.5f * value.verticalVelocity * value.verticalVelocity +
            PET_FALL_GRAVITY * (viewport.bottom - value.position.y)
        var previousEnergy = energy(state)
        val counts = mutableSetOf(state.bouncesRemaining)
        repeat(250) {
            if (state.mode == PetMode.BOUNCE) {
                val next = advancePet(state, emptyList(), viewport, halfSize = 0f)
                val nextEnergy = energy(next)
                assertTrue(nextEnergy <= previousEnergy + 2f)
                if (next.mode == PetMode.BOUNCE && next.bouncesRemaining < state.bouncesRemaining) {
                    assertEquals(previousEnergy * PET_BOUNCE_DECAY * PET_BOUNCE_DECAY, nextEnergy, 2f)
                }
                counts += next.bouncesRemaining
                previousEnergy = nextEnergy
                state = next
            }
        }
        assertEquals(PetMode.IDLE, state.mode)
        assertEquals((0..PET_BOUNCE_COUNT).toSet(), counts)
        assertPointClose(PetPoint(400f, 2000f), state.position)
    }

    @Test
    fun `bounce reflects at the ceiling and advances the remaining frame time`() {
        val viewport = PetRect(0f, 0f, 400f, 300f)
        val initial = PetState(PetPoint(200f, 10f), PetMode.BOUNCE, "__viewport-bottom__",
            verticalVelocity = -1000f, bouncesRemaining = 5)
        val next = advancePet(initial, emptyList(), viewport, halfSize = 0f)
        val contactTime = (1000f - kotlin.math.sqrt(1000f * 1000f - 2f * PET_FALL_GRAVITY * 10f)) / PET_FALL_GRAVITY
        val reflectedVelocity = (1000f - PET_FALL_GRAVITY * contactTime) * PET_BOUNCE_TOP_RESTITUTION
        val remaining = PET_FALL_TIME_STEP_SECONDS - contactTime
        assertEquals(PetMode.BOUNCE, next.mode)
        assertEquals(5, next.bouncesRemaining)
        assertEquals(reflectedVelocity * remaining + 0.5f * PET_FALL_GRAVITY * remaining * remaining, next.position.y, 1e-4f)
        assertEquals(reflectedVelocity + PET_FALL_GRAVITY * remaining, next.verticalVelocity, 1e-3f)
        assertTrue(next.position.y > 0f)
    }

    @Test
    fun `elastic bounce scales consistently with display density`() {
        val logicalViewport = PetRect(0f, 0f, 400f, 300f)
        var logical = PetState(PetPoint(200f, 299f), PetMode.FALL, verticalVelocity = 1500f)
        var scaled = logical.copy(position = PetPoint(400f, 598f), verticalVelocity = 3000f)
        repeat(150) {
            logical = advancePet(logical, emptyList(), logicalViewport, halfSize = 0f)
            scaled = advancePet(scaled, emptyList(), PetRect(0f, 0f, 800f, 600f), halfSize = 0f, fallUnitScale = 2f)
            assertEquals(logical.mode, scaled.mode)
            assertEquals(logical.bouncesRemaining, scaled.bouncesRemaining)
            assertEquals(logical.position.y * 2f, scaled.position.y, 1e-3f)
            assertEquals(logical.verticalVelocity * 2f, scaled.verticalVelocity, 1e-3f)
        }
    }
}
