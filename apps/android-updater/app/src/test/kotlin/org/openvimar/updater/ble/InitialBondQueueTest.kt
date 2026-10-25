package org.openvimar.updater.ble

import org.junit.Assert.*
import org.junit.Test

class InitialBondQueueTest {
 @Test fun unbondedPeerGetsBondBeforeProtectedSmpInitialization() {
  val queue=InitialBondQueue().prepare(BondState.NONE){"system-bond"}
  assertNotNull(queue)
  // Pinned Nordic2.11 initGatt creates this queue before McuMgr appends its
  // MTU/CCC requests; the returned request must precede those requests.
  queue!!.addLast("mtu");queue.addLast("protected-ccc")
  assertEquals(listOf("system-bond","mtu","protected-ccc"),queue.toList())
 }
 @Test fun neverRemovesOrRecreatesExistingBond() {
  assertNull(InitialBondQueue().prepare(BondState.BONDED){error("Must not replace the bond")})
 }
 @Test fun inProgressSystemPairingDoesNotGetASecondRequest() {
  assertNull(InitialBondQueue().prepare(BondState.BONDING){error("Must not restart pairing")})
 }
 @Test fun rediscoveryCannotStartAnAutomaticPairingRetry() {
  val policy=InitialBondQueue();assertNotNull(policy.prepare(BondState.NONE){"first"})
  assertNull(policy.prepare(BondState.NONE){error("Must not automatically retry pairing")})
 }
}
