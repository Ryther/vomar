plugins { jacoco; kotlin("jvm"); kotlin("plugin.serialization") }
kotlin { jvmToolchain(21)
    sourceSets.main { kotlin.srcDir("../../../tools/android/first_install_contract/src") }
    sourceSets.main { kotlin.srcDir("../../../tools/android/first_install_resume_contract/src") }
    sourceSets.test { kotlin.srcDir("../../../tools/android/first_install_resume_contract/tests") }
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}
dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.11.0")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.12.0")
    implementation("org.apache.commons:commons-compress:1.28.0")
    testImplementation("junit:junit:4.13.2")
}
dependencyLocking { lockAllConfigurations() }
java { sourceCompatibility=JavaVersion.VERSION_17; targetCompatibility=JavaVersion.VERSION_17 }

val firstInstallFixtures = tasks.register<Exec>("generateFirstInstallTestFixtures") {
    val repository = rootProject.projectDir.resolve("../..")
    val output = layout.buildDirectory.dir("generated/first-install-test-fixtures")
    inputs.files(repository.resolve("tools/android/generate_first_install_test_fixtures.py"),
        repository.resolve("tools/android/first_install_contract/tests/test_first_install_contract.py"))
    outputs.dir(output)
    commandLine(providers.environmentVariable("VOMAR_PYTHON").orElse("python3").get(),
        repository.resolve("tools/android/generate_first_install_test_fixtures.py"), "--output", output.get().asFile)
}

tasks.withType<Test>().configureEach {
    dependsOn(firstInstallFixtures)
    inputs.dir(layout.buildDirectory.dir("generated/first-install-test-fixtures"))
    systemProperty("vomar.root", rootProject.projectDir.resolve("../..").canonicalPath)
    systemProperty("vomar.firstInstallFixtures", layout.buildDirectory.dir("generated/first-install-test-fixtures").get().asFile.absolutePath)
}

jacoco { toolVersion = "0.8.14" }
tasks.jacocoTestReport { dependsOn(tasks.test); reports { xml.required.set(true); html.required.set(true) } }
