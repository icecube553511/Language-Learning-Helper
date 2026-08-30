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
        val state = PetState(
            PetPoint(100f, 120f),
            PetMode.BOUNCE,
            "chart",
            movementSpeed = 3f,
            verticalVelocity = -4f,
            bouncesRemaining = 1,
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

        assertEquals(1_034.375f, advanced.verticalVelocity)
        assertEquals(PetPoint(340f, 116.275f), advanced.position)
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
        assertEquals(PetPoint(60f, 100.275f), first.position)

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

        assertEquals(PetPoint(60f, 10.55f), state.position)
        assertEquals(68.75f, state.verticalVelocity)
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
        assertEquals(PET_FIRST_BOUNCE_SPEED, motion.getValue("firstBounceSpeed").jsonPrimitive.float)
        assertEquals(PET_BOUNCE_DECAY, motion.getValue("bounceDecay").jsonPrimitive.float)
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
        assertEquals(point(surface.getValue("expectedPosition")), surfaceResult.position)
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
        assertEquals(point(rolling.getValue("expectedPosition")), rollingResult.position)
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
        assertEquals(point(verticalEdge.getValue("expectedPosition")), verticalEdgeResult.position)
        assertEquals(PetMode.valueOf(verticalEdge.getValue("expectedMode").jsonPrimitive.content.uppercase()), verticalEdgeResult.mode)

        val horizontalEdge = vectors.getValue("horizontal-edge-moves-to-upper-support").jsonObject
        val horizontalEdgeTarget = target(horizontalEdge.getValue("target"))
        val horizontalEdgeResult = advancePet(
            PetState(point(horizontalEdge.getValue("position")), targetId = horizontalEdgeTarget.id),
            listOf(horizontalEdgeTarget),
            viewport,
            0f,
            horizontalEdge.getValue("step").jsonPrimitive.float,
        )
        assertEquals(point(horizontalEdge.getValue("expectedPosition")), horizontalEdgeResult.position)
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
        assertEquals(point(fallback.getValue("expectedPositionAfterOneTick")), fallbackResult.position)
        assertEquals(fallback.getValue("expectedVerticalVelocity").jsonPrimitive.float, fallbackResult.verticalVelocity)
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
        assertEquals(point(fall.getValue("expectedPosition")), fallResult.position)
        assertEquals(fall.getValue("expectedVerticalVelocity").jsonPrimitive.float, fallResult.verticalVelocity)
        assertEquals(PetMode.valueOf(fall.getValue("expectedMode").jsonPrimitive.content.uppercase()), fallResult.mode)

        val hardLanding = vectors.getValue("hard-landing-bounces-twice").jsonObject
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
        assertEquals(point(hardLanding.getValue("expectedPosition")), hardLandingResult.position)
        assertEquals(PetMode.valueOf(hardLanding.getValue("expectedMode").jsonPrimitive.content.uppercase()), hardLandingResult.mode)
        assertEquals(
            hardLanding.getValue("expectedBouncesRemaining").jsonPrimitive.content.toInt(),
            hardLandingResult.bouncesRemaining,
        )
        assertEquals(
            hardLanding.getValue("expectedBounceVerticalVelocity").jsonPrimitive.float,
            hardLandingResult.verticalVelocity,
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
        assertEquals(point(offsetFall.getValue("expectedPositionAfterOneTick")), offsetResult.position)
        assertEquals(offsetFall.getValue("expectedVerticalVelocity").jsonPrimitive.float, offsetResult.verticalVelocity)
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
        assertEquals(point(retarget.getValue("expectedPositionAfterOneTick")), retargetResult.position)
        assertEquals(retarget.getValue("expectedVerticalVelocity").jsonPrimitive.float, retargetResult.verticalVelocity)
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
        assertEquals(point(touching.getValue("expectedPosition")), touchingResult.position)
        assertEquals(touching.getValue("expectedTarget").jsonPrimitive.content, touchingResult.targetId)
        assertEquals(
            PetMode.valueOf(touching.getValue("expectedMode").jsonPrimitive.content.uppercase()),
            touchingResult.mode,
        )
        assertEquals(touching.getValue("expectedVerticalVelocity").jsonPrimitive.float, touchingResult.verticalVelocity)

        val synthetic = vectors.getValue("synthetic-bottom-hard-landing-bounces-twice").jsonObject
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
        assertEquals(point(synthetic.getValue("expectedPosition")), syntheticResult.position)
        assertEquals(PetMode.BOUNCE, syntheticResult.mode)
        assertEquals(synthetic.getValue("expectedBounceVerticalVelocity").jsonPrimitive.float, syntheticResult.verticalVelocity)
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
    fun `hard landing performs two decaying vertical bounces without horizontal drift`() {
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

        assertTrue(2 in remainingCounts)
        assertTrue(1 in remainingCounts)
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
        assertEquals(PetMode.FLY, fromControlBottom.mode)
        assertEquals(PetPoint(40f, 49.5f), fromControlBottom.position)

        val bottomEdge = PetTarget("screen-bottom", PetTargetKind.EDGE, PetRect(0f, 99f, 100f, 1f))
        val fromEdgeBottom = advancePet(
            PetState(PetPoint(40f, 100f), targetId = bottomEdge.id),
            listOf(bottomEdge),
            viewport,
            halfSize = 0f,
            step = 5f,
        )
        assertEquals(PetMode.FLY, fromEdgeBottom.mode)
        assertEquals(PetPoint(40f, 99.5f), fromEdgeBottom.position)
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
}
