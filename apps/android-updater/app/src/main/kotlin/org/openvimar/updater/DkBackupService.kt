package org.openvimar.updater

import android.app.*
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.usb.UsbManager
import android.os.*
import android.util.AtomicFile
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.io.File
import java.io.IOException
import java.time.Instant
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

internal data class DkBackupServiceState(val running: Boolean=false,val message: String="No backup is running",
    val progress: DkBackupProgress?=null,val verifiedFile: File?=null,val diagnostic: DkBackupDiagnostic?=null)

/** User-started connected-device host. Activity rotation/background does not own
 * this job. A killed service never resumes acquisition or exports automatically. */
class DkBackupService: Service() {
    inner class LocalBinder: Binder() { val service get()=this@DkBackupService }
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
    private val cancelled=AtomicBoolean(false)
    private val mutableState=MutableStateFlow(DkBackupServiceState())
    internal val state=mutableState.asStateFlow()
    private var work: Job?=null
    private lateinit var store: DkBackupStore
    private val diagnosticFile by lazy {AtomicFile(File(filesDir,"dk-backup-diagnostic.bin"))}

    private fun persistDiagnostic(snapshot: DkBackupDiagnostic) {
        val bytes=snapshot.encode()
        val output=diagnosticFile.startWrite()
        try {output.write(bytes);diagnosticFile.finishWrite(output)}
        catch(error: Exception){diagnosticFile.failWrite(output);throw error}
    }

