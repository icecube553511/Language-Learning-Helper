package com.lexitrack.learning.domain

const val PET_APPEARANCE_VERSION = "pet-appearance-v1"
const val PET_AIRBORNE_THRESHOLD_SECONDS = 3.0
const val PET_STATIONARY_THRESHOLD_SECONDS = 30.0
const val PET_DOUBLE_TAP_WINDOW_MS = 300L
const val PET_HUNGRY_SATIETY = 0.0
const val PET_LARGE_LANDING_SPEED = 437.5

enum class PetAppearance(val value: String) {
    NORMAL("normal"),
    PAIN("pain"),
    SCARED("scared"),
    HUNGRY("hungry"),
    SLEEP("sleep"),
    HAPPY("happy"),
}

data class PetAppearanceAssets(
    val stateFiles: Set<String> = emptySet(),
    val happyFiles: List<String> = emptyList(),
) {
    val complete: Boolean
        get() = setOf("pain.png", "scared.png", "sleep.png", "hungry.png").all(stateFiles::contains) && happyFiles.isNotEmpty()

    companion object {
        private val happyPattern = Regex("^happy([1-9][0-9]*)\\.png$")

        fun fromFileNames(stateFiles: Iterable<String> = emptyList(), happyFiles: Iterable<String> = emptyList()): PetAppearanceAssets {
            val orderedHappy = happyFiles
                .map(String::trim)
                .filter { happyPattern.matches(it) }
                .distinct()
                .sortedWith(compareBy({ happyPattern.matchEntire(it)!!.groupValues[1].toInt() }, { it }))
            return PetAppearanceAssets(stateFiles.map(String::trim).toSet(), orderedHappy)
        }
    }
}

data class PetAppearanceContext(
    val landingImpactSpeed: Double = 0.0,
    val airborneSeconds: Double = 0.0,
    val stationarySeconds: Double = 0.0,
    val moving: Boolean = false,
    val satiety: Double? = null,
    val rapidDoubleTap: Boolean = false,
    val happyAssetIndex: Int = 0,
)

data class PetAppearanceDecision(
    val appearance: PetAppearance,
    val assetName: String? = null,
    val reason: String,
)

private fun atLeast(value: Double, threshold: Double): Boolean = value.isFinite() && value >= threshold

private fun stateDecision(
    appearance: PetAppearance,
    filename: String,
    reason: String,
    assets: PetAppearanceAssets,
): PetAppearanceDecision? = if (filename in assets.stateFiles) {
    PetAppearanceDecision(appearance, filename, reason)
} else {
    null
}

fun selectPetAppearance(
    context: PetAppearanceContext,
    assets: PetAppearanceAssets = PetAppearanceAssets(),
): PetAppearanceDecision {
    // Recommended deterministic order: pain > scared > hungry > sleep > happy > normal.
    if (atLeast(context.landingImpactSpeed, PET_LARGE_LANDING_SPEED)) {
        stateDecision(PetAppearance.PAIN, "pain.png", "large-landing", assets)?.let { return it }
    }
    if (atLeast(context.airborneSeconds, PET_AIRBORNE_THRESHOLD_SECONDS)) {
        stateDecision(PetAppearance.SCARED, "scared.png", "airborne-too-long", assets)?.let { return it }
    }
    if (context.satiety?.isFinite() == true && context.satiety <= PET_HUNGRY_SATIETY) {
        stateDecision(PetAppearance.HUNGRY, "hungry.png", "satiety-zero", assets)?.let { return it }
    }
    if (!context.moving && atLeast(context.stationarySeconds, PET_STATIONARY_THRESHOLD_SECONDS)) {
        stateDecision(PetAppearance.SLEEP, "sleep.png", "stationary-too-long", assets)?.let { return it }
    }
    if (!context.moving && context.rapidDoubleTap && assets.happyFiles.isNotEmpty()) {
        val index = Math.floorMod(context.happyAssetIndex, assets.happyFiles.size)
        return PetAppearanceDecision(PetAppearance.HAPPY, assets.happyFiles[index], "stationary-double-tap")
    }
    return PetAppearanceDecision(PetAppearance.NORMAL, reason = "normal")
}
