package org.openvimar.updater

import java.nio.file.Files
import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.*

class BootHistoryReportStoreTest {
 private val address="AA:BB:CC:DD:EE:FF"
 private fun report(id:String,state:BootHistoryReadState,address:String=this.address)=BootHistoryDiagnosticReport(id,address,null,state,50L,if(state==BootHistoryReadState.READING)null else 100L,null)
 @Test fun laterFailedDeviceCannotExportPreviousSuccessfulOrInProgressAttempt() {
  val folder=Files.createTempDirectory("history-store").toFile();val store=BootHistoryReportStore(folder)
  val identity=RuntimeIdentity(1,"VIMAR30805",2,listOf("11223344","ffffffff"),"ab".repeat(32))
  val history=RecoveryBootHistory(sequence=1,pendingReason=0,state=BootHistoryState(true,true,true,0,0,0,0),entries=emptyList())
  store.save(report("A",BootHistoryReadState.READING));store.save(report("A",BootHistoryReadState.COMPLETE).copy(observation=BootHistoryObservation(address,identity,history,100)))
  store.save(report("B",BootHistoryReadState.READING,"11:22:33:44:55:66"));store.save(report("B",BootHistoryReadState.FAILED,"11:22:33:44:55:66"))
  val saved=BootHistoryReports.decode(requireNotNull(store.selectedBytes()))
  assertEquals("B",saved.attemptId);assertEquals("11:22:33:44:55:66",saved.address);assertEquals(BootHistoryReadState.FAILED,saved.state);assertNull(saved.observation)
  store.deselect();assertNull(store.selectedBytes());assertEquals("B",store.latest()?.attemptId)
  val reopened=BootHistoryReportStore(folder);assertNull(reopened.selectedBytes());assertEquals("B",reopened.latest()?.attemptId)
 }
 @Test fun delayedCompletionOfOlderAttemptCannotReplaceNewerDeviceReport() {
  val store=BootHistoryReportStore(Files.createTempDirectory("history-owner").toFile())
  store.save(report("A",BootHistoryReadState.READING));store.save(report("B",BootHistoryReadState.READING))
  assertThrows(IllegalStateException::class.java){store.save(report("A",BootHistoryReadState.CANCELLED))}
  assertEquals("B",BootHistoryReports.decode(requireNotNull(store.selectedBytes())).attemptId)
 }
}
