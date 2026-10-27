package org.openvimar.updater.core

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class ZigbeePairingTest {
 private val address="AA:BB:CC:DD:EE:FF"
 private class Radio:BleTransport,ZigbeePairingTransport {
  var id=RuntimeIdentity(1,"VIMAR30805",2,listOf("11223344","55667788"),"ab".repeat(32))
  var requests=0;var closed=0;var unsupported=false;var ack=ResetAck.ACKNOWLEDGED
  var connectFailure:Exception?=null;var requestFailure:Exception?=null
  var capabilityReads=0
  val connections=mutableListOf<String>()
  val events=mutableListOf<String>()
  override suspend fun connect(address:String){connections+=address;events+="connect";connectFailure?.let{throw it}}
  override suspend fun identityV2():RuntimeIdentity=throw IdentityCommandUnavailable()
  override suspend fun identity():RuntimeIdentity {events+="identity";return id}
  override suspend fun pairingCapabilities():ZigbeePairingCapabilities {
   capabilityReads++;events+="capability"
   if(unsupported)error("Unsupported pairing command")
   return ZigbeePairingCapabilities(1,120,true)
  }
  override suspend fun startZigbeePairing():ResetAck {requests++;events+="request";requestFailure?.let{throw it};return ack}
  override suspend fun images():RemoteImages=error("No image operation")
  override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit)=error("No upload")
  override suspend fun reset():ResetAck=error("No reset fallback")
  override suspend fun close(){closed++;events+="close"}
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

 @Test fun pairingRequiresTheSelectedUidAndValidIdentityBeforeCapabilityDiscovery()=runBlocking {
  for(invalidIdentity in listOf(false,true)){
   val r=Radio()
   if(invalidIdentity)r.id=r.id.copy(model="foreign-model")
   var refused=false
   try{ZigbeePairing.inspect(r,address,listOf("00000000","11111111"))}catch(_:IllegalArgumentException){refused=true}
   assertTrue(refused);assertEquals(0,r.capabilityReads);assertEquals(0,r.requests)
   assertEquals(listOf(address),r.connections);assertEquals(1,r.closed)
  }
 }
 @Test fun plainBleTransportCannotOfferPairingOrExecuteAnExistingReview()=runBlocking {
  val r=Radio()
  val plain=object:BleTransport by r {}
  var refused=false
  try{ZigbeePairing.inspect(plain,address)}catch(_:IllegalStateException){refused=true}
  assertTrue(refused);assertEquals(1,r.closed);assertEquals(0,r.requests)
  val review=ZigbeePairing.inspect(r,address)
  refused=false;var persisted=false
  try{ZigbeePairing.execute(review,plain){persisted=true}}catch(_:IllegalStateException){refused=true}
  assertTrue(refused);assertFalse(persisted);assertEquals(3,r.closed);assertEquals(0,r.requests)
 }
 @Test fun pairingRevalidatesCapabilityAndConsumesReviewEvenIfItBecomesUnsupported()=runBlocking {
  val r=Radio();val review=ZigbeePairing.inspect(r,address);r.unsupported=true
  var persisted=false;var refused=false
  try{ZigbeePairing.execute(review,r){persisted=true}}catch(_:IllegalStateException){refused=true}
  assertTrue(refused);assertFalse(persisted);assertEquals(2,r.capabilityReads)
  assertEquals(0,r.requests);assertEquals(2,r.closed)
  r.unsupported=false
  refused=false
  try{ZigbeePairing.execute(review,r){persisted=true}}catch(_:IllegalStateException){refused=true}
  assertTrue(refused);assertFalse(persisted);assertEquals(2,r.connections.size)
 }
 @Test fun connectionFailureClosesTransportAndCannotLeaveAReusableApproval()=runBlocking {
  val r=Radio();val review=ZigbeePairing.inspect(r,address)
  r.connectFailure=TransportDisconnected("Connection refused")
  var refused=false;var persisted=false
  try{ZigbeePairing.execute(review,r){persisted=true}}catch(_:TransportDisconnected){refused=true}
  assertTrue(refused);assertFalse(persisted);assertEquals(2,r.closed);assertEquals(0,r.requests)
  r.connectFailure=null;refused=false
  try{ZigbeePairing.execute(review,r){persisted=true}}catch(_:IllegalStateException){refused=true}
  assertTrue(refused);assertFalse(persisted);assertEquals(2,r.connections.size)
 }
 @Test fun reviewCapturesAnImmutableIdentitySnapshotRatherThanAliasingTheRadioList()=runBlocking {
  val r=Radio();val reportedUid=mutableListOf("11223344","55667788");r.id=r.id.copy(uid=reportedUid)
  val review=ZigbeePairing.inspect(r,address)
  reportedUid[1]="00000000"
  assertEquals(listOf("11223344","55667788"),review.identity.uid)
  var refused=false
  try{ZigbeePairing.execute(review,r){fail("Changed identity must not persist intent")}}catch(_:IllegalArgumentException){refused=true}
  assertTrue(refused);assertEquals(0,r.requests);assertEquals(2,r.closed)
 }
 @Test fun mutationIntentIsPersistedAfterFreshIdentityAndCapabilityBeforeTheOnlyRequest()=runBlocking {
  val r=Radio();val review=ZigbeePairing.inspect(r,address)
  r.events.clear()
  ZigbeePairing.execute(review,r){r.events+="persist"}
  assertEquals(listOf("connect","identity","capability","persist","request","close"),r.events)
  assertEquals(listOf(address,address),r.connections)
 }
 @Test fun cancellationAtEitherSideOfSubmissionClosesTransportAndNeverReplaysReview()=runBlocking {
  for(afterSubmission in listOf(false,true)){
   val r=Radio();val review=ZigbeePairing.inspect(r,address)
   if(afterSubmission)r.requestFailure=CancellationException("Stopped after request")
   var cancelled=false
   try{ZigbeePairing.execute(review,r){if(!afterSubmission)throw CancellationException("Stopped during durable intent")}}
   catch(_:CancellationException){cancelled=true}
   assertTrue(cancelled);assertEquals(if(afterSubmission)1 else 0,r.requests);assertEquals(2,r.closed)
   r.requestFailure=null;var refused=false
   try{ZigbeePairing.execute(review,r){fail("Cancelled grant was replayed")}}catch(_:IllegalStateException){refused=true}
   assertTrue(refused);assertEquals(if(afterSubmission)1 else 0,r.requests)
   assertEquals(2,r.connections.size)
  }
 }
 @Test fun transportErrorAfterWriteDoesNotTriggerRetryOrOrdinaryReset()=runBlocking {
  val r=Radio();val review=ZigbeePairing.inspect(r,address)
  r.requestFailure=TransportDisconnected("Write outcome unknown")
  var failed=false
  try{ZigbeePairing.execute(review,r){}}catch(_:TransportDisconnected){failed=true}
  assertTrue(failed);assertEquals(1,r.requests);assertEquals(2,r.closed)
  r.requestFailure=null;var refused=false
  try{ZigbeePairing.execute(review,r){}}catch(_:IllegalStateException){refused=true}
  assertTrue(refused);assertEquals(1,r.requests);assertEquals(2,r.connections.size)
 }
 @Test fun onlyTheSupportedDestructiveWindowCanBeRepresentedAsACapability() {
  for(value in listOf(Triple(0,120,true),Triple(2,120,true),Triple(1,119,true),Triple(1,121,true),Triple(1,120,false))){
   assertThrows(IllegalArgumentException::class.java){ZigbeePairingCapabilities(value.first,value.second,value.third)}
  }
 }
}
