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
    fun testUsbOwnerReleasesItsLeaseWhenAndroidServiceAcquisitionFails(){
        val context=object:ContextWrapper(instrumentation.targetContext){
            override fun getSystemService(name:String):Any? {
                check(name==android.content.Context.USB_SERVICE)
                throw java.io.IOException("Synthetic unavailable USB service")
            }
        }
        val outcome=runCatching{AndroidDkInstallUsbOwner.open(context,"synthetic-absent-probe","synthetic-open",{false})}
        assertTrue(outcome.exceptionOrNull() is java.io.IOException)
        val next=checkNotNull(DkUsbOperationGate.acquire("after synthetic failure"))
        try{next.checkCurrent()}finally{next.close()}
    }
    private fun context()=object:ContextWrapper(instrumentation.targetContext){
        private val folder=File(super.getFilesDir(),"first-install-test-${System.nanoTime()}").apply{mkdirs()}
        override fun getFilesDir()=folder
        override fun getSharedPreferences(name:String,mode:Int)=super.getSharedPreferences("${folder.name}-$name",mode)
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
            store.saveState(InitialInstallSnapshot(InitialInstallPhase.FAILED,request,mutationMayHaveStarted=true,commitMayHaveBeenWritten=true,programmingPreparation="Synthetic ACL preparation",installStep="PAGE_ERASE_INTENT",installAddress=4096,message="Synthetic lost acknowledgement"))
            val report=AndroidInitialInstallPersistence(context).diagnostic()
            assertEquals(request.requestId,report.getString("requestId"));assertTrue(report.getBoolean("commitMayHaveBeenWritten"))
            assertEquals("Synthetic ACL preparation",report.getString("programmingPreparation"));assertEquals("PAGE_ERASE_INTENT",report.getString("installStep"));assertEquals(4096,report.getInt("installAddress"))
            assertFalse(report.has("flash"));assertFalse(report.has("regions"));assertTrue(report.toString().length<16384)
        }finally{context.filesDir.deleteRecursively()}
    }
    fun testPrivateBackupHandoffReopensExactBytesAndCatalogMatchesUidOnly(){
        val context=context()
        try{
            val store=AndroidInitialInstallPersistence(context);val bytes=archive();val checked=OriginalArchive.verify(bytes)
            store.saveOriginal("ef1faf4b-cd24-42c7-8508-8d51b4f10ad5",bytes)
            val port=store.privateExport(checked.archiveSha256)
            val exported=OriginalArchive.exportAndReopen(checked,port)
            assertTrue(exported.document.startsWith("file:"));val material=exported.deriveOriginal();assertEquals(checked.identity,material.identity)
            fun hash(value:ByteArray)=java.security.MessageDigest.getInstance("SHA-256").digest(value).joinToString(""){"%02x".format(it.toInt() and 255)}
            val fixed="11".repeat(32);val binding=InstallBinding(checked.identity,checked.archiveSha256,fixed,fixed,hash(material.anchor()),hash(material.table()),fixed,fixed)
            store.saveExportReceipt(material,binding)
            val journal=FileInstallJournal(store.journalDirectory);assertTrue(journal.begin(InstallJournalRecord(binding,1,InstallPhase.PREPARED,null,false,false)))
            val retained=AndroidInitialInstallPersistence(context).reopenRetained(binding.id)
            assertEquals(checked.archiveSha256,retained.reopenOriginal(exported.document,port::reopen).archiveSha256)
            val uid=listOf("%08x".format(checked.identity.uid0),"%08x".format(checked.identity.uid1))
            assertEquals(1,store.backupsFor(uid).size);assertTrue(store.backupsFor(listOf("deadbeef","01020304")).isEmpty())
            assertTrue(store.originalBytes(checked.archiveSha256).contentEquals(bytes))
            val changed=bytes.copyOf().apply{this[10]=(this[10].toInt() xor 1).toByte()}
            try{port.create(changed);fail("Private handoff must reject different bytes")}catch(_:IllegalArgumentException){}
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
    fun testStartIntentAndAcknowledgementSurviveAndroidReopen(){
        val context=context()
        try{
            val store=AndroidInitialInstallPersistence(context);val bytes=archive();val original=OriginalArchive.verify(bytes)
            val request="ef1faf4b-cd24-42c7-8508-8d51b4f10ad5";store.saveOriginal(request,bytes)
            val material=OriginalArchive.exportAndReopen(original,store.privateExport(original.archiveSha256)).deriveOriginal()
            fun hash(value:ByteArray)=java.security.MessageDigest.getInstance("SHA-256").digest(value).joinToString(""){"%02x".format(it.toInt() and 255)}
            val fixed="11".repeat(32);val binding=InstallBinding(original.identity,original.archiveSha256,fixed,fixed,hash(material.anchor()),hash(material.table()),fixed,fixed)
            store.saveExportReceipt(material,binding)
            val journal=FileInstallJournal(store.journalDirectory)
            assertTrue(journal.begin(InstallJournalRecord(binding,1,InstallPhase.PREPARED,null,false,false)))
            journal.save(InstallJournalRecord(binding,2,InstallPhase.VERIFIED,null,true,true))
            store.recordStart(binding,request,false)
            val reopened=AndroidInitialInstallPersistence(context)
            assertTrue(reopened.reopenRetained(binding.id).startUncertain)
            assertEquals(binding.id,reopened.resumeOptions(original.identity).single().bindingId)
            try{reopened.recordStart(binding,"ab1faf4b-cd24-42c7-8508-8d51b4f10ad5",true);fail("A different request must not acknowledge the start")}
            catch(_:IllegalArgumentException){}
            assertTrue(AndroidInitialInstallPersistence(context).reopenRetained(binding.id).startUncertain)
            reopened.recordStart(binding,request,true)
            val completed=AndroidInitialInstallPersistence(context)
            assertFalse(completed.reopenRetained(binding.id).startUncertain)
            assertTrue(completed.resumeOptions(original.identity).isEmpty())
            assertTrue(completed.originalBytes(original.archiveSha256).contentEquals(bytes))
            try{completed.assertCanCapture(original.identity);fail("Completed start must not permit replacing the original")}
            catch(_:IllegalArgumentException){}
        }finally{context.filesDir.deleteRecursively()}
    }
}
