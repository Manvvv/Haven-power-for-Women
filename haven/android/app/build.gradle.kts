plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

android {
    namespace = "com.haven.android"
    compileSdk = 36

    defaultConfig {
        applicationId = "com.haven.android"
        minSdk = 26          // Android 8.0 — required for foreground-service types (API 29+
                              // adds the foregroundServiceType attribute; we handle gracefully)
        targetSdk = 36
        versionCode = 1
        versionName = "1.0.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Build-config fields for backend and frontend endpoints.
        // Production URLs are the default across all builds.
        buildConfigField("String", "HAVEN_BASE_URL", "\"https://haven-power-for-women.onrender.com\"")
        buildConfigField("String", "HAVEN_BASE_URL_HTTPS", "\"https://haven-power-for-women.onrender.com\"")
        // TWA frontend URL — the confirmed production Vercel deployment
        buildConfigField("String", "HAVEN_TWA_URL", "\"https://haven-your-own-voice.vercel.app/\"")
    }

    signingConfigs {
        create("release") {
            storeFile = file("haven-release.keystore")
            storePassword = "haven-release-key-2024"
            keyAlias = "haven"
            keyPassword = "haven-release-key-2024"
        }
    }

    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
            buildConfigField("String", "HAVEN_BASE_URL", "\"https://haven-power-for-women.onrender.com\"")
            buildConfigField("String", "HAVEN_BASE_URL_HTTPS", "\"https://haven-power-for-women.onrender.com\"")
            buildConfigField("String", "HAVEN_TWA_URL", "\"https://haven-your-own-voice.vercel.app/\"")
        }
        debug {
            applicationIdSuffix = ".debug"
            isDebuggable = true
            buildConfigField("String", "HAVEN_BASE_URL", "\"https://haven-power-for-women.onrender.com\"")
            buildConfigField("String", "HAVEN_BASE_URL_HTTPS", "\"https://haven-power-for-women.onrender.com\"")
            buildConfigField("String", "HAVEN_TWA_URL", "\"https://haven-your-own-voice.vercel.app/\"")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
        }
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.service)
    implementation(libs.androidx.activity.compose)

    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.material.icons.extended)

    // Networking
    implementation(libs.retrofit)
    implementation(libs.retrofit.converter.gson)
    implementation(libs.okhttp)
    implementation(libs.okhttp.logging)

    // Coroutines
    implementation(libs.coroutines.android)

    // Secure token storage
    implementation(libs.security.crypto)

    // WorkManager for reliable offline retry
    implementation(libs.work.runtime.ktx)

    // DataStore for monitoring preferences
    implementation(libs.datastore.preferences)

    // Google Play Services Location (FusedLocationProviderClient)
    implementation(libs.play.services.location)

    // Chrome Custom Tabs — used by TwaLauncherActivity (TWA) and external URL handling
    implementation(libs.browser)

    // AppCompat — required by TwaLauncherActivity (extends AppCompatActivity)
    implementation(libs.androidx.appcompat)

    // Fragment >= 1.3.0 required for ActivityResult APIs (fixes InvalidFragmentVersionForActivityResult lint)
    implementation(libs.androidx.fragment.ktx)

    // Testing
    testImplementation(libs.junit)
    testImplementation(libs.mockk)
    testImplementation(libs.coroutines.test)

    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.ui.test.junit4)
    androidTestImplementation(libs.mockk.android)

    debugImplementation(libs.androidx.ui.tooling)
    debugImplementation(libs.androidx.ui.test.manifest)
}
