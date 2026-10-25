package org.openvimar.updater.ble

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

class BlePreparationTest {
 private val address="AA:BB:CC:DD:EE:FF"
 private class Fake:PairingPlatform<String> {
  var state=BondState.NONE;var available=true;var permission=true;var accepted=true
  var nearby=listOf<String>(); override fun nearbySmpAddresses()=nearby
  var scans=0;var stops=0;var observers=0;var removed=0;var creates=0
  var scan:((Result<DiscoveredPeer<String>>)->Unit)?=null
  var bond:((Result<BondEvent>)->Unit)?=null
  override fun checkAvailable(){check(permission){"Permessi Bluetooth mancanti"};check(available){"Bluetooth spento"}}
  override fun startScan(address:String,onResult:(Result<DiscoveredPeer<String>>)->Unit):AutoCloseable{checkAvailable();scans++;scan=onResult;return AutoCloseable{stops++}}
  override fun bondState(peer:String)=state
  override fun observeBond(peer:String,onState:(Result<BondEvent>)->Unit):AutoCloseable{observers++;bond=onState;return AutoCloseable{removed++}}
  override fun createBond(peer:String):Boolean{creates++;return accepted}
  fun found(mac:String= "AA:BB:CC:DD:EE:FF"){scan!!(Result.success(DiscoveredPeer(mac,"peer")))}
  fun changed(next:BondState,mac:String="AA:BB:CC:DD:EE:FF"){state=next;bond!!(Result.success(BondEvent(mac,next)))}
 }
 private suspend fun rejected(block:suspend()->Unit):String {try{block();fail("expected failure")}catch(e:IllegalStateException){return e.message!!};error("unreachable")}
 @Test fun firstUseDiscoversExactMacThenWaitsForBond()=runBlocking {
  val f=Fake();val p=BlePreparation(f,1000,1000);val task=async{p.prepare(address)};yield()
  f.found("11:22:33:44:55:66");yield();assertEquals(0,f.creates);assertFalse(task.isCompleted)
  f.found();yield();assertEquals(1,f.stops);assertEquals(1,f.creates);assertFalse(task.isCompleted)
  f.changed(BondState.BONDED,"11:22:33:44:55:66");yield();assertFalse(task.isCompleted)
  f.changed(BondState.BONDED);assertEquals("peer",task.await());assertEquals(1,f.removed)
 }
 @Test fun alreadyBondedStillRequiresDiscovery()=runBlocking {val f=Fake();f.state=BondState.BONDED;val task=async{BlePreparation(f,1000,1000).prepare(address)};yield();assertFalse(task.isCompleted);f.found();assertEquals("peer",task.await());assertEquals(0,f.creates);assertEquals(0,f.observers)}
 @Test fun bondingDoesNotRestartPairing()=runBlocking {val f=Fake();f.state=BondState.BONDING;val task=async{BlePreparation(f,1000,1000).prepare(address)};yield();f.found();yield();assertEquals(0,f.creates);f.changed(BondState.BONDED);task.await();assertEquals(1,f.removed)}
 @Test fun rejectedCreateBondIsExplicit()=runBlocking {val f=Fake();f.accepted=false;val task=async{rejected{BlePreparation(f,1000,1000).prepare(address)}};yield();f.found();assertTrue(task.await().contains("did not start"));assertEquals(1,f.removed)}
 @Test fun bondNoneIsFailure()=runBlocking {val f=Fake();val task=async{rejected{BlePreparation(f,1000,1000).prepare(address)}};yield();f.found();yield();f.changed(BondState.NONE);assertTrue(task.await().contains("pairing failed"));assertEquals(1,f.removed)}
 @Test fun scanTimeoutStopsOnlyOwnedScan()=runBlocking {val f=Fake();assertTrue(rejected{BlePreparation(f,15,1000).prepare(address)}.contains("not reachable"));assertEquals(1,f.stops)}
 @Test fun bondTimeoutRemovesObserver()=runBlocking {val f=Fake();val task=async{rejected{BlePreparation(f,1000,15).prepare(address)}};yield();f.found();assertTrue(task.await().contains("timed out"));assertEquals(1,f.removed)}
 @Test fun cancelDuringScanCleansUp()=runBlocking {val f=Fake();val task=launch{BlePreparation(f,1000,1000).prepare(address)};yield();task.cancelAndJoin();assertEquals(1,f.stops)}
 @Test fun closeDuringBondCleansUpWithoutBondRemoval()=runBlocking {val f=Fake();val p=BlePreparation(f,1000,1000);val task=launch{p.prepare(address)};yield();f.found();yield();p.close();task.join();assertTrue(task.isCancelled);assertEquals(1,f.removed);assertEquals(1,f.stops)}
 @Test fun bluetoothOffAndPermissionsFailBeforeScan()=runBlocking {for(permission in listOf(true,false)){val f=Fake();f.permission=permission;f.available=false;val message=rejected{BlePreparation(f,1000,1000).prepare(address)};assertTrue(message.contains(if(permission)"spento" else "Permessi"));assertEquals(0,f.scans)}}
 @Test fun scanFailureAndPermissionRaceCleanUp()=runBlocking {val f=Fake();val task=async{rejected{BlePreparation(f,1000,1000).prepare(address)}};yield();f.scan!!(Result.failure(IllegalStateException("Scansione fallita")));assertEquals("Scansione fallita",task.await());assertEquals(1,f.stops)}
 @Test fun permissionLossAfterDiscoveryDoesNotStartBond()=runBlocking {val f=Fake();val task=async{rejected{BlePreparation(f,1000,1000).prepare(address)}};yield();f.permission=false;f.found();assertTrue(task.await().contains("Permessi"));assertEquals(1,f.stops);assertEquals(0,f.creates)}
 @Test fun bondPlatformFailureRemovesReceiver()=runBlocking {val f=Fake();val task=async{rejected{BlePreparation(f,1000,1000).prepare(address)}};yield();f.found();yield();f.bond!!(Result.failure(IllegalStateException("Bluetooth spento")));assertEquals("Bluetooth spento",task.await());assertEquals(1,f.removed)}
 @Test fun lateScanCallbacksCannotRestartBond()=runBlocking {val f=Fake();f.state=BondState.BONDED;val task=async{BlePreparation(f,1000,1000).prepare(address)};yield();f.found();task.await();f.found();assertEquals(0,f.creates);assertEquals(1,f.stops)}
 @Test fun missingExpectedPeerReportsNearbySmpButNeverSelectsIt()=runBlocking {
  val f=Fake();f.nearby=listOf("11:22:33:44:55:66")
  val task=async{rejected{BlePreparation(f,30,1000).prepare(address)}};yield()
  f.found("11:22:33:44:55:66")
  val message=task.await();assertTrue(message.contains(address));assertTrue(message.contains("11:22:33:44:55:66"));assertEquals(0,f.creates);assertEquals(0,f.observers);assertEquals(1,f.stops)
 }
 @Test fun leFirstObservesBeforeGattAndNeverCreatesBond()=runBlocking {
  val f=Fake();val task=async{BlePreparation(f,1000,1000).connectLeFirst(address){peer ->
   assertEquals("peer",peer);assertEquals(1,f.observers);assertEquals(0,f.creates)
   f.changed(BondState.BONDING);f.changed(BondState.BONDED)
  }};yield();f.found();assertEquals("peer",task.await());assertEquals(0,f.creates);assertEquals(1,f.removed)
 }
 @Test fun leFirstWaitsForLateBondBeforeAuthorizingSmp()=runBlocking {
  val f=Fake();var initialized=false;var authorized=false
  val task=async{BlePreparation(f,1000,1000).connectLeFirst(address){initialized=true};authorized=true};yield();f.found();yield()
  assertTrue(initialized);assertFalse(authorized);assertEquals(0,f.creates)
  f.changed(BondState.BONDED);task.await();assertTrue(authorized)
 }
 @Test fun leFirstBondFailureDoesNotAuthorizeSmp()=runBlocking {
  val f=Fake();val task=async{rejected{BlePreparation(f,1000,1000).connectLeFirst(address){f.changed(BondState.BONDING);f.changed(BondState.NONE)}}};yield();f.found()
  assertTrue(task.await().contains("pairing failed"));assertEquals(0,f.creates);assertEquals(1,f.removed)
 }
 @Test fun leFirstInitializationFailureRemovesBondObserver()=runBlocking {
  val f=Fake();val task=async{rejected{BlePreparation(f,1000,1000).connectLeFirst(address){error("GATT unavailable")}}};yield();f.found()
  assertEquals("GATT unavailable",task.await());assertEquals(1,f.removed)
 }
 @Test fun leFirstCancellationDuringInitializeCleansObservers()=runBlocking {
  val f=Fake();val policy=BlePreparation(f,1000,1000)
  val task=launch{policy.connectLeFirst(address){awaitCancellation()}};yield();f.found();yield();policy.close();task.join()
  assertTrue(task.isCancelled);assertEquals(1,f.removed);assertEquals(1,f.stops);assertEquals(0,f.creates)
 }
 @Test fun leFirstAlreadyBondedStillInitializesGatt()=runBlocking {
  val f=Fake();f.state=BondState.BONDED;var initialized=false
  val task=async{BlePreparation(f,1000,1000).connectLeFirst(address){initialized=true}};yield();f.found();task.await()
  assertTrue(initialized);assertEquals(0,f.creates);assertEquals(1,f.observers);assertEquals(1,f.removed)
 }
 @Test fun leFirstHardBondFailureInterruptsInitializationWithCause()=runBlocking {
  val f=Fake();var cancelled=false
  val task=async{rejected{BlePreparation(f,1000,1000).connectLeFirst(address){
   try{f.changed(BondState.BONDING);f.changed(BondState.NONE);awaitCancellation()}finally{cancelled=true}
  }}};yield();f.found()
  assertTrue(task.await().contains("pairing failed"));assertTrue(cancelled);assertEquals(1,f.removed);assertEquals(0,f.creates)
 }
 @Test fun leFirstPassiveBondTimeoutNeverCreatesBond()=runBlocking {
  val f=Fake();val task=async{rejected{BlePreparation(f,1000,15).connectLeFirst(address){}}};yield();f.found()
  assertTrue(task.await().contains("timed out"));assertEquals(0,f.creates);assertEquals(1,f.removed)
 }
}
