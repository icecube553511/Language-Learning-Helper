import org.gradle.api.tasks.Copy
import org.gradle.api.tasks.testing.Test

plugins {
    id("com.android.library")
    kotlin("android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val preparePetAsset by tasks.registering(Copy::class) {
    from(rootProject.file("../shared/assets/pets")) {
        include("bingzi.png", "bingzi-left.png")
        rename("bingzi-left.png", "bingzi_left.png")
    }
    into(layout.buildDirectory.dir("generated/pet-res/drawable"))
}

android.sourceSets["main"].res.srcDir(layout.buildDirectory.dir("generated/pet-res"))
tasks.named("preBuild").configure { dependsOn(preparePetAsset) }

android {
    namespace = "com.lexitrack.learning.presentation"
    compileSdk = 35

    defaultConfig {
        minSdk = 26
        consumerProguardFiles("consumer-rules.pro")
    }

    buildFeatures {
        compose = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    api(project(":application"))
    implementation(platform("androidx.compose:compose-bom:2025.04.01"))
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.8.7")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.1")
    debugImplementation("androidx.compose.ui:ui-tooling")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.0")
}

tasks.withType<Test>().configureEach {
    systemProperty(
        "pet.companion.golden.path",
        rootProject.file("../shared/contracts/pet-companion-golden-v1.json").absolutePath,
    )
}
