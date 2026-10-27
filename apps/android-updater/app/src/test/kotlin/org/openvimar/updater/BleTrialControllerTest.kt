package org.openvimar.updater

import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.*

class BleTrialControllerTest {
    private val directory=File("../../../tools/android/test-fixtures/common-v3-candidate")
    private val bytes=File(directory,"qualification-candidate.zip").readBytes()
    private val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File(directory,"public.der").readBytes()))
    private val entries=java.util.zip.ZipInputStream(bytes.inputStream()).use{zip->
        buildMap<String,ByteArray>{while(true){val entry=zip.nextEntry ?: break;put(entry.name,zip.readBytes())}}
    }
    private val manifest=Json.parseToJsonElement(entries.getValue("manifest.json").toString(Charsets.UTF_8)).jsonObject
    private val address="AA:BB:CC:DD:EE:FF"
    private fun hash(role:String)=manifest.getValue(role).jsonObject.getValue("signedRegionSha256").jsonPrimitive.content
    private fun candidate()=BleTrialCandidate.inspect(bytes,key,"9.0.0")

    private inner class Harness {
        var loader:suspend()->BleTrialCandidate={candidate()}
        var permission=true
        var leaseFailure=false
        var leased=false
        var writes=0
        var resets=0
        var closes=0
        var saves=0
        var cancelUpload=false
        var uploadGate:CompletableDeferred<Unit>?=null
        val uploadEntered=CompletableDeferred<Unit>()
        var verificationGate:CompletableDeferred<Unit>?=null
        val verificationEntered=CompletableDeferred<Unit>()
        var resetGate:CompletableDeferred<Unit>?=null
        val resetEntered=CompletableDeferred<Unit>()
        var holdImages:CompletableDeferred<Unit>?=null
        var imagesEntered=CompletableDeferred<Unit>()
        var reset=ResetAck.ACKNOWLEDGED
        var pairingRequests=0
        var checkpoint:Checkpoint?=null
        var identity=RuntimeIdentity(2,"VIMAR30805",2,listOf("11223344","55667788"),"",
            LoaderContract(LoaderContract.COMMON,manifest.getValue("loaderContracts").jsonArray[0].jsonObject.getValue("sha256").jsonPrimitive.content),"12".repeat(32))
        var remote=RemoteImages(RemoteImage(manifest.getValue("allowedSourceSignedHashes").jsonArray[0].jsonPrimitive.content,false,true,"0.5.5"),
            RemoteImage(hash("recovery"),true,true,"0.8.0"))
        val sessions=object:SessionStore {
            override suspend fun load(bundleDigest:String,address:String)=checkpoint
            override suspend fun save(checkpoint:Checkpoint){saves++;this@Harness.checkpoint=checkpoint}
        }
        val bootstrap=object:BootstrapStore {
            override suspend fun load(digest:String,address:String):BootstrapCheckpoint?=null
            override suspend fun save(checkpoint:BootstrapCheckpoint){error("Modern target must not enter bootstrap")}
        }
        private fun check(){check(leased){"Global lease missing"};check(permission){"Bluetooth permission revoked"}}
        private fun radio(expected:String,guard:()->Unit)=object:BleTransport,ZigbeePairingTransport {
            override suspend fun connect(address:String){guard();check();require(address==expected)}
            override suspend fun identityV2():RuntimeIdentity {guard();check();return identity}
            override suspend fun identity():RuntimeIdentity {guard();check();return identity}
            override suspend fun images():RemoteImages {guard();check();imagesEntered.complete(Unit);holdImages?.await();if(writes>0){verificationEntered.complete(Unit);verificationGate?.await()};return remote}
            override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){
                guard();check();if(cancelUpload)throw CancellationException("User stopped trial")
                writes++;onAck(data.size/2);uploadEntered.complete(Unit);uploadGate?.await();onAck(data.size);remote=remote.copy(primary=RemoteImage(hash("main"),false,true,"0.6.0"))
            }
            override suspend fun reset():ResetAck {guard();check();resets++;resetEntered.complete(Unit);resetGate?.await();return reset}
            override suspend fun pairingCapabilities()=ZigbeePairingCapabilities(1,120,true)
            override suspend fun startZigbeePairing():ResetAck {
                guard();check();assertTrue(reports.last().pairing);assertTrue(reports.last().busy)
                pairingRequests++;return reset
            }
            override suspend fun close(){closes++}
        }
        val reports=mutableListOf<BleTrialState>()
        val reportAddresses=mutableListOf<String>()
        val controller=BleTrialController({loader()},{target,guard->radio(target,guard)},bootstrap,sessions,{operation->
            check(!leased)
            if(leaseFailure)error("Another Bluetooth operation is active")
            leased=true
            try{operation{check()}}finally{leased=false}
        },{snapshot,target->reports+=snapshot;reportAddresses+=target})
        suspend fun inspect():BleTrialReviewInfo {controller.inspect(address);return requireNotNull(controller.state.value.review)}
    }

    @Test fun displayedTargetSurvivesUploadAndConsumedReviewThroughAwaitingReturn()=runBlocking {
        val h=Harness();val review=h.inspect();h.uploadGate=CompletableDeferred()
        val operation=launch{h.controller.execute(review.id)}
        try{
            withTimeout(2_000){h.uploadEntered.await()}
            val uploading=h.controller.state.value
            assertNull("Execution consumes the review immediately",uploading.review)
            assertEquals(address,uploading.target?.address)
            assertEquals(review.identitySummary,uploading.target?.identitySummary)
            assertEquals(BleTrialPhase.TRANSFERRING,uploading.phase)
        }finally{h.uploadGate!!.complete(Unit);operation.join()}
        val result=h.controller.state.value
        assertEquals(address,result.target?.address)
        assertEquals(BleTrialPhase.AWAITING_RETURN,result.phase)
        assertNull(result.review)
        h.controller.execute(review.id)
        assertEquals("Display metadata cannot authorize a second upload",1,h.writes)
    }
    @Test fun uploadAcknowledgementAndResetAreDistinctFromVerifiedReturn()=runBlocking {
        val h=Harness();val review=h.inspect();h.verificationGate=CompletableDeferred();h.resetGate=CompletableDeferred()
        val operation=launch{h.controller.execute(review.id)}
        try{
            withTimeout(2_000){h.verificationEntered.await()}
            val verifying=h.controller.state.value
            assertEquals(address,verifying.target?.address)
            assertEquals(BleTrialPhase.VERIFYING,verifying.phase)
            assertNull("Uploaded bytes do not establish reset or return",verifying.acknowledged)
            h.verificationGate!!.complete(Unit)
            withTimeout(2_000){h.resetEntered.await()}
            assertEquals(BleTrialPhase.RESTARTING,h.controller.state.value.phase)
            assertEquals(address,h.controller.state.value.target?.address)
            assertNull(h.controller.state.value.acknowledged)
        }finally{h.verificationGate!!.complete(Unit);h.resetGate!!.complete(Unit);operation.join()}
        assertEquals(BleTrialPhase.AWAITING_RETURN,h.controller.state.value.phase)
        assertEquals(true,h.controller.state.value.acknowledged)
    }
    @Test fun displayedTargetSurvivesFailureAndStopWithoutRetainingApproval()=runBlocking {
        for(stopped in listOf(false,true)){
            val h=Harness();val review=h.inspect()
            if(stopped)h.cancelUpload=true else h.permission=false
            try{h.controller.execute(review.id)}catch(_:CancellationException){}
            val state=h.controller.state.value
            assertEquals(address,state.target?.address)
            assertEquals(review.identitySummary,state.target?.identitySummary)
            assertEquals(BleTrialPhase.PAUSED,state.phase)
            assertNull(state.review);assertFalse(state.busy);assertEquals(0,h.resets)
        }
    }
    @Test fun newInspectionNeverShowsThePriorIdentityEvenWhenItFails()=runBlocking {
        val h=Harness();val previous=h.inspect();val other="11:22:33:44:55:66"
        val loading=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        h.loader={loading.complete(Unit);release.await();error("Candidate unavailable")}
        val operation=launch{h.controller.inspect(other)}
        try{
            withTimeout(2_000){loading.await()}
            val inspecting=h.controller.state.value
            assertEquals(other,inspecting.target?.address)
            assertNull(inspecting.target?.identitySummary)
            assertEquals(BleTrialPhase.INSPECTING,inspecting.phase)
            assertNull(inspecting.review)
        }finally{release.complete(Unit);operation.join()}
        assertEquals(other,h.controller.state.value.target?.address)
        assertNull(h.controller.state.value.target?.identitySummary)
        assertEquals(BleTrialPhase.PAUSED,h.controller.state.value.phase)
        h.controller.execute(previous.id);assertEquals(0,h.writes)
    }
    @Test fun candidateInvalidationClearsDisplayAndFreshControllerRestoresNoTargetOrApproval()=runBlocking {
        val h=Harness();val review=h.inspect()
        assertNotNull(h.controller.state.value.target)
        assertTrue(h.controller.invalidate());assertNull(h.controller.state.value.target)
        val restored=Harness()
        assertNull(restored.controller.state.value.target);assertNull(restored.controller.state.value.review)
        restored.controller.execute(review.id);assertEquals(0,restored.writes);assertEquals(0,restored.resets)
    }

    @Test fun readOnlyInspectionPublishesTargetReviewWithoutMutation()=runBlocking {
        val h=Harness();val review=h.inspect()
        assertEquals(address,review.address);assertEquals("0.6.0",review.version);assertEquals("0.5.5",review.currentVersion)
        assertTrue(review.identitySummary.contains("11223344"));assertFalse(review.legacy)
        assertEquals(0,h.writes);assertEquals(0,h.resets);assertEquals(0,h.saves)
        assertFalse(h.controller.state.value.busy);assertFalse(h.leased);assertTrue(h.closes>0)
        assertEquals(address,h.reportAddresses.last())
    }
    @Test fun explicitExecutionUsesOriginalCandidateOwnerDespiteRevalidationReturningNewInstance()=runBlocking {
        val h=Harness();val review=h.inspect();h.controller.execute(review.id)
        assertEquals(1,h.writes);assertEquals(1,h.resets);assertEquals(Phase.AWAIT_OPERATOR,h.checkpoint!!.phase)
        assertEquals(true,h.controller.state.value.acknowledged);assertNull(h.controller.state.value.review)
        assertTrue(h.controller.state.value.status.contains("Zigbee"));assertFalse(h.leased)
        h.controller.execute(review.id);assertEquals(1,h.writes);assertEquals(1,h.resets)
    }
    @Test fun newInspectionRevokesPreviousReview()=runBlocking {
        val h=Harness();val previous=h.inspect();val fresh=h.inspect();assertNotEquals(previous.id,fresh.id)
        h.controller.execute(previous.id);assertEquals(0,h.writes);assertEquals(0,h.resets);assertNull(h.controller.state.value.review)
    }
    @Test fun invalidationAndNewControllerNeverRestoreAnApproval()=runBlocking {
        val h=Harness();val review=h.inspect();assertTrue(h.controller.invalidate())
        h.controller.execute(review.id);assertEquals(0,h.writes);assertNull(h.controller.state.value.review)
        val restored=Harness();restored.controller.execute(review.id);assertEquals(0,restored.writes)
    }
    @Test fun changedTargetStopsBeforeAnyUpload()=runBlocking {
        val h=Harness();val review=h.inspect();h.identity=h.identity.copy(uid=listOf("00000000","11111111"))
        h.controller.execute(review.id);assertEquals(0,h.writes);assertEquals(0,h.resets);assertNull(h.controller.state.value.review)
    }
    @Test fun changedOrUnverifiableReleaseRevokesApproval()=runBlocking {
        val h=Harness();val review=h.inspect()
        h.loader={BleTrialCandidate.inspect(bytes.copyOf().also{it[it.lastIndex/2]=(it[it.lastIndex/2].toInt() xor 1).toByte()},key,"9.0.0")}
        h.controller.execute(review.id);assertEquals(0,h.writes);assertNull(h.controller.state.value.review);assertFalse(h.leased)
    }
    @Test fun differentlyWrappedButStillSignedCandidateDoesNotInheritExactZipApproval()=runBlocking {
        val h=Harness();val review=h.inspect()
        // Change only ZIP member timestamp metadata; all signed entries remain exact.
        val alternate=BleTrialCandidate.inspect(bytes.copyOf().also{it[10]=(it[10].toInt() xor 1).toByte()},key,"9.0.0")
        assertNotEquals(review.digest,alternate.digest);h.loader={alternate}
        h.controller.execute(review.id);assertEquals(0,h.writes);assertEquals(0,h.resets);assertNull(h.controller.state.value.review)
    }
    @Test fun permissionAndLeaseFailureConsumeReviewWithoutMutation()=runBlocking {
        for(failLease in listOf(false,true)){
            val h=Harness();val review=h.inspect();if(failLease)h.leaseFailure=true else h.permission=false
            h.controller.execute(review.id);assertEquals(0,h.writes);assertEquals(0,h.resets)
            assertNull(h.controller.state.value.review);assertFalse(h.controller.state.value.busy);assertFalse(h.leased)
            assertEquals(address,h.reportAddresses.last())
        }
    }
    @Test fun cancellationConsumesReviewAndDrainsTransportBeforeIdle()=runBlocking {
        val h=Harness();val review=h.inspect();h.cancelUpload=true
        var cancelled=false;try{h.controller.execute(review.id)}catch(_:CancellationException){cancelled=true}
        assertTrue(cancelled);assertNull(h.controller.state.value.review);assertFalse(h.controller.state.value.busy)
        assertFalse(h.leased);assertTrue(h.closes>=3);assertEquals(0,h.resets)
        assertEquals(address,h.reportAddresses.last())
    }
    @Test fun busyInspectionCannotBeInvalidatedOrReplaced()=runBlocking {
        val h=Harness();h.holdImages=CompletableDeferred();val operation=launch{h.controller.inspect(address)}
        withTimeout(2_000){h.imagesEntered.await()};assertTrue(h.controller.state.value.busy);assertFalse(h.controller.invalidate())
        var rejected=false;try{h.controller.inspect("11:22:33:44:55:66")}catch(_:IllegalStateException){rejected=true}
        assertTrue(rejected);h.holdImages!!.complete(Unit);operation.join();assertEquals(address,h.controller.state.value.review!!.address)
    }
    @Test fun uncertainResetRequiresFreshExplicitConfirmation()=runBlocking {
        val h=Harness();h.remote=h.remote.copy(primary=RemoteImage(hash("main"),false,true,"0.6.0"))
        h.checkpoint=Checkpoint(bundleDigest=candidate().digest,bleAddress=address,phase=Phase.FINAL_RESET_INTENT,targetUid=h.identity.uid,runtimeIdentity=h.identity)
        val review=h.inspect();assertTrue(review.resetRetryRequired);h.controller.execute(review.id)
        assertEquals(0,h.resets);assertNull(h.controller.state.value.review)
        val fresh=h.inspect();h.controller.execute(fresh.id,true);assertEquals(1,h.resets);assertEquals(true,h.controller.state.value.acknowledged)
    }
    @Test fun lostResetAcknowledgementNeverReportsConfirmedReturnOrAutomaticallyRetries()=runBlocking {
        val h=Harness();h.reset=ResetAck.LOST;val review=h.inspect();h.controller.execute(review.id)
        assertEquals(1,h.resets);assertEquals(false,h.controller.state.value.acknowledged)
        assertTrue(h.controller.state.value.status.contains("uncertain",true));assertNull(h.controller.state.value.review)
    }
    @Test fun importingForTrialDoesNotEnableNormalReleaseValidator() {
        candidate()
        assertThrows(Exception::class.java){CommonPackageValidator.validate(CommonPackageReader.read(bytes.inputStream()),key,"9.0.0")}
    }
    @Test fun pairingNeedsFreshReviewAndDurableIntentWithoutFirmwareSelection()=runBlocking {
        val h=Harness();h.loader={error("Pairing needs no firmware package")}
        h.controller.inspectPairing(address,h.identity.uid)
        val review=requireNotNull(h.controller.state.value.pairingReview)
        assertEquals(0,h.pairingRequests)
        h.controller.executePairing(review.id)
        assertEquals(1,h.pairingRequests);assertEquals(0,h.writes);assertEquals(0,h.resets)
        assertEquals(true,h.controller.state.value.acknowledged)
        h.controller.executePairing(review.id);assertEquals(1,h.pairingRequests)
    }
    @Test fun pairingLostAckIsUncertainAndCannotReplayTheReview()=runBlocking {
        val h=Harness();h.reset=ResetAck.LOST
        h.controller.inspectPairing(address)
        h.controller.executePairing(requireNotNull(h.controller.state.value.pairingReview).id)
        assertEquals(false,h.controller.state.value.acknowledged)
        assertTrue(h.controller.state.value.status.contains("uncertain",true))
        assertNull(h.controller.state.value.pairingReview);assertEquals(1,h.pairingRequests)
    }

}
