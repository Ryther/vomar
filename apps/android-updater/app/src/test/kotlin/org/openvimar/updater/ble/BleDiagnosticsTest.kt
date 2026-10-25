package org.openvimar.updater.ble

import org.junit.Assert.*
import org.junit.Test

class BleDiagnosticsTest {
 private val mac="AA:BB:CC:DD:EE:FF"
 @Test fun gattRecordsOnlyPhaseAndIgnoresStaleTokens(){val old=BleDiagnostics.begin(mac);val current=BleDiagnostics.begin(mac);BleDiagnostics.gatt(old,BleDiagnostics.GattPhase.FAILED);BleDiagnostics.gatt(current,BleDiagnostics.GattPhase.READY);val event=BleDiagnostics.snapshot(mac).last();assertEquals("gatt",event["event"]);assertEquals("READY",event["phase"]);assertEquals(setOf("event","attempt","atMillis","phase"),event.keys)}
 @Test fun boundsAndFiltersSnapshots(){val token=BleDiagnostics.begin(mac);repeat(70){BleDiagnostics.scanStarted(token)};assertEquals(40,BleDiagnostics.snapshot(mac).size);assertTrue(BleDiagnostics.snapshot("11:22:33:44:55:66").isEmpty())}
 @Test fun newAttemptDiscardsOldCallbacks(){val old=BleDiagnostics.begin(mac);val fresh=BleDiagnostics.begin(mac);BleDiagnostics.pairing(old,2);BleDiagnostics.createBond(fresh,true);assertEquals(listOf("attempt_started","create_bond"),BleDiagnostics.snapshot(mac).map{it["event"]})}
 @Test fun keepsOnlyTypedMetadataAndCopiesSnapshots(){val token=BleDiagnostics.begin(mac);BleDiagnostics.bond(token,11,10,10,null);BleDiagnostics.pairing(token,0);val snapshot=BleDiagnostics.snapshot(mac);BleDiagnostics.error(token,BleDiagnostics.Stage.SCAN,3);assertEquals(3,snapshot.size);assertTrue(snapshot[1].containsKey("aospReasonBestEffortNonPublicContract"));assertNull(snapshot[1]["aospReasonBestEffortNonPublicContract"]);assertEquals(0,snapshot[2]["variant"]);assertEquals(token,BleDiagnostics.token(mac.lowercase()))}
 @Test fun historyEventCarriesOnlyBoundedValidatedMetadataAndIgnoresOldOwner() {
  val history=org.openvimar.updater.core.RecoveryBootHistory(sequence=9,pendingReason=3,state=org.openvimar.updater.core.BootHistoryState(true,true,false,0,-2,0,0),entries=emptyList())
  val old=BleDiagnostics.begin(mac);val current=BleDiagnostics.begin(mac)
  BleDiagnostics.bootHistory(old,history);BleDiagnostics.bootHistory(current,history)
  val event=BleDiagnostics.snapshot(mac).last()
  assertEquals(setOf("event","attempt","atMillis","sequence","entryCount","pendingReason","storageValid"),event.keys)
  assertEquals("boot_history_validated",event["event"]);assertEquals(0,event["entryCount"]);assertEquals(false,event["storageValid"])
 }
}
