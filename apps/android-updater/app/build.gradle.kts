plugins { jacoco; id("com.android.application"); kotlin("android") }
android {
    useLibrary("android.test.runner", false)
    useLibrary("android.test.base", false)
    // Compile instrumentation against the actual variant being installed.
    // Kotlin internal ABI names differ between debug/release modules.
    testBuildType=providers.gradleProperty("vimarTestBuildType").orElse("debug").get().also { require(it in setOf("debug","release")) }
    namespace="org.openvimar.updater"; compileSdk=35
    defaultConfig { applicationId="org.openvimar.updater"; minSdk=26; targetSdk=35; versionCode=26; versionName="1.0.6"; testInstrumentationRunner="android.test.InstrumentationTestRunner" }
    compileOptions { sourceCompatibility=JavaVersion.VERSION_17; targetCompatibility=JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget="17" }
}
dependencies { implementation(project(":core")); implementation("org.eclipse.paho:org.eclipse.paho.client.mqttv3:1.2.5"); implementation("androidx.core:core:1.12.0"); implementation("no.nordicsemi.android:mcumgr-ble:2.7.4"); implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2"); implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0"); testImplementation("junit:junit:4.13.2") }
dependencyLocking { lockAllConfigurations() }


val publicNotices = tasks.register<Sync>("generatePublicNotices") {
    from(rootProject.projectDir.resolve("../../THIRD_PARTY_NOTICES.md"))
    into(layout.buildDirectory.dir("generated/vomar-notices"))
    rename { "third_party_notices.txt" }
}
android.sourceSets.getByName("main").assets.srcDir(layout.buildDirectory.dir("generated/vomar-notices"))
tasks.named("preBuild").configure { dependsOn(publicNotices) }


jacoco { toolVersion = "0.8.14" }
android.buildTypes.getByName("debug").enableUnitTestCoverage = true
val jacocoDebugReport = tasks.register<JacocoReport>("jacocoDebugReport") {
    dependsOn("testDebugUnitTest")
    executionData(fileTree(layout.buildDirectory) { include("outputs/unit_test_code_coverage/debugUnitTest/*.exec") })
    classDirectories.setFrom(fileTree(layout.buildDirectory.dir("tmp/kotlin-classes/debug")) { exclude("**/R.class", "**/R$*.class", "**/BuildConfig.class") })
    sourceDirectories.setFrom(files("src/main/kotlin"))
    reports { xml.required.set(true); html.required.set(true) }
}
