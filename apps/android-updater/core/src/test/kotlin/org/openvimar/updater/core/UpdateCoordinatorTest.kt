package org.openvimar.updater.core

import org.junit.Assert.*
import org.junit.Test
import java.io.File
import kotlinx.serialization.json.Json
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.CancellationException

class UpdateCoordinatorTest {
    private val m=Json.decodeFromString<Manifest>(File("../test-fixtures/manifest.json").readText())
    private val p=ValidatedPackage(m,byteArrayOf(1),byteArrayOf(2),"bundle")
    private fun transport(recovery:String=m.legacyRecoverySignedHash,primary:String?=m.allowedSourceSignedHashes.first())=FakeTransport(p,RemoteImages(primary?.let { RemoteImage(it,true,true) },RemoteImage(recovery,true,true)))
    private fun run(t:FakeTransport,s:FakeStore=FakeStore(),c:UpdateCoordinator?=null,allowResetRetry:Boolean=false)=runBlocking {
        var clock=0L
        val coordinator=c ?: UpdateCoordinator(wait={clock+=it},now={clock})
        val events=mutableListOf<UpdateEvent>(); coordinator.run(p,t,s,allowResetRetry=allowResetRetry) {events+=it}; events
    }
    @Test fun normalTwoStagesAndFinalAwaitingOperator() {
        val t=transport(); val s=FakeStore(); val events=run(t,s)
        assertEquals(2,t.calls.count {it=="upload"}); assertEquals(2,t.calls.count {it=="reset"})
        assertEquals(UpdateEvent.AwaitingOperator(true),events.last()); assertEquals(Phase.AWAIT_OPERATOR,s.checkpoint!!.phase)
    }
    @Test fun saveFailurePreventsUpload() { val t=transport(); val s=FakeStore(); s.failSave=true; assertTrue(run(t,s).last() is UpdateEvent.Paused); assertFalse("upload" in t.calls) }
    @Test fun unknownHashNeverWrites() { val t=transport(primary="unknown"); run(t); assertFalse("upload" in t.calls); assertFalse("reset" in t.calls) }
    @Test fun completeUploadNeverRepeated() { val t=transport(m.targetRecoverySignedHash,m.main.signedRegionSha256); val s=FakeStore(); run(t,s); run(t,s); assertFalse("upload" in t.calls); assertEquals(1,t.calls.count {it=="reset"}) }
    @Test fun crashAfterAckReconcilesRemote() {
        val t=transport(m.targetRecoverySignedHash); val s=FakeStore()
        t.afterAck={throw CancellationException("process died")}
        assertThrows(CancellationException::class.java) {run(t,s)}
        t.afterAck={}; run(t,s)
        assertEquals(1,t.calls.count {it=="upload"}); assertEquals(1,t.calls.count {it=="reset"})
    }
    @Test fun lostResetAckRequiresReadback() {
        val t=transport(m.targetRecoverySignedHash,m.main.signedRegionSha256); t.ack=ResetAck.LOST
        val events=run(t); val reset=t.calls.indexOf("reset")
        assertTrue(t.calls.drop(reset+1).contains("images")); assertEquals(UpdateEvent.AwaitingOperator(false),events.last())
    }
    @Test fun stopNeverIssuesNextCommand() {
        val t=transport(); val c=UpdateCoordinator(wait={}); t.boundary={if(it=="upload.after") c.stop()}
        assertEquals(UpdateEvent.Stopped,run(t,c=c).last()); assertFalse("reset" in t.calls)
    }
    @Test fun stopDuringProgressPreventsNextUploadPacket()=runBlocking {
        val t=transport(); val c=UpdateCoordinator(wait={}); val events=mutableListOf<UpdateEvent>()
        t.uploadOffsets=listOf(0,1)
        c.run(p,t,FakeStore()) { events+=it; if(it is UpdateEvent.Progress)c.stop() }
        assertEquals(1,events.count {it is UpdateEvent.Progress}); assertFalse("reset" in t.calls)
    }
    @Test fun corruptSessionStopsBeforeTransport() { val t=transport(); val s=FakeStore(); s.corrupt=true; run(t,s); assertEquals(listOf("close"),t.calls) }
    @Test fun invalidOffsetStopsWithoutReset() { val t=transport(); t.uploadOffsets=listOf(999); run(t); assertFalse("reset" in t.calls) }
    @Test fun reconnectIsBoundedAndBackoffExact() {
        val t=transport(); t.boundary={if(it=="connect.before") throw TransportDisconnected()}
        val waits=mutableListOf<Long>(); val events=run(t,c=UpdateCoordinator(wait={waits+=it}))
        assertEquals(listOf(2000L,5000L,10000L),waits); assertTrue(events.last() is UpdateEvent.Paused)
    }
    @Test fun missingPrimaryResumesOnlyAuthorizedPhase() {
        val t=transport(m.targetRecoverySignedHash,null); val s=FakeStore(Checkpoint(bundleDigest=p.bundleDigest,bleAddress=m.device.bleAddress,phase=Phase.UPLOAD_MAIN,ackOffset=999))
        run(t,s); assertEquals(1,t.calls.count {it=="upload"}); assertEquals(1,s.saved.first {it.phase==Phase.UPLOAD_MAIN && it.ackOffset>0}.ackOffset)
    }
    @Test fun crashesAtEveryTransportBoundaryNeverRepeatCompletedImagesOrResetIntent() {
        listOf("connect","images","upload","reset").flatMap {listOf("$it.before","$it.after")}.forEach { target ->
            val t=transport(m.targetRecoverySignedHash); val s=FakeStore(); var fired=false
            t.boundary={if(!fired && it==target){fired=true;throw CancellationException(target)}}
            assertThrows(CancellationException::class.java) {run(t,s)}
            t.boundary={}; run(t,s)
            assertTrue("$target repeated upload",t.calls.count {it=="upload"}<=1)
            assertTrue("$target repeated reset",t.calls.count {it=="reset"}<=1)
        }
    }
    @Test fun crashesAtEachPersistBoundaryPreserveRemoteReconciliation() {
        for(target in listOf("load.before","load.after","save.before","save.after")) {
            val t=transport(m.targetRecoverySignedHash); val s=FakeStore(); var fired=false
            s.boundary={if(!fired && it==target){fired=true;throw CancellationException(target)}}
            assertThrows(CancellationException::class.java) {run(t,s)}
            s.boundary={};run(t,s)
            assertEquals(1,t.calls.count {it=="upload"}); assertEquals(1,t.calls.count {it=="reset"})
        }
    }
    @Test fun migrationWindowExpiresWithoutRepeatingReset() {
        val t=transport(primary=m.migration.signedRegionSha256)
        val s=FakeStore(Checkpoint(bundleDigest=p.bundleDigest,bleAddress=m.device.bleAddress,phase=Phase.MIGRATION_RESET_INTENT))
        var clock=0L
        val events=run(t,s,UpdateCoordinator(wait={clock+=it},now={clock}))
        assertEquals(120_000L,clock); assertTrue(events.last() is UpdateEvent.Paused)
        assertFalse("reset" in t.calls); assertFalse("upload" in t.calls)
    }
    @Test fun disconnectedFinalResetNeverLoopsAndReadsBack() {
        val t=transport(m.targetRecoverySignedHash,m.main.signedRegionSha256); var once=true
        t.boundary={if(it=="reset.after" && once){once=false;throw TransportDisconnected()}}
        val events=run(t)
        assertEquals(1,t.calls.count {it=="reset"}); assertEquals(UpdateEvent.AwaitingOperator(false),events.last())
        assertEquals(listOf("images","close"),t.calls.takeLast(2))
    }
    @Test fun crashAtEachCallAndPersistenceOccurrence() {
        val baselineT=transport();val baselineS=FakeStore();var count=0
        baselineT.boundary={count++};baselineS.boundary={count++};run(baselineT,baselineS)
        for(crash in 1..count) {
            val t=transport();val s=FakeStore();var index=0
            val boundary:(String)->Unit={if(++index==crash)throw CancellationException("boundary $crash")}
            t.boundary=boundary;s.boundary=boundary
            assertThrows(CancellationException::class.java) {run(t,s)}
            t.boundary={};s.boundary={}
            val resumed=run(t,s,allowResetRetry=true)
            assertEquals("crash $crash failed explicit resume",UpdateEvent.AwaitingOperator(true),resumed.last())
            assertTrue("crash $crash repeated a full upload",t.completedUploads<=2)
            assertTrue("crash $crash exceeded one explicit reset retry",t.calls.count {it=="reset"}<=3)
        }
    }
    @Test fun lostFinalResetWithUnexpectedReadbackPauses() {
        val t=transport(m.targetRecoverySignedHash,m.main.signedRegionSha256); t.ack=ResetAck.LOST
        t.boundary={if(it=="reset.after")t.remote=t.remote.copy(recovery=RemoteImage("foreign",true,true))}
        assertTrue(run(t).last() is UpdateEvent.Paused)
        assertEquals(1,t.calls.count {it=="reset"})
    }
    @Test fun uploadReadbackMismatchNeverResets() {
        val t=transport();t.afterAck={t.remote=t.remote.copy(primary=RemoteImage("foreign",true,true))}
        assertTrue(run(t).last() is UpdateEvent.Paused);assertFalse("reset" in t.calls)
    }
    @Test fun explicitResumeRetriesMigrationIntentAndCompletes() {
        val t=transport(primary=m.migration.signedRegionSha256)
        val s=FakeStore(Checkpoint(bundleDigest=p.bundleDigest,bleAddress=m.device.bleAddress,phase=Phase.MIGRATION_RESET_INTENT))
        assertEquals(UpdateEvent.AwaitingOperator(true),run(t,s,allowResetRetry=true).last())
        assertEquals(1,t.completedUploads);assertEquals(2,t.calls.count {it=="reset"})
    }
    @Test fun explicitResumeRetriesUncertainFinalIntentAndLostAck() {
        for(phase in listOf(Phase.FINAL_RESET_INTENT,Phase.AWAIT_OPERATOR)) {
            val t=transport(m.targetRecoverySignedHash,m.main.signedRegionSha256)
            val s=FakeStore(Checkpoint(bundleDigest=p.bundleDigest,bleAddress=m.device.bleAddress,phase=phase))
            assertEquals(UpdateEvent.AwaitingOperator(true),run(t,s,allowResetRetry=true).last())
            assertEquals(0,t.completedUploads);assertEquals(1,t.calls.count {it=="reset"})
        }
    }
    @Test fun explicitRetryNeverLoopsWhenMigrationStillShowsOldRecovery() {
        val t=transport(primary=m.migration.signedRegionSha256)
        val s=FakeStore(Checkpoint(bundleDigest=p.bundleDigest,bleAddress=m.device.bleAddress,phase=Phase.MIGRATION_RESET_INTENT))
        t.boundary={if(it=="reset.after")t.remote=t.remote.copy(recovery=RemoteImage(m.legacyRecoverySignedHash,true,true))}
        assertTrue(run(t,s,allowResetRetry=true).last() is UpdateEvent.Paused)
        assertEquals(1,t.calls.count {it=="reset"});assertEquals(0,t.completedUploads)
    }
    @Test fun explicitRetryStillRejectsUnknownImagesAndAcknowledgedFinal() {
        val t=transport(m.targetRecoverySignedHash,"unknown")
        val s=FakeStore(Checkpoint(bundleDigest=p.bundleDigest,bleAddress=m.device.bleAddress,phase=Phase.FINAL_RESET_INTENT))
        assertTrue(run(t,s,allowResetRetry=true).last() is UpdateEvent.Paused);assertFalse("reset" in t.calls)
        t.remote=t.remote.copy(primary=RemoteImage(m.main.signedRegionSha256,true,true))
        s.checkpoint=s.checkpoint!!.copy(resetAcknowledged=true)
        assertEquals(UpdateEvent.AwaitingOperator(true),run(t,s,allowResetRetry=true).last());assertFalse("reset" in t.calls)
    }
    @Test fun closeRunsAfterSuccessFailureAndCancellationAndCannotMaskOutcome() {
        val success=transport(m.targetRecoverySignedHash,m.main.signedRegionSha256)
        assertEquals(UpdateEvent.AwaitingOperator(true),run(success).last());assertEquals("close",success.calls.last())
        val failure=transport();failure.boundary={if(it=="connect.before")error("connect failed")};failure.closeFailure=IllegalStateException("cleanup failed")
        assertEquals(UpdateEvent.Paused("connect failed"),run(failure).last());assertEquals("close",failure.calls.last())
        val cancelled=transport();cancelled.boundary={if(it=="connect.before")throw CancellationException("cancelled")};cancelled.closeFailure=IllegalStateException("cleanup failed")
        assertThrows(CancellationException::class.java){run(cancelled)};assertEquals("close",cancelled.calls.last())
    }
    @Test fun lostMigrationAndFinalAckHaveLiveExplicitRecovery() {
        val t=transport(primary=m.migration.signedRegionSha256);val s=FakeStore();t.ack=ResetAck.LOST
        t.boundary={if(it=="reset.after")t.remote=t.remote.copy(recovery=RemoteImage(m.legacyRecoverySignedHash,true,true))}
        assertTrue(run(t,s).last() is UpdateEvent.Paused);assertEquals(1,t.calls.count {it=="reset"})
        t.boundary={};t.ack=ResetAck.ACKNOWLEDGED
        assertEquals(UpdateEvent.AwaitingOperator(true),run(t,s,allowResetRetry=true).last())
        assertEquals(1,t.completedUploads);assertEquals(3,t.calls.count {it=="reset"})
        val final=transport(m.targetRecoverySignedHash,m.main.signedRegionSha256);val finalStore=FakeStore();final.ack=ResetAck.LOST
        assertEquals(UpdateEvent.AwaitingOperator(false),run(final,finalStore).last())
        final.ack=ResetAck.ACKNOWLEDGED
        assertEquals(UpdateEvent.AwaitingOperator(true),run(final,finalStore,allowResetRetry=true).last())
        assertEquals(0,final.completedUploads);assertEquals(2,final.calls.count {it=="reset"})
    }
}
