package com.lexitrack.learning.domain

import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.double
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlin.test.Test
import kotlin.test.assertEquals

class PetAppearanceTest {
    private val assets = PetAppearanceAssets.fromFileNames(
        stateFiles = listOf("pain.png", "scared.png", "sleep.png", "hungry.png"),
        happyFiles = listOf("happy10.png", "happy2.png", "happy1.png"),
    )

    @Test
    fun `shared golden vectors match selector`() {
        val path = requireNotNull(System.getProperty("pet.appearance.golden.path"))
        val root = Json.parseToJsonElement(File(path).readText()).jsonObject
        assertEquals("pet-appearance-v1", root.getValue("contractVersion").jsonPrimitive.content)
        val assetSet = root.getValue("assetSet").jsonObject
        val goldenAssets = PetAppearanceAssets.fromFileNames(
            stateFiles = assetSet.getValue("stateAssets").jsonObject.values.map { it.jsonPrimitive.content },
            happyFiles = assetSet.getValue("happyAssets").jsonArray.map { it.jsonPrimitive.content },
        )
        root.getValue("vectors").jsonArray.forEach { vectorElement ->
            val vector = vectorElement.jsonObject
            val context = vector.getValue("context").jsonObject
            val vectorAssets = if (vector["assetSet"]?.jsonPrimitive?.content == "empty") {
                PetAppearanceAssets()
            } else {
                goldenAssets
            }
            val decision = selectPetAppearance(
                PetAppearanceContext(
                    landingImpactSpeed = context["landingImpactSpeed"]?.jsonPrimitive?.double ?: 0.0,
                    airborneSeconds = context["airborneSeconds"]?.jsonPrimitive?.double ?: 0.0,
                    stationarySeconds = context["stationarySeconds"]?.jsonPrimitive?.double ?: 0.0,
                    moving = context["moving"]?.jsonPrimitive?.boolean ?: false,
                    satiety = context["satiety"]?.jsonPrimitive?.double,
                    rapidDoubleTap = context["rapidDoubleTap"]?.jsonPrimitive?.boolean ?: false,
                    happyAssetIndex = context["happyAssetIndex"]?.jsonPrimitive?.int ?: 0,
                ),
                vectorAssets,
            )
            val expected = vector.getValue("expected").jsonObject
            assertEquals(expected.getValue("appearance").jsonPrimitive.content, decision.appearance.value)
            assertEquals(expected["asset"]?.jsonPrimitive?.contentOrNull, decision.assetName)
            assertEquals(expected.getValue("reason").jsonPrimitive.content, decision.reason)
        }
    }

    @Test
    fun `thresholds are shared and explicit`() {
        assertEquals(437.5, PET_LARGE_LANDING_SPEED)
        assertEquals(3.0, PET_AIRBORNE_THRESHOLD_SECONDS)
        assertEquals(30.0, PET_STATIONARY_THRESHOLD_SECONDS)
        assertEquals(300L, PET_DOUBLE_TAP_WINDOW_MS)
        assertEquals(0.0, PET_HUNGRY_SATIETY)
    }

    @Test
    fun `large landing wins at boundary`() {
        val decision = selectPetAppearance(
            PetAppearanceContext(landingImpactSpeed = PET_LARGE_LANDING_SPEED),
            assets,
        )
        assertEquals(PetAppearance.PAIN, decision.appearance)
        assertEquals("pain.png", decision.assetName)
    }

    @Test
    fun `airborne condition includes three seconds`() {
        val decision = selectPetAppearance(
            PetAppearanceContext(airborneSeconds = PET_AIRBORNE_THRESHOLD_SECONDS),
            assets,
        )
        assertEquals(PetAppearance.SCARED, decision.appearance)
    }

    @Test
    fun `zero satiety is strict`() {
        assertEquals(
            PetAppearance.HUNGRY,
            selectPetAppearance(PetAppearanceContext(satiety = 0.0), assets).appearance,
        )
        assertEquals(
            PetAppearance.NORMAL,
            selectPetAppearance(PetAppearanceContext(satiety = 0.001), assets).appearance,
        )
    }

    @Test
    fun `stationary and double tap choose sleep and happy`() {
        assertEquals(
            PetAppearance.SLEEP,
            selectPetAppearance(
                PetAppearanceContext(stationarySeconds = PET_STATIONARY_THRESHOLD_SECONDS),
                assets,
            ).appearance,
        )
        val happy = selectPetAppearance(
            PetAppearanceContext(rapidDoubleTap = true, happyAssetIndex = 1),
            assets,
        )
        assertEquals(PetAppearance.HAPPY, happy.appearance)
        assertEquals("happy2.png", happy.assetName)
    }

    @Test
    fun `priority is pain then scared then hungry then other states`() {
        val all = PetAppearanceContext(
            landingImpactSpeed = PET_LARGE_LANDING_SPEED,
            airborneSeconds = PET_AIRBORNE_THRESHOLD_SECONDS,
            satiety = 0.0,
            stationarySeconds = PET_STATIONARY_THRESHOLD_SECONDS,
            rapidDoubleTap = true,
        )
        assertEquals(PetAppearance.PAIN, selectPetAppearance(all, assets).appearance)
        assertEquals(
            PetAppearance.SCARED,
            selectPetAppearance(all.copy(landingImpactSpeed = 0.0), assets).appearance,
        )
    }

    @Test
    fun `missing files retain normal appearance`() {
        val decision = selectPetAppearance(
            PetAppearanceContext(
                landingImpactSpeed = PET_LARGE_LANDING_SPEED,
                airborneSeconds = PET_AIRBORNE_THRESHOLD_SECONDS,
                satiety = 0.0,
                stationarySeconds = PET_STATIONARY_THRESHOLD_SECONDS,
                rapidDoubleTap = true,
            ),
        )
        assertEquals(PetAppearance.NORMAL, decision.appearance)
        assertEquals(null, decision.assetName)
    }
}
