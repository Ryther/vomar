package org.openvimar.installer.resume

import java.nio.file.Path
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

/** Runs retained-evidence repair scenarios against instrumented core classes. */
@RunWith(Parameterized::class)
class ExplicitResumeContractTest(private val scenario: String) {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun repairsOnlyTheReviewedOriginalAndIssuedFrontier() {
        val fixtures = Path.of(System.getProperty("vomar.firstInstallFixtures"))
        val original = if (scenario.startsWith("body-short-frontier")) "original-erased-tail.zip" else "original.zip"
        resumeEngineProbe(arrayOf("engine", fixtures.resolve(original).toString(),
            fixtures.resolve("candidate.zip").toString(), fixtures.resolve("candidate-public.der").toString(),
            temporary.root.toString(), scenario))
    }

    companion object {
        @JvmStatic @Parameterized.Parameters(name = "{0}") fun scenarios(): List<Array<String>> = listOf(
            "one-damaged-page", "good", "body-ready", "body-short-frontier", "body-short-frontier-lost",
            "body-short-frontier-tail", "committed", "unissued-changed", "uicr", "uid", "cancel-prior", "cancel-after",
            "generation", "lost-commit", "stale-head", "stale-prepared", "replay-prepared", "wrong-generation", "resume-again"
        ).map { arrayOf(it) }
    }
}
