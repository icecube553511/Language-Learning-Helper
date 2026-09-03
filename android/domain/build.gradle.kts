plugins {
    kotlin("jvm")
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.0")
    testImplementation(kotlin("test"))
    testImplementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.0")
}

tasks.test {
    useJUnitPlatform()
    systemProperty(
        "scheduler.golden.path",
        rootProject.file("../shared/contracts/scheduler-golden-v1.json").absolutePath,
    )
    systemProperty(
        "weighted.review.golden.path",
        rootProject.file("../shared/contracts/weighted-review-golden-v1.json").absolutePath,
    )
    systemProperty(
        "dictation.export.golden.path",
        rootProject.file("../shared/contracts/dictation-export-golden-v1.json").absolutePath,
    )
    systemProperty(
        "word.bubble.golden.path",
        rootProject.file("../shared/contracts/word-bubble-golden-v1.json").absolutePath,
    )
    systemProperty(
        "pet.companion.golden.path",
        rootProject.file("../shared/contracts/pet-companion-golden-v1.json").absolutePath,
    )
    systemProperty(
        "pet.vitals.golden.path",
        rootProject.file("../shared/contracts/pet-vitals-golden-v1.json").absolutePath,
    )
    systemProperty(
        "pet.appearance.golden.path",
        rootProject.file("../shared/contracts/pet-appearance-golden-v1.json").absolutePath,
    )
    systemProperty(
        "vocabulary.groups.golden.path",
        rootProject.file("../shared/contracts/vocabulary-groups-golden-v1.json").absolutePath,
    )
}
