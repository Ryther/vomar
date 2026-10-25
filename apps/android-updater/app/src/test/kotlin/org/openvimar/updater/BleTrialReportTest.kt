package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test

class BleTrialReportTest {
 @Test fun failedInspectionExportsGattEvidenceAndActualAppAndAndroidVersions() {
  val events=listOf(mapOf<String,Any?>("event" to "native_gatt","phase" to "CONNECTION_STATE","status" to 22,"newState" to 0))
  val report=BleTrialReport.snapshot(BleTrialState(status="Inspection paused: GATT CONN TERMINATE LOCAL HOST"),"AA:BB:CC:DD:EE:FF","ab".repeat(32),"0.6.2","0.6.2",36,"16",events)
  assertEquals(events,report["bleDiagnostic"]);assertEquals(36,report["androidApi"])
  assertEquals("16",report["androidRelease"]);assertEquals("0.6.2",report["appVersion"])
  assertEquals("AA:BB:CC:DD:EE:FF",report["address"]);assertNull(report["resetAcknowledged"])
 }
 @Test fun reportCannotChangeWhenTheNextAttemptStarts() {
  val event=linkedMapOf<String,Any?>("event" to "gatt","phase" to "FAILED")
  val events=mutableListOf<Map<String,Any?>>(event)
  val report=BleTrialReport.snapshot(BleTrialState(),"AA:BB:CC:DD:EE:FF",null,null,"0.6.2",36,"16",events)
  event["phase"]="READY";events.clear()
  assertEquals(listOf(mapOf("event" to "gatt","phase" to "FAILED")),report["bleDiagnostic"])
 }
}
