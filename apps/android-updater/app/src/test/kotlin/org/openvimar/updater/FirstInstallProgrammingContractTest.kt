package org.openvimar.updater

import java.nio.file.Path
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

/** Existing independent wire model, with real production byte/clock execution. */
@RunWith(Parameterized::class)
class FirstInstallProgrammingContractTest(private val scenario: String) {
    @get:Rule val temporary = TemporaryFolder()

    @Test fun obeysReviewedInstallAndTransportContract() {
        val fixtures = Path.of(System.getProperty("vomar.firstInstallFixtures"))
        val watchdog = "watchdog" in scenario && scenario != "controller-watchdog-no-cap"
        val candidate = if (watchdog) "watchdog" else "candidate"
        val directory = temporary.root.toPath()
        // The standalone dispatcher uses its second argument for directory-only
        // fence scenarios; all package scenarios consume the complete tuple.
        val arguments = if (scenario in setOf("recovery-fence", "resume-capture-fence")) {
            arrayOf(scenario, directory.toString())
        } else {
            arrayOf(scenario, fixtures.resolve("$candidate.zip").toString(),
                fixtures.resolve("$candidate-public.der").toString(), directory.toString())
        }
        main(arguments)
    }

    companion object {
        @JvmStatic @Parameterized.Parameters(name = "{0}") fun scenarios(): List<Array<String>> = listOf(
            "gate", "wire-policy", "wire-wait", "wire-posted-read", "wire-core-registers", "wire-cache",
            "wire-performance", "wire-flash-wait", "wire-flash-fault", "wire-flash-parity", "wire-flash-ready",
            "lease-erase-ready-deadline", "lease-before-cancel", "lease-after-cancel", "lease-happy", "lease-wdt",
            "lease-control", "lease-ready", "lease-posthalt-mode", "lease-posthalt-busy", "lease-cross-boundary",
            "lease-mid-batch-cancel", "lease-batch-uid", "lease-ff-words", "lease-watchdog-paused",
            "lease-watchdog-running", "lease-retired-reset-flag", "controller-prewrite", "controller-full",
            "controller-partial-cancel", "controller-persist-fail", "controller-close-fail", "controller-export-change",
            "controller-begin-persist-fail", "controller-start", "controller-start-changed", "controller-keep-halted",
            "controller-already-custom", "controller-anchor-present", "controller-start-clean-debug",
            "controller-start-wrong-pc", "controller-start-wrong-msp", "controller-start-ignored-catch",
            "controller-start-enable-fail", "controller-paused-watchdog", "controller-watchdog-no-cap",
            "controller-watchdog-running", "controller-watchdog-empty-rre", "controller-watchdog-long",
            "controller-start-open-fail", "controller-resume", "controller-resume-cancel", "controller-resume-verified",
            "recovery-fence", "resume-capture-fence", "selected-document", "host-policy", "resume-mode1", "resume-mode2",
            "resume-cancel", "resume-bad-uicr", "resume-mode-ack-loss", "resume-unconfirmed", "restore-mode1",
            "restore-paused-watchdog", "restore-running-watchdog", "restore-bad-uicr", "restore-wrong-uid",
            "restore-acl", "restore-acl-watchdog", "prepare-acl-lower", "prepare-acl-upper", "prepare-no-acl",
            "prepare-acl-empty", "prepare-acl-capture", "prepare-acl-watchdog", "prepare-acl-persistent",
            "prepare-acl-uncaught", "prepare-acl-cancel", "prepare-acl-empty-vectors", "prepare-acl-read-denied",
            "prepare-acl-wrong-pc", "prepare-acl-wrong-msp", "prepare-acl-even-vector", "prepare-acl-fault"
        ).map { arrayOf(it) }
    }
}
