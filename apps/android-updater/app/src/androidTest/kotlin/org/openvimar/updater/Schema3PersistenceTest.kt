package org.openvimar.updater

import android.content.Context
import android.content.ContextWrapper
import android.test.InstrumentationTestCase
import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec
import kotlinx.coroutines.runBlocking
import org.json.JSONObject
import org.openvimar.updater.core.*

/** Synthetic signed bytes in test APK only. No USB/Bluetooth/network access. */
@Suppress("DEPRECATION")
class Schema3PersistenceTest:InstrumentationTestCase() {
    private fun context():Context=object:ContextWrapper(instrumentation.targetContext) {
        private val directory=File(super.getFilesDir(),"schema3-test-${System.nanoTime()}").apply{mkdirs()}
        override fun getFilesDir()=directory
    }
    private fun key()=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(instrumentation.context.assets.open("synthetic-common-v3-public.der").use{it.readBytes()}))
    private fun imported(context:Context):Pair<DocumentRepository,ValidatedPackage> {
        val repository=DocumentRepository(context,key())
        assertNull(repository.importAnyStream(instrumentation.context.assets.open("synthetic-common-v3.zip")))
        val common=requireNotNull(repository.pendingCommon())
        val identity=RuntimeIdentity(2,"VIMAR30805",2,listOf("11223344","55667788"),"",common.manifest.loaderContracts.single{it.kind==LoaderContract.COMMON},"12".repeat(32))
        return repository to repository.bindCommonTarget("AA:BB:CC:DD:EE:FF",identity)
    }
    fun testTypedTargetAndAtomicCheckpointSurvivePrivateReopen()=runBlocking {
        val context=context()
        try {
            val (_,bound)=imported(context)
            val checkpoint=Checkpoint(bundleDigest=bound.bundleDigest,bleAddress=bound.manifest.device.bleAddress,phase=Phase.MIGRATION_RESET_INTENT,targetUid=bound.targetUid,runtimeIdentity=bound.runtimeIdentity)
            AndroidSessionStore(context.filesDir).save(checkpoint)
            val reopened=DocumentRepository(context,key()).current()!!
            assertEquals(bound.runtimeIdentity,reopened.runtimeIdentity)
            val saved=AndroidSessionStore(context.filesDir).load(reopened.bundleDigest,reopened.manifest.device.bleAddress,reopened.targetUid)
            assertEquals(checkpoint,saved);assertTrue(UpdatePlanner.matches(reopened,saved))
            assertFalse(UpdatePlanner.matches(reopened.copy(runtimeIdentity=reopened.runtimeIdentity!!.copy(anchorSha256="34".repeat(32))),saved))
        } finally {context.filesDir.deleteRecursively()}
    }
    fun testOldUidOnlyCheckpointCannotBecomeSchema3Authority()=runBlocking {
        val context=context()
        try {
            val (_,bound)=imported(context)
            val checkpoint=Checkpoint(bundleDigest=bound.bundleDigest,bleAddress=bound.manifest.device.bleAddress,phase=Phase.UPLOAD_MAIN,targetUid=bound.targetUid)
            AndroidSessionStore(context.filesDir).save(checkpoint)
            val file=SessionFiles(context.filesDir).checkpoint(SessionFiles.Identity(checkpoint.bundleDigest,checkpoint.bleAddress,checkpoint.targetUid))
            val old=JSONObject(file.readText()).apply{remove("runtimeIdentity")};file.writeText(old.toString())
            val loaded=AndroidSessionStore(context.filesDir).read()!!
            assertNull(loaded.runtimeIdentity);assertFalse(UpdatePlanner.matches(bound,loaded))
        } finally {context.filesDir.deleteRecursively()}
    }
}
