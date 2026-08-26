plugins {
    kotlin("jvm")
}

kotlin {
    jvmToolchain(17)
}

dependencies {
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
}
