package org.openvimar.updater

import java.io.IOException
import org.junit.Assert.*
import org.junit.Test

class DkUsbPresenceGuardTest {
    @Test fun boundsPresencePollingAndChecksAgainAtTheBoundaryOrClockRewind() {
        var clock = 0L
        var checks = 0
        val guard = DkUsbPresenceGuard({ clock }) { checks++ }
        guard.check()
        clock = 249_999_999L
        guard.check()
        assertEquals(1, checks)
        clock = 250_000_000L
        guard.check()
        assertEquals(2, checks)
        clock--
        guard.check()
        assertEquals(3, checks)
    }

    @Test fun aLostGenerationCannotReconnectEvenAfterThePollingInterval() {
        var clock = 0L
        var checks = 0
        val lost = IOException("Synthetic USB generation disconnected")
        val guard = DkUsbPresenceGuard({ clock }) { checks++; throw lost }
        assertSame(lost, assertThrows(IOException::class.java) { guard.check() })
        clock += 1_000_000_000L
        assertThrows(IllegalStateException::class.java) { guard.check() }
        assertEquals(1, checks)
    }
}
