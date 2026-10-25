plugins { kotlin("jvm"); kotlin("plugin.serialization") }
kotlin { jvmToolchain(21)
    sourceSets.main { kotlin.srcDir("../../../tools/android/first_install_contract/src") }
    sourceSets.main { kotlin.srcDir("../../../tools/android/first_install_resume_contract/src") }
    compilerOptions { jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17) }
}
dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-core:1.10.2")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.9.0")
    implementation("org.apache.commons:commons-compress:1.28.0")
    testImplementation("junit:junit:4.13.2")
}
dependencyLocking { lockAllConfigurations() }
java { sourceCompatibility=JavaVersion.VERSION_17; targetCompatibility=JavaVersion.VERSION_17 }

tasks.withType<Test>().configureEach {
    systemProperty("vomar.root", rootProject.projectDir.resolve("../..").canonicalPath)
}
