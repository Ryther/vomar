package org.openvimar.updater.ble
import kotlinx.coroutines.*
import org.junit.Test
import org.junit.Assert.*
import org.openvimar.updater.core.*
class NordicBleTransportTest {
 private val address="AA:BB:CC:DD:EE:FF"
 private class Fake:BleGateway {
  var healthy=true; var released=false; var offsets=mutableListOf(4); val sent=mutableListOf<Int>(); var rows=listOf(Slot(0,1,"ab",true,true)); var resetFailure:Exception?=null; var mismatch=false
  var historyCalls=0
  var historyRead:suspend()->RecoveryBootHistory={RecoveryBootHistory(sequence=1,pendingReason=0,state=BootHistoryState(true,true,true,0,0,0,0),entries=emptyList())}
  override suspend fun connect(address:String){}; override fun checkReady(){check(healthy)}
  override suspend fun images()=rows
  override suspend fun chunk(data:ByteArray,offset:Int,image:Int):Chunk { assertEquals(0,image); sent+=offset; return Chunk(offsets.removeAt(0),if(mismatch)false else null) }
  override suspend fun reset(){resetFailure?.let{throw it}}
  override suspend fun bootHistory():RecoveryBootHistory{historyCalls++;return historyRead()}
  override fun close(){released=true}
 }
 private suspend fun fails(block:suspend()->Unit){try{block();fail("expected failure")}catch(e:IllegalStateException){}}
 @Test fun rejectsSameNameDifferentAddress()=runBlocking { val f=Fake(); fails{NordicBleTransport(address,f).connect("11:22:33:44:55:66")} }
 @Test fun requiresActiveRecoverySlot1()=runBlocking {val f=Fake(); f.rows=listOf(Slot(0,1,"ab",false,true)); fails{NordicBleTransport(address,f).images()} }
 @Test fun rejectsForeignAndDuplicateIndices()=runBlocking {for(rows in listOf(listOf(Slot(1,1,"ab",true,true)),listOf(Slot(0,1,"ab",true,true),Slot(0,1,"ab",true,true)))){val f=Fake();f.rows=rows;fails{NordicBleTransport(address,f).images()}}}
 @Test fun stopsOnBondOrPermissionLoss()=runBlocking {val f=Fake();f.healthy=false;fails{NordicBleTransport(address,f).upload(ByteArray(4)) {}};assertTrue(f.sent.isEmpty())}
 @Test fun usesImage0NotSlot1()=runBlocking {val f=Fake();NordicBleTransport(address,f).upload(ByteArray(4)){};assertEquals(listOf(0),f.sent)}
 @Test fun usesReportedOffset()=runBlocking {val f=Fake();f.offsets=mutableListOf(2,4);val ack=mutableListOf<Int>();NordicBleTransport(address,f).upload(ByteArray(4)){ack+=it;assertEquals(ack.size,f.sent.size)};assertEquals(listOf(0,2),f.sent);assertEquals(listOf(2,4),ack)}
 @Test fun rejectsOffsetOutsideFile()=runBlocking {val f=Fake();f.offsets=mutableListOf(5);fails{NordicBleTransport(address,f).upload(ByteArray(4)){}}}
 @Test fun pausesAfterThreeNonProgressAcks()=runBlocking {val f=Fake();f.offsets=mutableListOf(0,0,0);fails{NordicBleTransport(address,f).upload(ByteArray(4)){}};assertEquals(3,f.sent.size)}
 @Test fun rejectsBackwardOffsetAfterNegotiation()=runBlocking {val f=Fake();f.offsets=mutableListOf(2,1);fails{NordicBleTransport(address,f).upload(ByteArray(4)){}}}
 @Test fun resetErrorIsNotSuccess()=runBlocking {val f=Fake();f.resetFailure=IllegalStateException("group error");fails{NordicBleTransport(address,f).reset()}}
 @Test fun cancelReleasesOnlyCurrentConnection()=runBlocking {val f=Fake();val other=Fake();try{NordicBleTransport(address,f).upload(ByteArray(4)){throw CancellationException()}}catch(_:CancellationException){};assertTrue(f.released);assertFalse(other.released)}
 @Test fun rejectsDeviceHashMismatch()=runBlocking {val f=Fake();f.mismatch=true;fails{NordicBleTransport(address,f).upload(ByteArray(4)){fail("must not persist mismatch")}}}
 @Test fun resetDisconnectIsAmbiguous()=runBlocking {val f=Fake();f.resetFailure=TransportDisconnected();assertEquals(ResetAck.LOST,NordicBleTransport(address,f).reset())}
 @Test fun ackFailurePreventsNextChunk()=runBlocking {val f=Fake();f.offsets=mutableListOf(2,4);fails{NordicBleTransport(address,f).upload(ByteArray(4)){error("disk full")}};assertEquals(listOf(0),f.sent)}
 @Test fun preservesReportedImageVersionAsObservationWithoutInventingOne()=runBlocking {
  val f=Fake();f.rows=listOf(Slot(0,0,"main",false,true,"0.7.3"),Slot(0,1,"recovery",true,true))
  val observed=NordicBleTransport(address,f).images();assertEquals("0.7.3",observed.primary!!.version);assertNull(observed.recovery.version)
 }
 @Test fun normalReadUploadAndResetNeverQueryBootHistoryAutomatically()=runBlocking {
  val f=Fake();val transport=NordicBleTransport(address,f)
  transport.connect(address);transport.images();transport.upload(ByteArray(4)){};transport.reset()
  assertEquals(0,f.historyCalls)
 }
 @Test fun explicitHistoryReadChecksBondAndCancellationReleasesItsOwner()=runBlocking {
  val f=Fake();f.healthy=false;fails{NordicBleTransport(address,f).bootHistory()};assertEquals(0,f.historyCalls)
  f.healthy=true;val entered=CompletableDeferred<Unit>();f.historyRead={entered.complete(Unit);awaitCancellation()}
  val job=launch{NordicBleTransport(address,f).bootHistory()};entered.await();job.cancelAndJoin();assertTrue(f.released)
  assertTrue(f.sent.isEmpty())
 }
}
