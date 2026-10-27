import java.security.MessageDigest

plugins { jacoco; id("com.android.application"); kotlin("android") }
android {
    useLibrary("android.test.runner", false)
    useLibrary("android.test.base", false)
    // Compile instrumentation against the actual variant being installed.
    // Kotlin internal ABI names differ between debug/release modules.
    testBuildType=providers.gradleProperty("vimarTestBuildType").orElse("debug").get().also { require(it in setOf("debug","release")) }
    namespace="org.openvimar.updater"; compileSdk=35
    defaultConfig { applicationId="org.openvimar.updater"; minSdk=26; targetSdk=35; versionCode=27; versionName="1.0.7"; testInstrumentationRunner="org.openvimar.updater.CoverageInstrumentationTestRunner" }
    compileOptions { sourceCompatibility=JavaVersion.VERSION_17; targetCompatibility=JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget="17" }
}
dependencies { implementation(platform("com.fasterxml.jackson:jackson-bom:2.18.12")); implementation(project(":core")); implementation("org.eclipse.paho:org.eclipse.paho.client.mqttv3:1.2.5"); implementation("androidx.core:core:1.19.1"); implementation("no.nordicsemi.android:mcumgr-ble:2.7.4"); implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0"); implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0"); testImplementation("junit:junit:4.13.2") }
dependencyLocking { lockAllConfigurations() }


val publicNotices = tasks.register<Sync>("generatePublicNotices") {
    from(rootProject.projectDir.resolve("../../THIRD_PARTY_NOTICES.md"))
    into(layout.buildDirectory.dir("generated/vomar-notices"))
    rename { "third_party_notices.txt" }
}
android.sourceSets.getByName("main").assets.srcDir(layout.buildDirectory.dir("generated/vomar-notices"))
// Run the same independently modeled SWD scenarios against the actual app
// classes in this JVM, so JaCoCo observes production execution.
android.sourceSets.getByName("test").java.srcDir("../../../tools/android/first_install_contract/programming-tests")
tasks.named("preBuild").configure { dependsOn(publicNotices) }

tasks.withType<Test>().configureEach {
    dependsOn(":core:generateFirstInstallTestFixtures")
    inputs.dir(project(":core").layout.buildDirectory.dir("generated/first-install-test-fixtures"))
    systemProperty("vomar.firstInstallFixtures", project(":core").layout.buildDirectory.dir("generated/first-install-test-fixtures").get().asFile.absolutePath)
}


jacoco { toolVersion = "0.8.14" }
android.buildTypes.getByName("debug").enableUnitTestCoverage = true
android.buildTypes.getByName("debug").enableAndroidTestCoverage = true
android.testCoverage.jacocoVersion = "0.8.14"
val jacocoDebugReport = tasks.register<JacocoReport>("jacocoDebugReport") {
    dependsOn("testDebugUnitTest")
    mustRunAfter(tasks.matching { it.name == "connectedDebugAndroidTest" })
    // Connected tests are an explicit CI/operator action. Reporting never
    // starts an emulator or connects to a target as a side effect.
    executionData(fileTree(layout.buildDirectory) {
        include("outputs/unit_test_code_coverage/debugUnitTest/*.exec")
        include("outputs/code_coverage/debugAndroidTest/connected/**/*.ec")
    })
    classDirectories.setFrom(fileTree(layout.buildDirectory.dir("tmp/kotlin-classes/debug")) { exclude("**/R.class", "**/R$*.class", "**/BuildConfig.class") })
    sourceDirectories.setFrom(files("src/main/kotlin"))
    reports { xml.required.set(true); html.required.set(true) }
}

// Resolve the actual release graph through Gradle's locked, verified resolver.
tasks.register("writeRuntimeInventory") {
    val output=layout.buildDirectory.file("reports/dependencies/android-runtime.json")
    outputs.file(output)
    val sourceRevision=providers.exec { workingDir(rootProject.rootDir);commandLine("git","rev-parse","HEAD") }.standardOutput.asText.map { it.trim() }
    inputs.property("sourceCommit",sourceRevision)
    inputs.files(configurations.named("releaseRuntimeClasspath"))
    inputs.file("gradle.lockfile")
    doLast {
        val configuration=configurations.getByName("releaseRuntimeClasspath")
        val packages=configuration.incoming.resolutionResult.allComponents.mapNotNull { component ->
            component.moduleVersion?.let { mapOf("ecosystem" to "Maven","name" to "${it.group}:${it.name}","version" to it.version) }
        }.distinct().sortedBy { it["name"] }
        val artifacts=configuration.resolvedConfiguration.resolvedArtifacts.map { artifact ->
            val id=artifact.moduleVersion.id
            mapOf("name" to "${id.group}:${id.name}","version" to id.version,"filename" to artifact.file.name,
                "sha256" to MessageDigest.getInstance("SHA-256").digest(artifact.file.readBytes()).joinToString(""){"%02x".format(it.toInt() and 255)})
        }.sortedBy { it["filename"] }
        val sha=sourceRevision.get()
        val file=output.get().asFile;file.parentFile.mkdirs()
        file.writeText(groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(mapOf("schemaVersion" to 1,"graph" to "android-runtime","sourceCommit" to sha,"packages" to packages,"artifacts" to artifacts)))+"\n")
    }
}
