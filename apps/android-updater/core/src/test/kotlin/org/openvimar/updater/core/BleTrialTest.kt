package org.openvimar.updater.core

import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.CancellationException
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class BleTrialTest {
 private val dir=File("../../../tools/android/test-fixtures/common-v3-candidate")
 private val bytes=File(dir,"qualification-candidate.zip").readBytes()
 private val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File(dir,"public.der").readBytes()))
 private val entries=java.util.zip.ZipInputStream(bytes.inputStream()).use { zip->
  buildMap<String,ByteArray>{while(true){val entry=zip.nextEntry?:break;put(entry.name,zip.readBytes())}}
 }
 private val m=Json.parseToJsonElement(entries.getValue("manifest.json").toString(Charsets.UTF_8)).jsonObject
 private val address="AA:BB:CC:DD:EE:FF"
 private fun h(role:String)=m.getValue(role).jsonObject.getValue("signedRegionSha256").jsonPrimitive.content
 private fun candidate()=BleTrialCandidate.inspect(bytes,key,"0.6.1")
 private fun identity()=RuntimeIdentity(2,"VIMAR30805",2,listOf("11223344","55667788"),"",
  LoaderContract(LoaderContract.COMMON,m.getValue("loaderContracts").jsonArray[0].jsonObject.getValue("sha256").jsonPrimitive.content),"12".repeat(32))
 private inner class Radio(var legacy:Boolean=false):BleTransport,MigrationBootTransport {
  var id=this@BleTrialTest.identity();var identityFailure:Exception?=null;var closed=0;var writes=0;var resets=0
  var remote=RemoteImages(RemoteImage(m.getValue("allowedSourceSignedHashes").jsonArray[0].jsonPrimitive.content,false,true,"0.5.5"),
   RemoteImage(if(legacy)m.getValue("legacyRecoverySignedHashes").jsonArray[0].jsonPrimitive.content else h("recovery"),true,true,"old"))
  override suspend fun connect(address:String){}
  override suspend fun identityV2():RuntimeIdentity {identityFailure?.let{throw it};if(legacy)throw IdentityCommandUnavailable();return id}
  override suspend fun identity():RuntimeIdentity {if(legacy)throw IdentityCommandUnavailable();return id}
  override suspend fun images()=remote
  override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){writes++;onAck(data.size);remote=remote.copy(primary=RemoteImage(if(data.contentEquals(entries.getValue("migration.signed.bin")))h("migration")else h("main"),false,true))}
  override suspend fun bootMigration(expectedHash:String):ResetAck {assertEquals(h("migration"),expectedHash);resets++;legacy=false;remote=remote.copy(recovery=RemoteImage(h("recovery"),true,true));return ResetAck.ACKNOWLEDGED}
  override suspend fun reset():ResetAck {resets++;return ResetAck.ACKNOWLEDGED}
  override suspend fun close(){closed++}
 }
 private class States {
  var normal:Checkpoint?=null;var boot:BootstrapCheckpoint?=null;var saves=0
  val sessions=object:SessionStore { override suspend fun load(bundleDigest:String,address:String):Checkpoint?=normal; override suspend fun save(checkpoint:Checkpoint){normal=checkpoint;saves++} }
  val bootstrap=object:BootstrapStore { override suspend fun load(digest:String,address:String):BootstrapCheckpoint?=boot; override suspend fun save(checkpoint:BootstrapCheckpoint){boot=checkpoint;saves++} }
 }
 @Test fun candidateInspectionDoesNotPromoteItToNormalRelease(){val c=candidate();assertEquals("0.6.0",c.version);assertThrows(Exception::class.java){CommonPackageValidator.validate(CommonPackageReader.read(bytes.inputStream()),key,"0.6.1")}}
 @Test fun signatureTamperingIsRejected(){val damaged=bytes.copyOf();damaged[damaged.lastIndex/2]=(damaged[damaged.lastIndex/2].toInt() xor 1).toByte();assertThrows(Exception::class.java){BleTrialCandidate.inspect(damaged,key,"0.6.1")}}
 @Test fun readOnlyReviewDoesNotWriteOrReset()=runBlocking {val c=candidate();val r=Radio();val s=States();val review=c.review(address,r,s.bootstrap,s.sessions);assertFalse(review.legacy);assertEquals(0,r.writes);assertEquals(0,r.resets);assertEquals(0,s.saves);assertTrue(r.closed>0)}
 @Test fun approvedCurrentRecoveryUsesExistingMainEngine()=runBlocking {val c=candidate();val r=Radio();val s=States();val v=c.review(address,r,s.bootstrap,s.sessions);val events=mutableListOf<UpdateEvent>();c.run(v,{r},s.bootstrap,s.sessions,false){events+=it};assertEquals(1,r.writes);assertEquals(1,r.resets);assertEquals(h("main"),r.remote.primary!!.hash);assertTrue(events.last() is UpdateEvent.AwaitingOperator)}
 @Test fun legacyBridgeAdoptsIdentityBeforeMainUpload()=runBlocking {val c=candidate();val r=Radio(true);val s=States();val v=c.review(address,r,s.bootstrap,s.sessions);assertTrue(v.legacy);c.run(v,{r},s.bootstrap,s.sessions,false){};assertEquals(2,r.writes);assertEquals(2,r.resets);assertNotNull(s.boot!!.observedIdentity);assertEquals(identity(),s.normal!!.runtimeIdentity)}
 @Test fun malformedIdentityNeverBecomesLegacyPermission()=runBlocking {val c=candidate();val r=Radio(true);r.identityFailure=IllegalArgumentException("malformed");val s=States();var failed=false;try{c.review(address,r,s.bootstrap,s.sessions)}catch(_:IllegalArgumentException){failed=true};assertTrue(failed);assertEquals(0,r.writes)}
 @Test fun differentCandidateInstanceCannotConsumeReview()=runBlocking {val c=candidate();val r=Radio();val s=States();val v=c.review(address,r,s.bootstrap,s.sessions);var failed=false;try{candidate().run(v,{r},s.bootstrap,s.sessions,false){}}catch(_:IllegalArgumentException){failed=true};assertTrue(failed);assertEquals(0,r.writes)}
 @Test fun consumedReviewCannotStartASecondOperation()=runBlocking {val c=candidate();val r=Radio();val s=States();val v=c.review(address,r,s.bootstrap,s.sessions);c.run(v,{r},s.bootstrap,s.sessions,false){};val writes=r.writes;var failed=false;try{c.run(v,{r},s.bootstrap,s.sessions,false){}}catch(_:IllegalStateException){failed=true};assertTrue(failed);assertEquals(writes,r.writes)}
 @Test fun explicitlyRevokedReviewCannotRun()=runBlocking {val c=candidate();val r=Radio();val s=States();val v=c.review(address,r,s.bootstrap,s.sessions);v.close();var failed=false;try{c.run(v,{r},s.bootstrap,s.sessions,false){}}catch(_:IllegalStateException){failed=true};assertTrue(failed);assertEquals(0,r.writes)}
 @Test fun changedAnchorUidImagesOrCheckpointStopsBeforeMutation()=runBlocking {
  for(change in 0..3){val c=candidate();val r=Radio();val s=States();val v=c.review(address,r,s.bootstrap,s.sessions)
   when(change){0->r.id=r.id.copy(anchorSha256="34".repeat(32));1->r.id=r.id.copy(uid=listOf("00000000","11111111"));2->r.remote=r.remote.copy(primary=r.remote.primary!!.copy(hash="88".repeat(32)));3->s.normal=Checkpoint(bundleDigest=c.digest,bleAddress=address,phase=Phase.UPLOAD_MAIN,targetUid=r.id.uid,runtimeIdentity=r.id)}
   var failed=false;try{c.run(v,{r},s.bootstrap,s.sessions,false){}}catch(_:IllegalArgumentException){failed=true};assertTrue("change $change",failed);assertEquals(0,r.writes);assertEquals(0,r.resets)
  }
 }
 @Test fun cancellationPropagatesAndClosesBeforeRelease()=runBlocking {val c=candidate();val r=Radio();val s=States();val v=c.review(address,r,s.bootstrap,s.sessions);var failed=false;try{c.run(v,{r},s.bootstrap,s.sessions,false){throw CancellationException("stop")}}catch(_:CancellationException){failed=true};assertTrue(failed);assertEquals(0,r.writes);assertTrue(r.closed>=2)}
 @Test fun incompatibleCheckpointIsRefusedDuringReadOnlyReview()=runBlocking {val c=candidate();val r=Radio();val s=States();s.normal=Checkpoint(bundleDigest="ff".repeat(32),bleAddress=address,phase=Phase.UPLOAD_MAIN,targetUid=r.id.uid,runtimeIdentity=r.id);var failed=false;try{c.review(address,r,s.bootstrap,s.sessions)}catch(_:IllegalArgumentException){failed=true};assertTrue(failed);assertEquals(0,r.writes);assertEquals(0,s.saves)}

 @Test fun observedNewRecoveryResolvesOldBootstrapRestartWithoutRetryPermission()=runBlocking {val c=candidate();val r=Radio();r.remote=r.remote.copy(primary=RemoteImage(h("migration"),false,true));val s=States();s.boot=BootstrapCheckpoint(c.digest,address,BootstrapPhase.RESET_INTENT,resetAcknowledged=false);val v=c.review(address,r,s.bootstrap,s.sessions);assertFalse(v.legacy);assertFalse(v.resetRetryRequired);c.run(v,{r},s.bootstrap,s.sessions,false){};assertEquals(1,r.writes);assertEquals(1,r.resets)}

 @Test fun selectedUidReviewCannotBeReboundByMutatingCallerOrDisplayedMetadata()=runBlocking {
  val c=candidate();val r=Radio();val s=States();val expected=r.id.uid.toMutableList()
  val review=c.review(address,r,s.bootstrap,s.sessions,expected);expected[0]="deadbeef"
  assertEquals(r.id.uid,review.expectedUid)
  assertThrows(UnsupportedOperationException::class.java){(review.expectedUid as MutableList<String>)[0]="deadbeef"}
  Unit
 }
 @Test fun selectedDeviceUidMismatchCannotReachAnUpload()=runBlocking {
  val c=candidate();val r=Radio();val s=States();var failed=false
  try{c.review(address,r,s.bootstrap,s.sessions,listOf("deadbeef","01020304"))}catch(_:IllegalArgumentException){failed=true}
  assertTrue(failed);assertEquals(0,r.writes);assertEquals(0,r.resets);assertEquals(0,s.saves)
 }
 @Test fun selectedLegacyDeviceMustMatchAfterPreparationBeforeMainUpload()=runBlocking {
  val c=candidate();val r=Radio(true);val s=States()
  val review=c.review(address,r,s.bootstrap,s.sessions,listOf("deadbeef","01020304"));val events=mutableListOf<UpdateEvent>()
  c.run(review,{r},s.bootstrap,s.sessions,false){events+=it}
  assertTrue(events.last() is UpdateEvent.Paused);assertNull(s.boot?.observedUid);assertEquals("Only recovery preparation can precede live UID availability",1,r.writes);assertEquals(1,r.resets);assertNull(s.normal)
 }

}
