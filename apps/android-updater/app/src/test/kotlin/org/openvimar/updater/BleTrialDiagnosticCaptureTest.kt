package org.openvimar.updater

import org.openvimar.updater.ble.BleDiagnostics
import org.junit.Assert.*
import org.junit.Test

class BleTrialDiagnosticCaptureTest {
 private val address="AA:BB:CC:DD:EE:FF"
 @Test fun freezesThisAttemptBeforeAnotherRadioOwnerStarts() {
  val capture=BleTrialDiagnosticCapture();capture.begin();capture.target(address)
  val token=BleDiagnostics.begin(address);BleDiagnostics.gatt(token,BleDiagnostics.GattPhase.FAILED)
  capture.finish();BleDiagnostics.begin("11:22:33:44:55:66")
  assertEquals(listOf("attempt_started","gatt"),capture.events.map{it["event"]})
  assertEquals("FAILED",capture.events.last()["phase"])
 }
 @Test fun preflightFailureDoesNotExportAnOldTraceForTheSameAddress() {
  val old=BleDiagnostics.begin(address);BleDiagnostics.gatt(old,BleDiagnostics.GattPhase.READY)
  val capture=BleTrialDiagnosticCapture();capture.begin();capture.target(address);capture.finish()
  assertTrue(capture.events.isEmpty())
 }
 @Test fun deniedLeaseCannotReuseLastTrialsEvidence() {
  val capture=BleTrialDiagnosticCapture();capture.begin();capture.target(address)
  BleDiagnostics.begin(address);capture.finish();assertFalse(capture.events.isEmpty())
  capture.begin() // Admission fails before a new target/connection is made.
  assertTrue(capture.events.isEmpty())
 }
 @Test fun unrelatedDeviceTraceDoesNotBecomeTargetEvidence() {
  val capture=BleTrialDiagnosticCapture();capture.begin();capture.target(address)
  BleDiagnostics.begin("11:22:33:44:55:66");capture.finish()
  assertTrue(capture.events.isEmpty())
 }
}
