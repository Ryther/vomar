package org.openvimar.updater

import android.content.Context
import android.net.Uri
import android.os.Build
import android.util.AtomicFile
import java.io.File
import java.security.PublicKey
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject
import org.openvimar.updater.ble.NordicBleTransport
import org.openvimar.updater.core.*

internal data class BleTrialSelection(val reference:BenchCandidateRef,val version:String,val recoveryVersion:String)
/** Separate candidate namespace. Restored selection/report never restores approval. */
internal class BleTrialRuntime(context:Context,verificationKey:PublicKey?=null,
    transportOverride:((String,()->Unit)->BleTransport)?=null,
    leaseOverride:(suspend(suspend(()->Unit)->Unit)->Unit)?=null) {
    private val app=context.applicationContext
    private val cache=AndroidBenchCandidates(app,verificationKey)
    private val preferences=app.getSharedPreferences("ble-trial",Context.MODE_PRIVATE)
    private val report=AtomicFile(File(app.filesDir,"ble-trial-report.json"))
    private val mutableSelection=MutableStateFlow(restoreSelection())
    val selection=mutableSelection.asStateFlow()
    private val mutableMessage=MutableStateFlow<String?>(null)
    val message=mutableMessage.asStateFlow()
    private val directory=File(app.filesDir,"ble-trial-state").apply{check(mkdirs()||isDirectory)}
    private val diagnostics=BleTrialDiagnosticCapture()
    val controller=BleTrialController(
        candidateLoader={cache.inspectBleTrial(requireNotNull(selection.value){"Choose firmware first"}.reference)},
        transportFactory={address,check->
            diagnostics.target(address)
            transportOverride?.invoke(address,check) ?: TrialCheckedTransport(NordicBleTransport(app,address),check)
        },
        bootstrap=AndroidBootstrapStore(directory),sessions=AndroidSessionStore(directory),
        lease={block->
            diagnostics.begin()
            val capture:suspend(()->Unit)->Unit={check->
                // Freeze evidence before another owner can acquire the radio.
                try{block(check)}finally{diagnostics.finish()}
            }
            if(leaseOverride!=null)leaseOverride(capture)else AndroidSessionOwner.get(app).executeFleet(capture)
        },
        reportWriter={state,address->saveReport(state,address)}
    )
    private fun restoreSelection():BleTrialSelection?=runCatching {
        val saved=preferences.getString("candidate",null)?:return null
        val j=JSONObject(saved)
        BleTrialSelection(BenchCandidateRef(j.getString("digest"),j.getString("family"),j.getString("path")),j.getString("version"),j.getString("recovery"))
    }.getOrNull()
    suspend fun importCandidate(uri:Uri) {
        check(controller.invalidate()){"Wait for the Bluetooth operation to finish"}
        clearMessage()
        val reference=cache.importLocal(uri)
        val candidate=cache.inspectBleTrial(reference)
        check(controller.invalidate()){"A Bluetooth operation started while importing"}
        val saved=JSONObject().put("digest",reference.digest).put("family",reference.familySha256).put("path",reference.cachePath)
            .put("version",candidate.version).put("recovery",candidate.recoveryVersion)
        check(preferences.edit().putString("candidate",saved.toString()).commit()){"Firmware selection could not be saved"}
        mutableSelection.value=BleTrialSelection(reference,candidate.version,candidate.recoveryVersion)
    }
    fun fail(message:String){if(!controller.state.value.busy){controller.invalidate();mutableMessage.value=message}}
    fun clearMessage(){mutableMessage.value=null}
    private suspend fun saveReport(state:BleTrialState,address:String)=withContext(Dispatchers.IO) {
        val j=JSONObject(BleTrialReport.snapshot(state,address,selection.value?.reference?.digest,selection.value?.version,
            app.packageManager.getPackageInfo(app.packageName,0).versionName ?: "unknown",Build.VERSION.SDK_INT,Build.VERSION.RELEASE,diagnostics.events))
            .put("observedAtMillis",System.currentTimeMillis())
            .put("operation",if(state.pairing)"zigbee_pairing" else "firmware_update")
            .put("interpretation",if(state.pairing)"Request acknowledgment does not establish successful Zigbee association" else "Image verification and reset acknowledgement do not establish lamp, buttons or Zigbee operation")
        val output=report.startWrite()
        try{output.write(j.toString(2).toByteArray());report.finishWrite(output)}catch(failure:Throwable){report.failWrite(output);throw failure}
    }
    val reportAvailable get()=report.baseFile.exists()||File(report.baseFile.path+".bak").exists()
    suspend fun reportBytes():ByteArray?=withContext(Dispatchers.IO) {
        if(!report.baseFile.exists()&&!File(report.baseFile.path+".bak").exists())null
        else report.openRead().use{input->input.readBytes().also{require(it.size<=65536)}}
    }
}
internal object AndroidBleTrialOwner {
    private var owner:BleTrialRuntime?=null
    @Synchronized fun get(context:Context):BleTrialRuntime=owner ?: BleTrialRuntime(context).also{owner=it}
    @Synchronized internal fun installForTest(replacement:BleTrialRuntime?){check(owner?.controller?.state?.value?.busy!=true);owner=replacement}
}
private class TrialCheckedTransport(private val delegate:BleTransport,private val check:()->Unit):BleTransport,MigrationBootTransport,ZigbeePairingTransport {
    override suspend fun connect(address:String){check();delegate.connect(address);check()}
    override suspend fun identity():RuntimeIdentity {check();return delegate.identity().also{check()}}
    override suspend fun identityV2():RuntimeIdentity {check();return delegate.identityV2().also{check()}}
    override suspend fun pairingCapabilities():ZigbeePairingCapabilities {check();return (delegate as? ZigbeePairingTransport ?: error("Pairing unavailable")).pairingCapabilities().also{check()}}
    override suspend fun startZigbeePairing():ResetAck {check();return (delegate as? ZigbeePairingTransport ?: error("Pairing unavailable")).startZigbeePairing()}
    override suspend fun images():RemoteImages {check();return delegate.images().also{check()}}
    override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){check();delegate.upload(data){check();onAck(it)}}
    override suspend fun reset():ResetAck {check();return delegate.reset().also{check()}}
    override suspend fun bootMigration(expectedHash:String):ResetAck {check();return (delegate as? MigrationBootTransport ?: error("Migration command unavailable")).bootMigration(expectedHash).also{check()}}
    override suspend fun close()=delegate.close()
}
