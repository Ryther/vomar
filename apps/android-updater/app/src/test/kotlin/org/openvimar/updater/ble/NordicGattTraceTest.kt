package org.openvimar.updater.ble

import org.junit.Assert.*
import org.junit.Test

class NordicGattTraceTest {
 private val address="AA:BB:CC:DD:EE:FF"
 @Test fun reportsExplicitBondAttemptWithoutSavingSystemPairingSecrets() {
  val token=BleDiagnostics.begin(address)
  listOf("Starting bonding...","device.createBond()","[Broadcast] PAIRING_REQUEST key=123456","Device bonded","Bonding failed").forEach{NordicGattTrace.capture(token,it)}
  assertEquals(listOf("BOND_REQUESTED","BOND_CREATE_CALLED","BOND_ESTABLISHED","BOND_FAILED"),BleDiagnostics.snapshot(address).drop(1).map{it["phase"]})
  assertFalse(BleDiagnostics.snapshot(address).toString().contains("123456"))
 }
 @Test fun recordsConnectionStatusBeforeTheFinalGenericError() {
  val token=BleDiagnostics.begin(address)
  NordicGattTrace.capture(token,"[Callback] Connection state changed with status: 22 and new state: 0 (DISCONNECTED)")
  val event=BleDiagnostics.snapshot(address).last()
  assertEquals("native_gatt",event["event"]);assertEquals("CONNECTION_STATE",event["phase"])
  assertEquals(22,event["status"]);assertEquals(0,event["newState"])
 }
 @Test fun distinguishesMtuFailureFromAuthenticatedNotificationSetup() {
  val token=BleDiagnostics.begin(address)
  listOf("Services discovered","Requesting new MTU...","Failed to negotiate MTU, disconnecting...",
   "Enabling notifications for da2e7828-fbce-4e01-ae9e-261174997c48","Authentication required (5)","Notifications enabled").forEach{NordicGattTrace.capture(token,it)}
  val events=BleDiagnostics.snapshot(address).drop(1)
  assertEquals(listOf("SERVICES_DISCOVERED","MTU_REQUESTED","MTU_FAILED","NOTIFICATIONS_REQUESTED","AUTHENTICATION_REQUIRED","NOTIFICATIONS_ENABLED"),events.map{it["phase"]})
  assertEquals(5,events[4]["status"])
 }
 @Test fun keepsOnlyBoundedNegotiatedMtu() {
  val token=BleDiagnostics.begin(address)
  NordicGattTrace.capture(token,"MTU changed to: 247")
  assertEquals("MTU_NEGOTIATED",BleDiagnostics.snapshot(address).last()["phase"])
  assertEquals(247,BleDiagnostics.snapshot(address).last()["mtu"])
  val count=BleDiagnostics.snapshot(address).size
  listOf("MTU changed to: 9999999999999999999999","MTU changed to: 0","MTU changed to: 999").forEach{NordicGattTrace.capture(token,it)}
  assertEquals(count,BleDiagnostics.snapshot(address).size)
 }
 @Test fun neverStoresCredentialsPayloadsOrArbitraryExceptionText() {
  val token=BleDiagnostics.begin(address)
  listOf("[Broadcast] PAIRING_REQUEST key=123456","Received CBOR {password: secret}","MTU changed to: 247 secret",
   "Authentication required (5) private","Enabling notifications for private","Services discovered private",
   "[Callback] Connection state changed with status: 22 and new state: 0 (SECRET)").forEach{NordicGattTrace.capture(token,it)}
  assertEquals(listOf("attempt_started"),BleDiagnostics.snapshot(address).map{it["event"]})
 }
 @Test fun staleNativeCallbacksCannotContaminateAnotherAttempt() {
  val old=BleDiagnostics.begin(address);val current=BleDiagnostics.begin(address)
  NordicGattTrace.capture(old,"Failed to negotiate MTU, disconnecting...")
  NordicGattTrace.capture(current,"Services discovered")
  assertEquals(listOf("attempt_started","native_gatt"),BleDiagnostics.snapshot(address).map{it["event"]})
  assertEquals("SERVICES_DISCOVERED",BleDiagnostics.snapshot(address).last()["phase"])
 }
}
