package org.openvimar.updater.core

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test

class RecoveryBootHistoryTest {
 private val address="AA:BB:CC:DD:EE:FF"
 private val identity=RuntimeIdentity(1,"VIMAR30805",2,listOf("11223344","ffffffff"),"ab".repeat(32))
 private fun history()=RecoveryBootHistory(sequence=0xffffffffL,pendingReason=0,state=BootHistoryState(true,true,true,0,-2,0,0),entries=listOf(BootHistoryEntry(0xffffffffL,1,3,0xffffffffL)))
 private inner class Radio:BootHistoryTransport {
  val calls=mutableListOf<String>();var second=identity;var histories=0;var read:suspend()->RecoveryBootHistory={history()}
  override suspend fun identityV2():RuntimeIdentity {calls+="identity";return if(calls.count{it=="identity"}==1)identity else second}
  override suspend fun bootHistory():RecoveryBootHistory {calls+="history";histories++;return read()}
  override suspend fun identity():RuntimeIdentity=error("Unexpected legacy fallback")
  override suspend fun connect(address:String)=error("Collector must not create a radio owner")
  override suspend fun images():RemoteImages=error("No image query required")
  override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit)=error("Diagnostic must never upload")
  override suspend fun reset():ResetAck=error("Diagnostic must never reset")
  override suspend fun close()=Unit
 }
 @Test fun readsIdentityAroundHistoryAndPinsExpectedUidWithoutUpdatePackage()=runBlocking {
  val radio=Radio();val observed=BootHistoryDiagnostic.read(address,radio,identity.uid,now={100L})
  assertEquals(listOf("identity","history","identity"),radio.calls)
  assertEquals(identity,observed.identity);assertEquals(history(),observed.history);assertEquals(100L,observed.observedAtMillis)
 }
 @Test fun wrongExpectedUidStopsBeforeHistoryRead()=runBlocking {
  val radio=Radio();var rejected=false
  try{BootHistoryDiagnostic.read(address,radio,listOf("00000000","00000001"))}catch(_:IllegalArgumentException){rejected=true}
  assertTrue(rejected);assertEquals(0,radio.histories)
 }
 @Test fun fullLoaderIdentityChangeRejectsSameUidHistory()=runBlocking {
  val radio=Radio();radio.second=identity.copy(loaderSha256="cd".repeat(32));var rejected=false
  try{BootHistoryDiagnostic.read(address,radio)}catch(_:IllegalArgumentException){rejected=true}
  assertTrue(rejected);assertEquals(listOf("identity","history","identity"),radio.calls)
 }
 @Test fun cancellationCannotPublishAnObservationOrContinueIdentityRead()=runBlocking {
  val radio=Radio();val entered=CompletableDeferred<Unit>();radio.read={entered.complete(Unit);awaitCancellation()}
  var published=false;val job=launch{BootHistoryDiagnostic.read(address,radio);published=true}
  entered.await();job.cancelAndJoin();assertFalse(published);assertEquals(listOf("identity","history"),radio.calls)
 }
 @Test fun exportRoundTripRetainsFullIdentityAndRawBoundedMetadata() {
  val observation=BootHistoryObservation(address,identity,history(),100L)
  val report=BootHistoryDiagnosticReport("attempt-1",address,identity.uid,BootHistoryReadState.COMPLETE,50L,100L,observation)
  val bytes=BootHistoryReports.encode(report);assertTrue(bytes.size<8192)
  assertEquals(report,BootHistoryReports.decode(bytes))
  assertTrue(bytes.toString(Charsets.UTF_8).contains("Raw observations"))
 }
 @Test fun invalidOrOversizedPersistedReportsCannotBecomeValidatedHistory() {
  val observation=BootHistoryObservation(address,identity,history(),100L)
  val report=BootHistoryDiagnosticReport("attempt-1",address,null,BootHistoryReadState.COMPLETE,50L,100L,observation)
  assertThrows(IllegalArgumentException::class.java){BootHistoryReports.encode(report.copy(observation=observation.copy(history=history().copy(entries=List(7){history().entries[0]}))))}
  assertThrows(IllegalArgumentException::class.java){BootHistoryReports.decode(ByteArray(32769))}
  val json=BootHistoryReports.encode(report).toString(Charsets.UTF_8).replace("4294967295","true")
  assertThrows(Exception::class.java){BootHistoryReports.decode(json.toByteArray())}
 }
}