    override fun onCreate() {
        super.onCreate()
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL,"Verified USB backup",NotificationManager.IMPORTANCE_LOW))
        store=DkBackupStore(File(filesDir,DIRECTORY))
        store.cleanupIncomplete()
        val latest=store.latest()
        val saved=runCatching {diagnosticFile.openRead().use {input->
            val bytes=ByteArray(65537);var length=0
            while(length<bytes.size) {
                val count=input.read(bytes,length,bytes.size-length)
                if(count<0)break
                if(count==0)throw IOException("Incomplete diagnostic snapshot")
                length+=count
            }
            DkBackupDiagnostic.restore(bytes.copyOf(length))
        }}.getOrNull()
        if(saved!=null) {
            mutableState.value=DkBackupServiceState(message=saved.message,progress=saved.progress,verifiedFile=latest,diagnostic=saved)
            runCatching {persistDiagnostic(saved)}
        } else latest?.let {mutableState.value=DkBackupServiceState(message="Verified backup ready to save",verifiedFile=it)}
    }
    override fun onBind(intent: Intent): IBinder=LocalBinder()
    override fun onStartCommand(intent: Intent?,flags: Int,startId: Int): Int {
        when(intent?.action) {
            START -> if(work?.isActive!=true) {
                val requestId=intent.getStringExtra(REQUEST_ID)
                try {
                    require(requestId!=null && UUID.fromString(requestId).toString()==requestId) {"Backup request identity is missing or invalid"}
                    foreground("Preparing a read-only double backup")
                    startBackup(intent.getStringExtra(DEVICE) ?: throw IOException("USB device is missing"),requestId)
                } catch(error: Exception) {
                    val diagnostic=requestId?.let {DkBackupDiagnostic(it).failed(error,false)}
                    diagnostic?.let {runCatching {persistDiagnostic(it)}}
                    mutableState.value=DkBackupServiceState(message=error.message ?: "Backup could not start",diagnostic=diagnostic)
                    stopForeground(STOP_FOREGROUND_REMOVE);stopSelf()
                }
            }
            STOP -> {cancelBackup();if(work?.isActive!=true)stopSelf()}
        }
        return START_NOT_STICKY
    }
    internal fun cancelBackup() { cancelled.set(true) }

    private fun startBackup(name: String,requestId: String) {
        cancelled.set(false)
        var diagnostic=DkBackupDiagnostic(requestId)
            .observed("startedAt",Instant.now().toString())
            .observed("appVersion",packageManager.getPackageInfo(packageName,0).versionName ?: "Unknown")
        var lastPersist=0L
        fun publish(snapshot: DkBackupDiagnostic,verifiedFile: File?=null) {
            val now=SystemClock.elapsedRealtime()
            val checkpoint=snapshot.phase!=diagnostic.phase||!snapshot.running||snapshot.progress==null||now-lastPersist>=1000
            diagnostic=snapshot
            if(checkpoint) {runCatching {persistDiagnostic(snapshot)};lastPersist=now}
            mutableState.value=DkBackupServiceState(snapshot.running,snapshot.message,snapshot.progress,verifiedFile,snapshot)
        }
        publish(diagnostic)
        work=scope.launch {
            var lock: PowerManager.WakeLock?=null
            var usbLease:DkUsbOperationGate.Lease?=null
            try {
                val operationLease=DkUsbOperationGate.acquire("Read-only double backup") ?: throw IOException("The DK is in use by another operation. Wait for it to finish or stop it first.")
                usbLease=operationLease
                lock=(getSystemService(POWER_SERVICE) as PowerManager).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"openvimar:usb-backup")
                lock.acquire(DkSwdBackup.DEADLINE_MILLIS+30_000)
                val result=withTimeout(DkSwdBackup.DEADLINE_MILLIS+30_000) {
                    withContext(Dispatchers.IO) {
                        val context=currentCoroutineContext()
                        fun stopped()=cancelled.get()||!context.isActive
                        fun checkStopped() { operationLease.checkCurrent();if(stopped())throw IOException("Backup cancelled; no partial archive is available") }
                        val started=Instant.now()
                        publish(diagnostic.at(DkBackupPhase.USB_OPEN,"Opening the selected USB probe"))
                        val manager=getSystemService(USB_SERVICE) as UsbManager
                        val device=manager.deviceList.values.singleOrNull {it.deviceName==name}
                            ?: throw IOException("The selected USB device was disconnected")
                        if(!manager.hasPermission(device))throw IOException("USB permission is missing")
                        val descriptors=(0 until device.interfaceCount).map {index->
                            val port=device.getInterface(index)
                            DkUsbInterfaceDescriptor(index,port.id,port.alternateSetting,port.interfaceClass,
                                port.interfaceSubclass,port.interfaceProtocol,port.name,
                                (0 until port.endpointCount).map {n->port.getEndpoint(n).let {
                                    DkUsbEndpointDescriptor(it.address,it.attributes,it.maxPacketSize,it.interval)
                                }})
                        }
                        val selected=DkJlinkInterfaceSelector.select(device.vendorId,device.productId,descriptors)
                        val selectedPort=selected.port ?: throw IOException(selected.error)
                        val port=device.getInterface(selectedPort.index)
                        val endpoints=(0 until port.endpointCount).map(port::getEndpoint)
                        val input=endpoints.single {it.address==selected.input?.address}
                        val output=endpoints.single {it.address==selected.output?.address}
                        val connection=manager.openDevice(device) ?: throw IOException("Android could not open the DK")
                        var claimed=false
                        try {
                            checkStopped()
                            claimed=connection.claimInterface(port,false)
                            if(!claimed)throw IOException("J-Link interface is busy; close other USB tools")
                            publish(diagnostic.observed("usbVendorId",device.vendorId).observed("usbProductId",device.productId)
                                .observed("interfaceId",port.id).observed("inputEndpoint",input.address).observed("outputEndpoint",output.address)
                                .at(DkBackupPhase.USB_PROBE,"Reading probe firmware and reference voltage"))
                            val channel=DkSwdBufferedChannel(object:DkBulkChannel {
                                override fun write(bytes: ByteArray): Int {checkStopped();return connection.bulkTransfer(output,bytes,bytes.size,2000)}
                                override fun read(maxBytes: Int): ByteArray {
                                    checkStopped();val buffer=ByteArray(maxBytes)
                                    val count=connection.bulkTransfer(input,buffer,buffer.size,2000)
                                    checkStopped()
                                    if(count<=0)throw IOException("USB read timed out or target disconnected")
                                    return buffer.copyOf(count)
                                }
                            })
                            val probe=DkJlinkReadOnly.probe(channel)
                            publish(diagnostic.observed("probeFirmware",probe.firmware).observed("targetMillivolts",probe.targetMillivolts))
                            if(probe.targetMillivolts !in 1700..3600)throw IOException("Target reference voltage is outside 1.7–3.6 V")
                            publish(diagnostic.at(DkBackupPhase.SWD_INITIALIZATION,"Initializing the read-only SWD link"))
                            val session=DkSwdJlinkSession(channel,timeoutMillis=DkSwdBackup.DEADLINE_MILLIS,cancelled=::stopped)
                            session.initialize {key,value->publish(diagnostic.observed(key,value))}
                            publish(diagnostic.at(DkBackupPhase.TARGET_IDENTITY,"Reading and checking live target identity"))
                            session.identify {key,value->publish(diagnostic.observed(key,value))}
                            val source=session.openBackupSource()
                            publish(diagnostic.at(DkBackupPhase.ACQUIRING,"Reading the first backup pass"))
                            var lastNotification=0L
                            val captured=DkBackupCapture.read(source,cancelled=::stopped,progress={event->
                                publish(diagnostic.advanced(event))
                                val tick=SystemClock.elapsedRealtime()
                                if(tick-lastNotification>=1000) {lastNotification=tick;notifyProgress(event)}
                            })
                            checkStopped()
                            publish(diagnostic.at(DkBackupPhase.VERIFYING,"Comparing and verifying the complete backup"))
                            val verified=Instant.now()
                            val provenance=DkBackupProvenance(packageManager.getPackageInfo(packageName,0).versionName ?: "Unknown",
                                probe.firmware,probe.targetMillivolts,device.vendorId,device.productId,port.id,input.address,output.address,started,verified)
                            val archive=DkBackupArchive.create(captured.first,captured.second,captured.identity,provenance)
                            checkStopped()
                            publish(diagnostic.at(DkBackupPhase.PUBLISHING,"Saving the verified private backup"))
                            store.publish(archive,captured.identity,verified,cancelled=::stopped)
                        } finally {try {if(claimed)connection.releaseInterface(port)} finally {connection.close()}}
                    }
                }
                publish(diagnostic.completed(),result)
            } catch(error: Exception) {
                publish(diagnostic.failed(error,cancelled.get()||error is CancellationException))
            } finally {
                usbLease?.close()
                runCatching {if(lock?.isHeld==true)lock.release()}
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
            }
        }
    }

    private fun notification(message: String,progress: DkBackupProgress?=null): Notification {
        val open=PendingIntent.getActivity(this,71,Intent(this,DkUsbDiagnosticsActivity::class.java),PendingIntent.FLAG_IMMUTABLE)
        val stop=PendingIntent.getService(this,72,Intent(this,DkBackupService::class.java).setAction(STOP),PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.stat_sys_download)
            .setContentTitle("Read-only USB backup").setContentText(message).setContentIntent(open)
            .setOngoing(true).addAction(Notification.Action.Builder(null,"Stop",stop).build()).apply {
                if(progress!=null)setProgress(1000,(progress.completedBytes*1000/progress.totalBytes).toInt(),false)
            }.build()
    }
    private fun foreground(message: String) {
        val notification=notification(message)
        if(Build.VERSION.SDK_INT>=29)startForeground(NOTIFICATION,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        else startForeground(NOTIFICATION,notification)
    }
    private fun notifyProgress(progress: DkBackupProgress) {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION,notification("Pass ${progress.pass}/2: ${progress.region.name}",progress))
    }
    override fun onDestroy() {cancelled.set(true);scope.cancel();super.onDestroy()}
    companion object {
        const val START="org.openvimar.updater.DK_BACKUP_START"
        const val STOP="org.openvimar.updater.DK_BACKUP_STOP"
        const val DEVICE="deviceName"
        const val REQUEST_ID="backupRequestId"
        const val DIRECTORY="dk-verified-backups"
        private const val CHANNEL="dk-backup"
        private const val NOTIFICATION=71
    }
}
