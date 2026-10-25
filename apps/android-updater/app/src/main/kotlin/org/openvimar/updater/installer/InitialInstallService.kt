package org.openvimar.updater.installer

import android.app.*
import android.content.*
import android.content.pm.ServiceInfo
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.net.Uri
import android.os.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject
import org.openvimar.installer.*
import org.openvimar.updater.R
import java.io.IOException
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec
import java.util.UUID
import java.util.concurrent.Executors

/** Explicit user-started foreground host. Process recreation restores a report,
 * never an execution grant, target inspection, USB lease or bench approval. */
class InitialInstallService:Service() {
    inner class LocalBinder:Binder(){val service get()=this@InitialInstallService}
    private val worker=Executors.newSingleThreadExecutor()
    private val policy=FirstInstallHostPolicy()
    private val main=Handler(Looper.getMainLooper())
    private val mutableState=MutableStateFlow(InitialInstallSnapshot())
    internal val state=mutableState.asStateFlow()
    private val target=MutableStateFlow<TargetIdentity?>(null)
    internal val inspectedTarget=target.asStateFlow()
    private val observedWatchdog=MutableStateFlow<ObservedWatchdogProfile?>(null)
    internal val inspectedWatchdog=observedWatchdog.asStateFlow()
    private val retainedOptions=MutableStateFlow<List<InitialInstallResumeOption>>(emptyList())
    internal val resumeOptions=retainedOptions.asStateFlow()
    private val inspection=MutableStateFlow("Inspect the selected USB target read-only")
    internal val inspectionMessage=inspection.asStateFlow()
    private val inspectionLock=Any();private var inspectedDeviceName:String?=null
    @Volatile private var controller:InitialInstallController?=null
    @Volatile private var destroyed=false
    private lateinit var persistence:AndroidInitialInstallPersistence
    private var wake:PowerManager.WakeLock?=null
    private var timeout:Runnable?=null
    internal val receipt get()=controller?.receipt
    private val detached=object:BroadcastReceiver(){override fun onReceive(context:Context,intent:Intent){
        @Suppress("DEPRECATION") val device=if(Build.VERSION.SDK_INT>=33)intent.getParcelableExtra(UsbManager.EXTRA_DEVICE,UsbDevice::class.java) else intent.getParcelableExtra(UsbManager.EXTRA_DEVICE) as? UsbDevice
        val relevant=controller?.snapshot?.request?.deviceName==device?.deviceName||synchronized(inspectionLock){inspectedDeviceName==device?.deviceName}
        if(device!=null&&relevant){clearInspection();cancelInstall()}
    }}
    override fun onCreate(){
        super.onCreate();persistence=AndroidInitialInstallPersistence(this)
        getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel(CHANNEL,"Initial USB installation",NotificationManager.IMPORTANCE_LOW))
        val filter=IntentFilter(UsbManager.ACTION_USB_DEVICE_DETACHED)
        if(Build.VERSION.SDK_INT>=33)registerReceiver(detached,filter,Context.RECEIVER_NOT_EXPORTED) else registerReceiver(detached,filter)
        val saved=persistence.diagnostic()
        if(saved.has("requestId"))mutableState.value=InitialInstallSnapshot(message="Previous report retained; no target, approval or operation resumed")
    }
    override fun onBind(intent:Intent):IBinder=LocalBinder()
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
        when(intent?.action){
            OPEN->if(policy.current()!=null)runCatching{foreground("Owner-approved operation is active")}.onFailure{serviceError(it)}
                else{stopForeground(STOP_FOREGROUND_REMOVE);stopSelf()}
            CANCEL->cancelInstall()
        }
        return START_NOT_STICKY
    }
    private fun clearInspection(){synchronized(inspectionLock){inspectedDeviceName=null;target.value=null;observedWatchdog.value=null;retainedOptions.value=emptyList()}}
    internal fun inspectTarget(deviceName:String){
        try{
            require(deviceName.isNotBlank()&&!destroyed)
            require(mutableState.value.phase in setOf(InitialInstallPhase.IDLE,InitialInstallPhase.FAILED,InitialInstallPhase.CANCELLED,InitialInstallPhase.STARTED)){"Finish the current held transaction first"}
            val ticket=policy.admit(UUID.randomUUID().toString())?:throw IOException("Another initial-install operation is active")
            clearInspection();inspection.value="Reading live FICR and geometry without halt/reset"
            worker.execute{
                try{ticket.checkActive();val found=AndroidInitialInstallIdentity.inspect(this,deviceName){ticket.cancelled||destroyed};ticket.checkActive()
                    val options=persistence.resumeOptions(found.target);ticket.checkActive()
                    synchronized(inspectionLock){inspectedDeviceName=deviceName;target.value=found.target;observedWatchdog.value=found.watchdog;retainedOptions.value=options}
                    inspection.value=if(!found.watchdog.active)"Live identity/geometry and inactive watchdog read; no halt/reset attempted"
                        else if(runCatching{found.watchdog.requireAcquisitionShape()}.isSuccess)"Live identity read; watchdog active and paused on HALT. A signed loader handoff is required; no halt/reset attempted"
                        else "Live identity read; active watchdog profile is unsupported for capture. No halt/reset attempted"}
                catch(error:Exception){clearInspection();inspection.value=error.message?:"Identity inspection failed"}
                finally{policy.finished(ticket);main.post{if(policy.current()==null)stopForeground(STOP_FOREGROUND_REMOVE)}}
            }
        }catch(error:Exception){inspection.value=error.message?:"Identity inspection unavailable"}
    }
    internal fun beginQualified(request:InstallCaptureRequest,rawZip:ByteArray)=begin(request,rawZip,false)
    internal fun beginCandidate(request:InstallCaptureRequest,rawZip:ByteArray)=begin(request,rawZip,true)
    internal fun prepareResumeQualified(request:InstallCaptureRequest,rawZip:ByteArray,originalUri:Uri)=begin(request,rawZip,false,originalUri)
    internal fun prepareResumeCandidate(request:InstallCaptureRequest,rawZip:ByteArray,originalUri:Uri)=begin(request,rawZip,true,originalUri)
    private fun begin(request:InstallCaptureRequest,rawZip:ByteArray,candidate:Boolean,originalUri:Uri?=null){
        var ticket:FirstInstallHostPolicy.Ticket?=null
        try{
            check(!destroyed&&controller==null){"Choose a new session after the previous transaction"}
            require(!request.allowResetCatch){"Pre-backup reset is unsupported; hardware watchdog must be inactive"}
            require(rawZip.size in 22..2*1024*1024);val frozen=rawZip.copyOf()
            ticket=policy.admit(request.requestId)?:throw IOException("Another initial-install operation is active")
            synchronized(inspectionLock){require(inspectedDeviceName==request.deviceName&&target.value==request.target){"A fresh live inspection in this service is required"};inspectedDeviceName=null;target.value=null;retainedOptions.value=emptyList()}
            // Synchronous: binder calls do not race the asynchronous OPEN intent.
            foreground("Verifying the explicitly reviewed signed common artifact")
            val preparing=InitialInstallSnapshot(InitialInstallPhase.CONNECTING,request,
                message="Verifying reviewed common artifact; no target opened yet",candidate=candidate,resume=originalUri!=null,
                mutationMayHaveStarted=originalUri!=null,commitMayHaveBeenWritten=originalUri!=null)
            mutableState.value=preparing
            try{persistence.saveState(preparing)}catch(error:Exception){mutableState.value=preparing.copy(journalFailure=true);throw error}
            val owned=ticket
            worker.execute{
                try{
                    owned.checkActive();val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(resources.openRawResource(R.raw.firmware_public).use{it.readBytes()}))
                    @Suppress("DEPRECATION") val version=packageManager.getPackageInfo(packageName,0).versionName?:error("App version unavailable")
                    val inspected=if(candidate)CandidateRelease.inspect(frozen,key,version) else null
                    val qualified=if(candidate)null else CommonRelease.verify(frozen,key,version)
                    require((inspected?.releaseSha256?:qualified?.releaseSha256)==request.reviewedReleaseSha256)
                    owned.checkActive();holdAwake(owned)
                    val retained=if(originalUri!=null){
                        val option=persistence.resumeOptions(request.target).single()
                        require(option.releaseSha256==request.reviewedReleaseSha256&&option.originalAvailable){"Selected release/original does not match retained transaction"}
                        persistence.reopenRetained(option.bindingId)
                    }else null
                    val reopened=if(retained!=null)retained.reopenOriginal(checkNotNull(originalUri).toString()){document->
                        AndroidInitialInstallDocuments.reopenExisting(contentResolver,Uri.parse(document)){owned.cancelled||destroyed}
                    }else null
                    owned.checkActive()
                    val active=InitialInstallController({r,cancelled,proof->AndroidInitialInstallConnection.open(this,r,cancelled={owned.cancelled||destroyed||cancelled()},
                        handoff={generation->inspected?.authorizeWatchdogHandoff(r.target,generation)?:qualified?.authorizeWatchdogHandoff(r.target,generation)},verifiedStart=proof)},persistence,
                        FileInstallJournal(persistence.journalDirectory),resumeConnect={r,cancelled,authority->
                            AndroidInitialInstallConnection.open(this,r,cancelled={owned.cancelled||destroyed||cancelled()},
                                handoff={generation->inspected?.authorizeWatchdogHandoff(r.target,generation)?:qualified?.authorizeWatchdogHandoff(r.target,generation)},resume=authority)
                        }){snapshot->mutableState.value=snapshot;notifyState(snapshot)}
                    controller=active;if(owned.cancelled||destroyed)active.cancel()
                    if(reopened!=null){
                        val head=checkNotNull(retained).checkpoint.headSha256
                        if(inspected!=null)active.prepareResumeCandidate(request,inspected,reopened,persistence.resumeJournal,head)
                        else active.prepareResumeQualified(request,checkNotNull(qualified),reopened,persistence.resumeJournal,head)
                    }else if(inspected!=null)active.beginCandidate(request,inspected) else active.beginQualified(request,checkNotNull(qualified))
                }catch(error:Exception){serviceError(error,request,candidate)}
                finally{completeIfTerminal(owned)}
            }
        }catch(error:Exception){ticket?.let(policy::finished);serviceError(error,request,candidate)
            main.post{if(policy.current()==null){stopForeground(STOP_FOREGROUND_REMOVE);stopSelf()}}}
    }
    internal fun exportOriginal(uri:Uri,expectedRequestId:String){
        action(expectedRequestId){ticket,active->
            require(active.snapshot.phase==InitialInstallPhase.AWAITING_EXPORT)
            active.export(AndroidInitialInstallDocuments.export(contentResolver,uri){ticket.cancelled||destroyed})
        }
    }
    internal fun install(review:InstallOwnerReview)=action(review.requestId){_,active->active.install(review)}
    internal fun resume(review:ResumeOwnerReview)=action(review.requestId){_,active->active.resume(review)}
    internal fun startVerifiedTarget(review:InstallOwnerReview){
        try{
            val active=checkNotNull(controller);require(active.snapshot.phase==InitialInstallPhase.VERIFIED_HALTED&&active.snapshot.request?.requestId==review.requestId)
            val ticket=policy.admit(review.requestId)?:throw IOException("Another initial-install operation is active")
            foreground("Verifying the completed image before explicit reset and start")
            worker.execute{try{ticket.checkActive();holdAwake(ticket);active.startVerified(review)}catch(error:Exception){serviceError(error)}finally{completeIfTerminal(ticket)}}
        }catch(error:Exception){serviceError(error)}
    }
    private fun action(requestId:String,operation:(FirstInstallHostPolicy.Ticket,InitialInstallController)->Unit){
        try{
            val ticket=checkNotNull(policy.current());val active=checkNotNull(controller)
            require(ticket.requestId==requestId&&active.snapshot.request?.requestId==requestId){"Stale document/dialog request"}
            worker.execute{try{ticket.checkActive();require(active.snapshot.request?.requestId==requestId);operation(ticket,active)}
                catch(error:Exception){serviceError(error)}finally{completeIfTerminal(ticket)}}
        }catch(error:Exception){serviceError(error)}
    }
    internal fun cancelInstall(){
        val ticket=policy.current();policy.cancel();val active=controller;active?.cancel();clearInspection()
        if(!destroyed)worker.execute{try{active?.cancelAndClose();active?.let{mutableState.value=it.snapshot}}
            catch(error:Exception){serviceError(error)}finally{ticket?.let(::completeIfTerminal)}}
    }
    internal fun newSession(){
        try{
            check(!destroyed&&policy.current()==null)
            require(mutableState.value.phase in setOf(InitialInstallPhase.IDLE,InitialInstallPhase.STARTED,InitialInstallPhase.CANCELLED,InitialInstallPhase.FAILED))
            controller=null;clearInspection();mutableState.value=InitialInstallSnapshot(message="New session; retained originals/journals were not deleted")
            inspection.value="Inspect the next selected USB target read-only"
        }catch(error:Exception){serviceError(error)}
    }
    internal fun diagnostic():JSONObject=persistence.diagnostic()
    private fun holdAwake(ticket:FirstInstallHostPolicy.Ticket){
        wake=(getSystemService(POWER_SERVICE) as PowerManager).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"openvimar:first-install").also{it.acquire(MAX_MILLIS+30_000)}
        timeout=Runnable{if(policy.current()===ticket)cancelInstall()}.also{main.postDelayed(it,MAX_MILLIS)}
    }
    private fun completeIfTerminal(ticket:FirstInstallHostPolicy.Ticket){
        if(policy.current()!==ticket)return // A drained old callback never owns a new request's resources.
        val phase=controller?.snapshot?.phase?:mutableState.value.phase
        if(phase !in TERMINAL&&!ticket.cancelled)return
        // Called only on the serialized worker after controller cleanup/USB close.
        timeout?.let(main::removeCallbacks);timeout=null
        runCatching{if(wake?.isHeld==true)wake?.release()};wake=null;policy.finished(ticket)
        main.post{if(policy.current()==null){stopForeground(STOP_FOREGROUND_REMOVE);stopSelf()}}
    }
    private fun serviceError(error:Throwable,request:InstallCaptureRequest?=null,candidate:Boolean=false){
        val base=controller?.snapshot?:mutableState.value
        val next=if(controller==null)InitialInstallSnapshot(InitialInstallPhase.FAILED,request,message=(error.message?:error.javaClass.simpleName).take(1024),candidate=candidate,journalFailure=base.journalFailure,
            resume=base.resume,mutationMayHaveStarted=base.mutationMayHaveStarted,commitMayHaveBeenWritten=base.commitMayHaveBeenWritten)
            else base.copy(message=(error.message?:error.javaClass.simpleName).take(1024))
        mutableState.value=next;runCatching{persistence.saveState(next)}
    }
    private fun notification(message:String):Notification {
        val open=PendingIntent.getActivity(this,74,Intent().setClassName(packageName,"org.openvimar.updater.InitialInstallActivity"),PendingIntent.FLAG_IMMUTABLE)
        val cancel=PendingIntent.getService(this,75,Intent(this,InitialInstallService::class.java).setAction(CANCEL),PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.stat_sys_download).setContentTitle("Initial USB installation")
            .setContentText(message).setContentIntent(open).setOngoing(true).addAction(Notification.Action.Builder(null,"Stop",cancel).build()).build()
    }
    private fun foreground(message:String){val notice=notification(message);if(Build.VERSION.SDK_INT>=29)startForeground(NOTIFICATION,notice,ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE) else startForeground(NOTIFICATION,notice)}
    private fun notifyState(snapshot:InitialInstallSnapshot){getSystemService(NotificationManager::class.java).notify(NOTIFICATION,notification(snapshot.message))}
    override fun onDestroy(){
        destroyed=true;policy.destroy();val active=controller;active?.cancel();runCatching{unregisterReceiver(detached)}
        worker.execute{try{active?.cancelAndClose()}finally{timeout?.let(main::removeCallbacks);runCatching{if(wake?.isHeld==true)wake?.release()};policy.current()?.let(policy::finished)}}
        worker.shutdown();super.onDestroy()
    }
    companion object {
        const val OPEN="org.openvimar.updater.INITIAL_INSTALL_OPEN"
        const val CANCEL="org.openvimar.updater.INITIAL_INSTALL_CANCEL"
        private const val CHANNEL="dk-first-install";private const val NOTIFICATION=74
        private const val MAX_MILLIS=2*60*60*1000L
        private val TERMINAL=setOf(InitialInstallPhase.VERIFIED_HALTED,InitialInstallPhase.STARTED,InitialInstallPhase.CANCELLED,InitialInstallPhase.FAILED)
    }
}
