package org.openvimar.updater.core

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class ZigbeePairingTest {
 private val address="AA:BB:CC:DD:EE:FF"
 private class Radio:BleTransport,ZigbeePairingTransport {
  var id=RuntimeIdentity(1,"VIMAR30805",2,listOf("11223344","55667788"),"ab".repeat(32))
  var requests=0;var closed=0;var unsupported=false;var ack=ResetAck.ACKNOWLEDGED
  override suspend fun connect(address:String){}
  override suspend fun identityV2():RuntimeIdentity=throw IdentityCommandUnavailable()
  override suspend fun identity()=id
  override suspend fun pairingCapabilities():ZigbeePairingCapabilities {
   if(unsupported)error("Unsupported pairing command")
   return ZigbeePairingCapabilities(1,120,true)
  }
  override suspend fun startZigbeePairing():ResetAck {requests++;return ack}
  override suspend fun images():RemoteImages=error("No image operation")
  override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit)=error("No upload")
  override suspend fun reset():ResetAck=error("No reset fallback")
  override suspend fun close(){closed++}
 }
 @Test fun inspectionOnlyReadsAndExecutionConsumesOneFreshReview()=runBlocking {
  val r=Radio();val review=ZigbeePairing.inspect(r,address,r.id.uid)
  assertEquals(0,r.requests)
  assertEquals(ResetAck.ACKNOWLEDGED,ZigbeePairing.execute(review,r){assertEquals(0,r.requests)})
  assertEquals(1,r.requests)
  try{ZigbeePairing.execute(review,r){};fail("Replayed review")}catch(_:IllegalStateException){}
  assertEquals(1,r.requests)
 }
 @Test fun changedIdentityAndMissingCapabilityCannotRequestPairing()=runBlocking {
  val r=Radio();val review=ZigbeePairing.inspect(r,address,r.id.uid)
  r.id=r.id.copy(uid=listOf("11223344","00000000"))
  try{ZigbeePairing.execute(review,r){};fail("Changed identity")}catch(_:IllegalArgumentException){}
  assertEquals(0,r.requests)
  r.unsupported=true
  try{ZigbeePairing.inspect(r,address);fail("Unsupported command")}catch(_:IllegalStateException){}
  assertEquals(0,r.requests)
 }
 @Test fun lostAcknowledgmentIsNotRetriedAndNoOrdinaryResetIsUsed()=runBlocking {
  val r=Radio();r.ack=ResetAck.LOST
  val review=ZigbeePairing.inspect(r,address)
  assertEquals(ResetAck.LOST,ZigbeePairing.execute(review,r){})
  assertEquals(1,r.requests)
 }
 @Test fun failedDurableIntentPreventsTheRequest()=runBlocking {
  val r=Radio();val review=ZigbeePairing.inspect(r,address)
  try{ZigbeePairing.execute(review,r){error("Storage unavailable")};fail("No durable report")}catch(_:IllegalStateException){}
  assertEquals(0,r.requests)
 }
 @Test fun reviewCanBeRevokedWithoutAnyDeviceMutation()=runBlocking {
  val r=Radio();val review=ZigbeePairing.inspect(r,address);review.close()
  try{ZigbeePairing.execute(review,r){};fail("Revoked review")}catch(_:IllegalStateException){}
  assertEquals(0,r.requests)
 }
}
