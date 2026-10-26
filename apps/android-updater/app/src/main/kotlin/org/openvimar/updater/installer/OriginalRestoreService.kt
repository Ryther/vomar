package org.openvimar.updater.installer

import android.app.*
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.openvimar.installer.*
import org.openvimar.updater.R
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicBoolean

internal data class OriginalRestoreState(val busy:Boolean=false,val done:Int=0,val total:Int=0,val verified:Boolean=false,
    val mutationMayHaveStarted:Boolean=false,val message:String="Original backup is saved on this phone.",val backupSha256:String?=null)

/** Explicit foreground restoration only. Restart/bind never opens USB. */
class OriginalRestoreService:Service() {
    inner class LocalBinder:Binder(){val service get()=this@OriginalRestoreService}
    private val worker=Executors.newSingleThreadExecutor()
    private val cancelled=AtomicBoolean(false)
    private val mutableState=MutableStateFlow(OriginalRestoreState())
    internal val state=mutableState.asStateFlow()
    private val lock=Any()
    @Volatile private var destroyed=false
    override fun onBind(intent:Intent):IBinder=LocalBinder()
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
        if(intent?.action==STOP){cancelled.set(true);if(!mutableState.value.busy)stopSelf()}
        return START_NOT_STICKY
    }
    override fun onCreate(){super.onCreate();getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel(CHANNEL,"Original firmware restore",NotificationManager.IMPORTANCE_LOW))}
    private fun notice():Notification {
        val open=PendingIntent.getActivity(this,78,Intent().setClassName(packageName,"org.openvimar.updater.OriginalRestoreActivity").putExtra("backup",mutableState.value.backupSha256),PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        val stop=PendingIntent.getService(this,79,Intent(this,OriginalRestoreService::class.java).setAction(STOP),PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this,CHANNEL).setSmallIcon(android.R.drawable.stat_sys_download).setContentTitle("Restore original firmware")
            .setContentText(mutableState.value.message).setContentIntent(open).setOngoing(true).addAction(Notification.Action.Builder(null,"Stop",stop).build()).build()
    }
    internal fun start(hash:String,deviceName:String){
        synchronized(lock){check(!mutableState.value.busy&&!destroyed);cancelled.set(false);mutableState.value=OriginalRestoreState(busy=true,message="Checking backup and connected device…",backupSha256=hash)}
        val notification=notice()
        try{if(Build.VERSION.SDK_INT>=29)startForeground(78,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)else startForeground(78,notification)}
        catch(error:Exception){mutableState.value=OriginalRestoreState(message=error.message?:"Android could not start restore",backupSha256=hash);stopSelf();return}
        worker.execute{
            var connection:InitialInstallConnection?=null;var wake:PowerManager.WakeLock?=null;var uncertain=false;var completed:OriginalRestoreState?=null
            val started=System.nanoTime()
            fun stopped()=cancelled.get()||destroyed||System.nanoTime()-started>2L*60*60*1_000_000_000
            try{
                check(!stopped());val persistence=AndroidInitialInstallPersistence(this)
                val original=persistence.reopenOriginal(hash);val requestId=UUID.randomUUID().toString()
                val request=InstallCaptureRequest(requestId,deviceName,original.identity,hash)
                wake=(getSystemService(POWER_SERVICE) as PowerManager).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK,"openvimar:original-restore").also{it.acquire(2L*60*60*1000+30000)}
                var plan:OriginalRestorePlan?=null
                connection=AndroidInitialInstallConnection.open(this,request,::stopped,restore={generation->OriginalRestorePlan.review(original,requestId,generation).also{plan=it}})
                val active=checkNotNull(connection);val reviewed=checkNotNull(plan)
                val outcome=OriginalRestoreEngine().run(reviewed,active.lease.authorizer(reviewed.binding),
                    FileInstallJournal(java.io.File(filesDir,"dk-first-install/original-restores").toPath(),originalRestore=true),
                    onProgress={done,total->mutableState.value=mutableState.value.copy(done=done,total=total,message=if(done<total/2)"Restoring original firmware…" else "Verifying original firmware…")},
                    checkCancelled={check(!stopped()){"Restore stopped"}})
                if(outcome.verified)persistence.recordOriginalRestored(hash)
                uncertain=outcome.mutationMayHaveStarted
                completed=mutableState.value.copy(busy=false,verified=outcome.verified,mutationMayHaveStarted=uncertain,
                    message=if(outcome.verified)outcome.message else "${outcome.message}. Device remains paused; keep its backup and retry after reviewing the connection.")
            }catch(error:Exception){uncertain=uncertain||connection?.lease?.mutationMayHaveStarted==true;completed=OriginalRestoreState(mutationMayHaveStarted=uncertain,message=error.message?:"Restore failed",backupSha256=hash)}
            finally{
                val closing=runCatching{try{connection?.lease?.finish()}finally{connection?.close()}}
                if(closing.isFailure)completed=(completed?:mutableState.value).copy(busy=false,verified=false,message="USB cleanup failed. Device state is uncertain; keep power and the backup.")
                runCatching{if(wake?.isHeld==true)wake?.release()};stopForeground(STOP_FOREGROUND_REMOVE);stopSelf()
                // Re-enable UI admission only after USB/wake/foreground teardown.
                // A second review cannot overlap the previous owner's cleanup.
                synchronized(lock){mutableState.value=(completed?:OriginalRestoreState(message="Restore ended")).copy(busy=false)}
            }
        }
    }
    internal fun stop(){cancelled.set(true)}
    override fun onDestroy(){destroyed=true;cancelled.set(true);worker.shutdown();super.onDestroy()}
    companion object {const val STOP="org.openvimar.updater.ORIGINAL_RESTORE_STOP";private const val CHANNEL="original-restore"}
}
