package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test

class DkSwdWatchPolicyTest {
    private class Harness(limit:Int=4) {
        var now=0L
        val watch=DkSwdWatchPolicy(now={now},recentLimit=limit)
        fun attempt():DkSwdWatchToken {assertTrue(watch.start() || watch.snapshot().running);return requireNotNull(watch.beginAttempt())}
        fun full(token:DkSwdWatchToken,uid:List<String> = listOf("0x11223344","0x55667788")) {
            watch.observe(token,"dkPresent",true);watch.observe(token,"probeFirmware","J-Link")
            watch.observe(token,"targetMillivolts",3300);watch.observe(token,"dpidr","0x2ba01477")
            watch.observe(token,"part","0x00052840");watch.observe(token,"uid",uid)
            watch.observe(token,"identityReadVerified",true)
        }
    }
    @Test fun requiresExplicitStartAndNeverOverlapsAttemptsOrTheCompletionInterval() {
        val h=Harness();assertNull(h.watch.beginAttempt());assertTrue(h.watch.start());assertFalse(h.watch.start())
        val first=h.watch.beginAttempt()!!;assertNull(h.watch.beginAttempt())
        h.watch.complete(first,"No DK");assertNull(h.watch.beginAttempt())
        h.now=999;assertNull(h.watch.beginAttempt());h.now=1000;assertNotNull(h.watch.beginAttempt())
    }
    @Test fun keepsPollingThroughAbsenceProbeVoltagePartialAndFullIdentity() {
        val h=Harness();var token=h.attempt()
        h.watch.observe(token,"dkPresent",false);h.watch.complete(token,"Absent")
        assertEquals(DkSwdWatchKind.DK_ABSENT,h.watch.snapshot().kind)
        h.now+=1000;token=h.attempt();h.watch.observe(token,"dkPresent",true);h.watch.observe(token,"probeFirmware","J-Link");h.watch.observe(token,"targetMillivolts",0);h.watch.complete(token,"Low voltage")
        assertEquals(DkSwdWatchKind.VOLTAGE,h.watch.snapshot().kind)
        h.now+=1000;token=h.attempt();h.watch.observe(token,"dkPresent",true);h.watch.observe(token,"probeFirmware","J-Link");h.watch.observe(token,"targetMillivolts",3300);h.watch.complete(token,"No ACK")
        assertEquals(DkSwdWatchKind.PROBE_ONLY,h.watch.snapshot().kind)
        h.now+=1000;token=h.attempt();h.watch.observe(token,"dpidr","0x2ba01477");h.watch.complete(token,"FICR failed")
        assertEquals(DkSwdWatchKind.SWD_PARTIAL,h.watch.snapshot().kind)
        h.now+=1000;token=h.attempt();h.full(token);h.watch.complete(token)
        assertEquals(DkSwdWatchKind.IDENTITY,h.watch.snapshot().kind)
        assertEquals(listOf("11223344","55667788"),h.watch.snapshot().uid)
        assertEquals(1,h.watch.snapshot().stableCount)
        assertFalse(h.watch.snapshot().message.contains("Vimar",ignoreCase=true))
    }
    @Test fun stableIdentityCountsResetAfterFailureAndUidChange() {
        val h=Harness();var token=h.attempt();h.full(token);h.watch.complete(token)
        h.now+=1000;token=h.attempt();h.full(token);h.watch.complete(token);assertEquals(2,h.watch.snapshot().stableCount)
        h.now+=1000;token=h.attempt();h.full(token,listOf("0x12345678","0x9abcdef0"));h.watch.complete(token);assertEquals(1,h.watch.snapshot().stableCount)
        h.now+=1000;token=h.attempt();h.watch.complete(token,"Lost contact");assertEquals(0,h.watch.snapshot().stableCount)
        h.now+=1000;token=h.attempt();h.full(token);h.watch.complete(token);assertEquals(1,h.watch.snapshot().stableCount)
    }
    @Test fun stopRejectsLateObservationsAndRetainsOwnershipUntilAttemptReleases() {
        val h=Harness();val token=h.attempt();h.watch.observe(token,"dpidr","0x2ba01477")
        assertTrue(h.watch.stop());assertFalse(h.watch.snapshot().running)
        assertTrue(h.watch.snapshot().inFlight);assertFalse(h.watch.start())
        assertFalse(h.watch.observe(token,"identityReadVerified",true))
        assertFalse(h.watch.complete(token));assertFalse(h.watch.snapshot().inFlight)
        assertEquals(DkSwdWatchKind.STOPPED,h.watch.snapshot().kind);assertEquals(0,h.watch.snapshot().stableCount)
        assertTrue(h.watch.start());assertNotNull(h.watch.beginAttempt())
    }
    @Test fun staleAttemptCannotCompleteOrMutateANewSession() {
        val h=Harness();val old=h.attempt();h.watch.stop();h.watch.complete(old)
        val current=h.attempt();assertFalse(h.watch.observe(old,"dpidr","0x2ba01477"));assertFalse(h.watch.complete(old))
        assertTrue(h.watch.snapshot().inFlight);h.full(current);assertTrue(h.watch.complete(current))
        assertEquals(1,h.watch.snapshot().stableCount)
    }
    @Test fun boundedExportContainsMetadataOnlyAndInvalidIdentityNeverBecomesFull() {
        val h=Harness(2)
        repeat(5) {index->val token=h.attempt();h.watch.observe(token,"dpidr","0x2ba01477");h.watch.observe(token,"identityReadVerified",true)
            h.watch.observe(token,"uid",listOf("0x1"));h.watch.observe(token,"rawBytes",ByteArray(4096));h.watch.observe(token,"errorText","x".repeat(1000));h.watch.complete(token,"Partial $index");h.now+=1000}
        val snapshot=h.watch.snapshot();assertEquals(2,snapshot.recent.size);assertEquals(5,snapshot.totalAttempts)
        assertEquals(DkSwdWatchKind.SWD_PARTIAL,snapshot.kind);assertEquals(0,snapshot.stableCount)
        assertFalse(snapshot.recent.last().observations.containsKey("rawBytes"))
        assertTrue((snapshot.recent.last().observations["errorText"] as String).length<=512)
        assertEquals(false,h.watch.reportFields()["haltAttempted"])
        assertEquals(false,h.watch.reportFields()["memoryWrite"])
        assertEquals(false,h.watch.reportFields()["commercialModelVerified"])
    }
    @Test fun permissionWaitIsDistinctAndDoesNotClaimAnSwDConnection() {
        val h=Harness();val token=h.attempt();h.watch.observe(token,"dkPresent",true);h.watch.observe(token,"usbPermissionGranted",false)
        assertEquals(DkSwdWatchKind.PERMISSION,h.watch.snapshot().kind)
        assertEquals(0,h.watch.snapshot().stableCount)
    }
    @Test fun intervalStartsAfterCompletionRatherThanAttemptStart() {
        val h=Harness();val token=h.attempt();h.now=5000;h.watch.complete(token,"Slow USB attempt")
        h.now=5999;assertNull(h.watch.beginAttempt());h.now=6000;assertNotNull(h.watch.beginAttempt())
    }
    @Test fun aFailedAttemptCannotPublishFullIdentityEvenAfterItsLastObservation() {
        val h=Harness();val token=h.attempt();h.full(token);h.watch.complete(token,"Connection ended before completion")
        assertEquals(DkSwdWatchKind.SWD_PARTIAL,h.watch.snapshot().kind)
        assertEquals(0,h.watch.snapshot().stableCount);assertNull(h.watch.snapshot().uid)
    }

    @Test fun anotherUsbOwnerClearsOldGreenIdentityAndDoesNotSuggestMovingContacts(){
        val h=Harness();var token=h.attempt();h.full(token);h.watch.complete(token)
        h.now+=1000;token=h.attempt();h.watch.observe(token,"dkPresent",true);h.watch.observe(token,"usbOperationBusy",true)
        assertEquals(DkSwdWatchKind.USB_BUSY,h.watch.snapshot().kind)
        h.watch.complete(token,"Another operation owns the DK")
        assertEquals(0,h.watch.snapshot().stableCount);assertNull(h.watch.snapshot().uid)
        assertTrue(h.watch.snapshot().message.contains("in use"));assertFalse(h.watch.snapshot().message.contains("contacts"))
    }

}
