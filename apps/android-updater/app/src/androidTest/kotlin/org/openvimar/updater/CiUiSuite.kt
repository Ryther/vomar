package org.openvimar.updater

import junit.framework.Test
import junit.framework.TestSuite

/** One class argument avoids the pinned engine's comma argument truncation.
 * All members use synthetic packages, preferences or transports. */
class CiUiSuite : TestSuite() {
    companion object {
        @JvmStatic fun suite(): Test = TestSuite("Vomar synthetic UI journeys").apply {
            addTestSuite(InitialInstallUiTest::class.java)
            addTestSuite(InitialInstallAndroidAdapterTest::class.java)
            addTestSuite(BleTrialUiTest::class.java)
            addTestSuite(AutomaticConnectionUiTest::class.java)
            addTestSuite(AutomaticNetworkConnectionTest::class.java)
            addTestSuite(NativeFleetUiTest::class.java)
            addTestSuite(SavedConnectionPersistenceTest::class.java)
        }
    }
}
