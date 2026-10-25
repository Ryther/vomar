package org.openvimar.updater

import android.content.ContextWrapper
import android.test.InstrumentationTestCase
import org.openvimar.installer.*
import org.openvimar.installer.resume.ResumePhase
import org.openvimar.updater.installer.*
import java.io.File
import java.time.Instant

/** Synthetic private files only. Never enumerates/opens USB or starts SWD. */
@Suppress("DEPRECATION")
class InitialInstallAndroidAdapterTest:InstrumentationTestCase() {
    private fun context()=object:ContextWrapper(instrumentation.targetContext){
        private val folder=File(super.getFilesDir(),"first-install-test-${System.nanoTime()}").apply{mkdirs()}
        override fun getFilesDir()=folder
    }
    private fun archive():ByteArray {
        val flash=ByteArray(0x100000){0xff.toByte()};byteArrayOf(0,0,2,0x20,1,0x10,0,0).copyInto(flash)
        val ficr=ByteArray(4096){0xff.toByte()}
        for((at,value)in listOf(0x10 to 4096L,0x14 to 256L,0x60 to 0x11223344L,0x64 to 0x55667788L,
            0x100 to 0x52840L,0x104 to 0x41414430L,0x10c to 256L,0x110 to 1024L))repeat(4){ficr[at+it]=(value ushr(it*8)).toByte()}
        val regions=mapOf("flash.bin" to flash,"ficr.bin" to ficr,"uicr.bin" to ByteArray(4096){0xff.toByte()})
        return QuiescentArchive.create(regions,regions.mapValues{it.value.copyOf()},QuiescentProvenance("instrumentation","synthetic",3300,0x1366,0x1060,4,0x85,3),
            Instant.parse("2026-10-23T12:00:00Z"),Instant.parse("2026-10-23T12:02:00Z"),0,false)
    }
    fun testPrivateOriginalReopenAndMetadataNeverBecomeResumeAuthority(){
        val context=context()
        try {
            val store=AndroidInitialInstallPersistence(context);val bytes=archive();val original=OriginalArchive.verify(bytes)
            store.saveOriginal("ef1faf4b-cd24-42c7-8508-8d51b4f10ad5",bytes)
            assertEquals(original.archiveSha256,AndroidInitialInstallPersistence(context).reopenOriginal(original.archiveSha256).archiveSha256)
            val request=InstallCaptureRequest("ef1faf4b-cd24-42c7-8508-8d51b4f10ad5","synthetic-only",original.identity,"11".repeat(32))
            store.saveState(InitialInstallSnapshot(InitialInstallPhase.FAILED,request,mutationMayHaveStarted=true,commitMayHaveBeenWritten=true,message="Synthetic lost acknowledgement"))
            val report=AndroidInitialInstallPersistence(context).diagnostic()
            assertEquals(request.requestId,report.getString("requestId"));assertTrue(report.getBoolean("commitMayHaveBeenWritten"))
            assertFalse(report.has("flash"));assertFalse(report.has("regions"));assertTrue(report.toString().length<16384)
        }finally{context.filesDir.deleteRecursively()}
    }
    fun testActualAndroidFilesystemExportReceiptAndProgressedResumeFence(){
        val context=context()
        try{
            val store=AndroidInitialInstallPersistence(context);val bytes=archive();val original=OriginalArchive.verify(bytes)
            val request="ef1faf4b-cd24-42c7-8508-8d51b4f10ad5";store.saveOriginal(request,bytes)
            val material=OriginalArchive.exportAndReopen(original,object:ArchiveExport{
                override fun create(bytes:ByteArray)="content://synthetic-instrumentation/original"
                override fun reopen(document:String)=bytes.copyOf()
            }).deriveOriginal()
            fun hash(value:ByteArray)=java.security.MessageDigest.getInstance("SHA-256").digest(value).joinToString(""){"%02x".format(it.toInt() and 255)}
            val fixed="11".repeat(32);val binding=InstallBinding(original.identity,original.archiveSha256,fixed,fixed,hash(material.anchor()),hash(material.table()),fixed,fixed)
            store.saveExportReceipt(material,binding);store.saveExportReceipt(material,binding)
            val base=FileInstallJournal(store.journalDirectory);assertTrue(base.begin(InstallJournalRecord(binding,1,InstallPhase.PREPARED,null,false,false)))
            val reopened=AndroidInitialInstallPersistence(context);val retained=reopened.reopenRetained(binding.id)
            assertEquals(original.archiveSha256,retained.initialReceipt.archiveSha256)
            reopened.resumeJournal.acquire(binding,retained.initialReceipt,retained.checkpoint.headSha256,request,77,"content://synthetic-cloud/copy").use{
                it.append(ResumePhase.REVIEWED,null,-1,false);it.append(ResumePhase.ERASE_INTENT,0,0,false)
            }
            assertFalse(base.load(binding.id)!!.mutationMayHaveStarted)
            assertEquals(0,reopened.resumeOptions(original.identity).single().frontierPage)
            try{reopened.assertCanCapture(original.identity);fail("Progressed resume must block new original capture")}
            catch(_:IllegalArgumentException){}
        }finally{context.filesDir.deleteRecursively()}
    }
    fun testActualAndroidFilesystemJournalRetainsIncompleteMutationFence(){
        val context=context()
        try {
            val store=AndroidInitialInstallPersistence(context);val target=TargetIdentity(0x11223344,0x55667788,0x41414430);val hash="00".repeat(32)
            val binding=InstallBinding(target,hash,hash,hash,hash,hash,hash,hash);val journal=FileInstallJournal(store.journalDirectory)
            assertTrue(journal.begin(InstallJournalRecord(binding,1,InstallPhase.PREPARED,null,false,false)))
            journal.save(InstallJournalRecord(binding,2,InstallPhase.PAGE_ERASE_INTENT,0,true,false))
            try{AndroidInitialInstallPersistence(context).assertCanCapture(target);fail("Incomplete same-UID mutation must block a fresh original")}
            catch(_:IllegalArgumentException){}
        }finally{context.filesDir.deleteRecursively()}
    }
}
