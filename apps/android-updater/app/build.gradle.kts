plugins { id("com.android.application"); kotlin("android") }
android {
    useLibrary("android.test.runner", false)
    useLibrary("android.test.base", false)
    // Compile instrumentation against the actual variant being installed.
    // Kotlin internal ABI names differ between debug/release modules.
    testBuildType=providers.gradleProperty("vimarTestBuildType").orElse("debug").get().also { require(it in setOf("debug","release")) }
    namespace="org.openvimar.updater"; compileSdk=35
    defaultConfig { applicationId="org.openvimar.updater"; minSdk=26; targetSdk=35; versionCode=23; versionName="1.0.3"; testInstrumentationRunner="android.test.InstrumentationTestRunner" }
    compileOptions { sourceCompatibility=JavaVersion.VERSION_17; targetCompatibility=JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget="17" }
}
dependencies { implementation(project(":core")); implementation("org.eclipse.paho:org.eclipse.paho.client.mqttv3:1.2.5"); implementation("androidx.core:core:1.12.0"); implementation("no.nordicsemi.android:mcumgr-ble:2.7.4"); implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2"); implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0"); testImplementation("junit:junit:4.13.2") }
dependencyLocking { lockAllConfigurations() }
