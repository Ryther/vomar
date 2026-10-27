import java.security.MessageDigest
import org.gradle.api.artifacts.component.ModuleComponentIdentifier
import com.android.build.api.artifact.ScopedArtifact
import com.android.build.api.variant.ScopedArtifacts

plugins { jacoco; id("com.android.application") }
android {
    useLibrary("android.test.runner", false)
    useLibrary("android.test.base", false)
    // Compile instrumentation against the actual variant being installed.
    // Kotlin internal ABI names differ between debug/release modules.
    testBuildType=providers.gradleProperty("vimarTestBuildType").orElse("debug").get().also { require(it in setOf("debug","release")) }
    namespace="org.openvimar.updater"
    compileSdk { version = release(37) { minorApiLevel = 0 } }
    buildToolsVersion="36.0.0"
    defaultConfig { applicationId="org.openvimar.updater"; minSdk=26; targetSdk=35; versionCode=31; versionName="1.1.1"; testInstrumentationRunner="org.openvimar.updater.CoverageInstrumentationTestRunner" }

    compileOptions { sourceCompatibility=JavaVersion.VERSION_17; targetCompatibility=JavaVersion.VERSION_17 }
}
dependencies { implementation(platform("com.fasterxml.jackson:jackson-bom:2.18.12")); implementation(project(":core")); implementation("org.eclipse.paho:org.eclipse.paho.client.mqttv3:1.2.5"); implementation("androidx.core:core:1.19.1"); implementation("no.nordicsemi.android:mcumgr-ble:3.4.1"); implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.11.0"); implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.12.0"); testImplementation("junit:junit:4.13.2"); testImplementation("org.mockito:mockito-subclass:5.24.0") }
dependencyLocking { lockAllConfigurations() }


abstract class PublicNoticesTask : DefaultTask() {
    @get:InputFile
    @get:PathSensitive(PathSensitivity.NONE)
    abstract val noticeFile: RegularFileProperty
    @get:OutputDirectory
    abstract val outputDirectory: DirectoryProperty

    @TaskAction
    fun generate() {
        val destination = outputDirectory.get().asFile.resolve("third_party_notices.txt")
        destination.parentFile.mkdirs()
        noticeFile.get().asFile.copyTo(destination, overwrite = true)
    }
}

androidComponents.onVariants { variant ->
    val notices = tasks.register<PublicNoticesTask>("generate${variant.name.replaceFirstChar { it.uppercase() }}PublicNotices") {
        noticeFile.set(rootProject.layout.projectDirectory.file("../../THIRD_PARTY_NOTICES.md"))
    }
    variant.sources.assets?.addGeneratedSourceDirectory(notices, PublicNoticesTask::outputDirectory)
}

// Run the independently modeled SWD scenarios against actual app classes in
// this JVM, so JaCoCo observes production execution through AGP's Kotlin sources.
android.sourceSets.getByName("test").kotlin.directories.add("../../../tools/android/first_install_contract/programming-tests")


tasks.withType<Test>().configureEach {
    dependsOn(":core:generateFirstInstallTestFixtures")
    inputs.dir(project(":core").layout.buildDirectory.dir("generated/first-install-test-fixtures"))
    systemProperty("vomar.firstInstallFixtures", project(":core").layout.buildDirectory.dir("generated/first-install-test-fixtures").get().asFile.absolutePath)
}

jacoco { toolVersion = "0.8.14" }
android.buildTypes.getByName("debug").enableUnitTestCoverage = true
android.buildTypes.getByName("debug").enableAndroidTestCoverage = true
android.testCoverage.jacocoVersion = "0.8.14"
abstract class VariantJacocoReport : JacocoReport() {
    @get:InputFiles
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val projectJars: ListProperty<RegularFile>
    @get:InputFiles
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val projectDirectories: ListProperty<Directory>
}

val jacocoDebugReport = tasks.register<VariantJacocoReport>("jacocoDebugReport") {
    dependsOn("testDebugUnitTest")
    mustRunAfter(tasks.matching { it.name == "connectedDebugAndroidTest" })
    // Connected tests are an explicit CI/operator action. Reporting never
    // starts an emulator or connects to a target as a side effect.

    executionData(fileTree(layout.buildDirectory) {
        include("outputs/unit_test_code_coverage/debugUnitTest/*.exec")
        include("outputs/code_coverage/debugAndroidTest/connected/**/*.ec")
    })
    val excludedClasses = listOf("**/R.class", "**/R$*.class", "**/BuildConfig.class")
    classDirectories.setFrom(
        projectDirectories.map { directories -> directories.map { it.asFileTree.matching { exclude(excludedClasses) } } },
        projectJars.map { jars -> jars.map { zipTree(it).matching { exclude(excludedClasses) } } }
    )
    sourceDirectories.setFrom(files("src/main/kotlin"))
    reports { xml.required.set(true); html.required.set(true) }
    doFirst {
        require(classDirectories.files.isNotEmpty()) { "No app classes available for coverage" }
        require(executionData.files.isNotEmpty()) { "No app unit test or instrumentation execution data available for coverage" }
    }
}

androidComponents.onVariants(androidComponents.selector().withBuildType("debug")) { variant ->
    variant.artifacts.forScope(ScopedArtifacts.Scope.PROJECT).use(jacocoDebugReport).toGet(
        ScopedArtifact.CLASSES,
        VariantJacocoReport::projectJars,
        VariantJacocoReport::projectDirectories
    )
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
            (component.id as? ModuleComponentIdentifier)?.let { mapOf("ecosystem" to "Maven","name" to "${it.group}:${it.module}","version" to it.version) }
        }.distinct().sortedBy { it["name"] }
        val artifacts=configuration.resolvedConfiguration.resolvedArtifacts.filter {
            it.id.componentIdentifier is ModuleComponentIdentifier
        }.map { artifact ->
            val id=artifact.moduleVersion.id
            mapOf("name" to "${id.group}:${id.name}","version" to id.version,"filename" to artifact.file.name,
                "sha256" to MessageDigest.getInstance("SHA-256").digest(artifact.file.readBytes()).joinToString(""){"%02x".format(it.toInt() and 255)})
        }.sortedBy { it["filename"] }
        val sha=sourceRevision.get()
        val file=output.get().asFile;file.parentFile.mkdirs()
        file.writeText(groovy.json.JsonOutput.prettyPrint(groovy.json.JsonOutput.toJson(mapOf("schemaVersion" to 1,"graph" to "android-runtime","sourceCommit" to sha,"packages" to packages,"artifacts" to artifacts)))+"\n")
    }
}
