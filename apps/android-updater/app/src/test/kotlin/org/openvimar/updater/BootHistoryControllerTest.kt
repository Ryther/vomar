package org.openvimar.updater

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.*

class BootHistoryControllerTest {
 private val address="AA:BB:CC:DD:EE:FF"
 private val uid=listOf("11223344","ffffffff")
 private fun observation()=BootHistoryObservation(address,RuntimeIdentity(1,"VIMAR30805",2,uid,"ab".repeat(32)),RecoveryBootHistory(sequence=1,pendingReason=0,state=BootHistoryState(true,true,true,0,0,0,0),entries=listOf(BootHistoryEntry(1,1,3,0))),System.currentTimeMillis())
 private inner class Harness {
  val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
  val reports=mutableListOf<BootHistoryDiagnosticReport>();val selections=mutableListOf<Boolean>();var packageReads=0
  var read:suspend(String,List<String>?,()->Unit)->BootHistoryObservation={a,pin,check->assertEquals(address,a);assertEquals(uid,pin);check();observation()}
  val controller=SessionController(scope,object:SessionStore {
   override suspend fun load(bundleDigest:String,address:String):Checkpoint?=error("No update checkpoint read allowed")
   override suspend fun save(checkpoint:Checkpoint)=error("No update checkpoint write allowed")
  },{packageReads++;null},{null},{_,_,_->error("No package import")},{error("No update transport")},{_,_,_->error("No update report")},{byteArrayOf()},{true},
   bootHistoryInspector={a,pin,check->read(a,pin,check)},bootHistoryReportWriter={reports+=it},diagnosticReportSelection={selections+=it})
 }
 @Test fun standaloneDiagnosticRequiresNoZipAndPublishesImmutableExactSnapshot()=runBlocking {
  val h=Harness();assertTrue(h.controller.inspectBootHistory(address,uid));h.controller.awaitIdle()
  assertEquals(0,h.packageReads);assertEquals(listOf(BootHistoryReadState.READING,BootHistoryReadState.COMPLETE),h.reports.map{it.state})
  val snapshot=requireNotNull(h.controller.reportedBootHistory.value);assertEquals(address,snapshot.address);assertEquals(uid,snapshot.identity.uid)
  val original=snapshot.reportBytes();val damaged=snapshot.reportBytes();damaged[0]=0
  assertArrayEquals(original,snapshot.reportBytes());assertTrue(snapshot.summary.contains("do not prove"));assertFalse(h.controller.busy.value)
  assertThrows(UnsupportedOperationException::class.java){(snapshot.identity.uid as MutableList<String>)[0]="00000000"}
  assertThrows(UnsupportedOperationException::class.java){(snapshot.history.entries as MutableList<BootHistoryEntry>).clear()}
  assertEquals(address,h.controller.lastBootHistoryAddress)
  assertEquals(BootHistoryReadState.COMPLETE,BootHistoryReports.decode(original).state);h.scope.cancel()
 }
 @Test fun unsupportedNewAttemptPersistsItsOwnFailureWithoutPreviousObservation()=runBlocking {
  val h=Harness();h.controller.inspectBootHistory(address,uid);h.controller.awaitIdle();assertNotNull(h.controller.reportedBootHistory.value)
  h.read={_,_,_->throw BootHistoryUnavailable()};h.controller.inspectBootHistory(address,uid);h.controller.awaitIdle()
  assertNull(h.controller.reportedBootHistory.value);assertEquals(BootHistoryReadState.UNSUPPORTED,h.reports.last().state);assertNull(h.reports.last().observation)
  assertTrue(h.controller.status.value.contains("unsupported"));assertNotEquals(h.reports[0].attemptId,h.reports.last().attemptId);h.scope.cancel()
 }
 @Test fun cancellationDrainsInspectionAndPersistsCancelledAttemptBeforeAnotherOwner()=runBlocking {
  val h=Harness();val entered=CompletableDeferred<Unit>();val ended=CompletableDeferred<Unit>()
  h.read={_,_,_->entered.complete(Unit);try{awaitCancellation()}finally{ended.complete(Unit)}}
  assertTrue(h.controller.inspectBootHistory(address,uid));entered.await()
  assertEquals(SessionOperation.INSPECT,h.controller.presentation.value.operation);assertFalse(h.controller.inspectBootHistory(address,uid))
  h.controller.stop();h.controller.awaitIdle();assertTrue(ended.isCompleted);assertNull(h.controller.reportedBootHistory.value)
  assertEquals(BootHistoryReadState.CANCELLED,h.reports.last().state);assertFalse(h.controller.running);h.scope.cancel()
 }
 @Test fun newerOtherOperationDeselectedHistoryEvenWhenThatOperationFails()=runBlocking {
  val h=Harness();h.controller.inspectBootHistory(address,uid);h.controller.awaitIdle();assertTrue(h.controller.start(false));h.controller.awaitIdle()
  assertEquals(false,h.selections.last());assertEquals(BootHistoryReadState.COMPLETE,h.reports.last().state);h.scope.cancel()
  assertNull(h.controller.lastBootHistoryAddress)
 }
 @Test fun unrelatedPresentationErrorCannotReplaceTheCorrelatedHistoryMessage()=runBlocking {
  val h=Harness();h.read={_,_,_->throw BootHistoryUnavailable()}
  h.controller.inspectBootHistory(address,uid);h.controller.awaitIdle()
  val message=h.controller.lastBootHistoryMessage;assertTrue(requireNotNull(message).contains("unsupported"))
  h.controller.notifyFailure("Unrelated export failure")
  assertNotEquals(message,h.controller.status.value);assertEquals(message,h.controller.lastBootHistoryMessage)
  h.controller.inspect();h.controller.awaitIdle();assertEquals(message,h.controller.lastBootHistoryMessage)
  h.controller.start(false);h.controller.awaitIdle();assertNull(h.controller.lastBootHistoryMessage);h.scope.cancel()
 }
}
