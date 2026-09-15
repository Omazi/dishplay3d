plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.dishplay.capture"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.dishplay.capture"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildTypes {
        release { isMinifyEnabled = false }
    }
    lint {
        // Physical camera/AR checks are documented separately from static analysis.
        abortOnError = true
    }
}

dependencies {
    implementation("com.google.ar:core:1.56.0")
    implementation("androidx.core:core:1.15.0")
}
