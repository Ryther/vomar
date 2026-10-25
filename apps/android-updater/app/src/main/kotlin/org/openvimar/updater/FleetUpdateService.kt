package org.openvimar.updater

import android.Manifest
import android.app.*
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.collectLatest

/** User-started foreground lifetime for the durable fleet scheduler. No automatic restart. */
class FleetUpdateService:Service(){
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
    private lateinit var runtime:FleetRuntime
    private var observer:Job?=null
    private var idleStop=false
    override fun onCreate(){
        super.onCreate()
        runtime=AndroidFleetOwner.get(this,AndroidNetworkOwner.get(this).executor)
        getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel(CHANNEL,"Device updates",NotificationManager.IMPORTANCE_LOW))
    }
    override fun onBind(intent:Intent):IBinder?=null
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
        val action=intent?.action
        if(action !in setOf(START,RESUME,NEARBY,RETURN)){idleStop=true;stopSelf(startId);return START_NOT_STICKY}
        try{
            foreground()
            val group=requireNotNull(intent?.getStringExtra(GROUP))
            require(runtime.queue.groups.value.any{it.id==group}){"This update group is no longer available"}
            when(action){START->runtime.queue.start(group);RESUME->runtime.queue.resume(group);NEARBY->runtime.queue.confirmNearby(requireNotNull(requireNotNull(intent).getStringExtra(JOB)))
                RETURN->{val g=runtime.queue.groups.value.first{it.id==group};val job=g.jobs.first{it.id==intent?.getStringExtra(JOB)};runtime.queue.confirmReturn(job.id,g.release.digest,job.device.uid)}
            }
            mutableStatus.value=""
            observer?.cancel()
            observer=scope.launch{
                runtime.queue.groups.collectLatest{groups->
                    val active=groups.flatMap{it.jobs}.count{it.state==FleetJobState.RUNNING}
                    if(active==0)delay(100)
                    if(active==0&&!withContext(Dispatchers.IO){runtime.queue.hasActiveWork()}){idleStop=true;stopForeground(STOP_FOREGROUND_REMOVE);stopSelf(startId)}
                    else {idleStop=false;getSystemService(NotificationManager::class.java).notify(NOTIFICATION,notification("$active ${if(active==1)"dimmer" else "dimmers"} updating. Open Activity for progress."))}
                }
            }
        }catch(e:Exception){
            mutableStatus.value=e.message?:"Android could not start updates. Keep the app open and try again."
            runtime.queue.pauseAll();idleStop=true;stopForeground(STOP_FOREGROUND_REMOVE);stopSelf(startId)
        }
        return START_NOT_STICKY
    }
    private fun foreground(){
        val types=ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC or
            if(Build.VERSION.SDK_INT<31||checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)==PackageManager.PERMISSION_GRANTED)ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE else 0
        if(Build.VERSION.SDK_INT>=29)startForeground(NOTIFICATION,notification("Checking the selected update group…"),types)
        else startForeground(NOTIFICATION,notification("Checking the selected update group…"))
    }
    private fun notification(message:String)=Notification.Builder(this,CHANNEL)
        .setSmallIcon(android.R.drawable.stat_sys_upload).setContentTitle("Vimar updates")
        .setContentText(message).setOngoing(true).setContentIntent(PendingIntent.getActivity(this,3,Intent(this,MainActivity::class.java),PendingIntent.FLAG_IMMUTABLE)).build()
    override fun onTimeout(startId:Int,fgsType:Int){runtime.queue.pauseAll();idleStop=true;mutableStatus.value="Android paused background work. Reopen Activity and check device status before resuming.";stopForeground(STOP_FOREGROUND_REMOVE);stopSelf()}
    override fun onDestroy(){if(!idleStop)runtime.queue.pauseAll();scope.cancel();super.onDestroy()}
    companion object{
        const val START="org.openvimar.updater.FLEET_START"
        const val RESUME="org.openvimar.updater.FLEET_RESUME"
        const val RETURN="org.openvimar.updater.FLEET_RETURN"
        const val NEARBY="org.openvimar.updater.FLEET_NEARBY"
        private const val GROUP="group";private const val JOB="job";private const val CHANNEL="fleet";private const val NOTIFICATION=3
        private val mutableStatus=MutableStateFlow("")
        internal val status=mutableStatus.asStateFlow()
        internal fun command(context:Context,action:String,group:String,job:String?=null){
            val intent=Intent(context,FleetUpdateService::class.java).setAction(action).putExtra(GROUP,group).putExtra(JOB,job)
            try{context.startForegroundService(intent)}catch(e:Exception){mutableStatus.value=e.message?:"Android could not start this update. Keep the app open and try again."}
        }
    }
}
