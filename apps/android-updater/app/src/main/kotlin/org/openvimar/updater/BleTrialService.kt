package org.openvimar.updater

import android.app.*
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import kotlinx.coroutines.*

/** Started only by explicit Inspect/Start/Stop. No sticky/redelivered authority. */
class BleTrialService:Service() {
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
    private var operation:Job?=null
    private val runtime get()=AndroidBleTrialOwner.get(this)
    override fun onBind(intent:Intent?):IBinder?=null
    override fun onCreate(){
        super.onCreate()
        getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel("ble-trial","Bluetooth update",NotificationManager.IMPORTANCE_LOW))
    }
    override fun onStartCommand(intent:Intent?,flags:Int,startId:Int):Int {
        if(intent?.action==STOP){operation?.cancel();if(operation==null)stopSelf();return START_NOT_STICKY}
        if(intent?.action !in setOf(INSPECT,EXECUTE)){stopSelf(startId);return START_NOT_STICKY}
        if(operation?.isActive==true||runtime.controller.state.value.busy)return START_NOT_STICKY
        try{foreground()}catch(failure:Exception){runtime.fail("Android could not keep the Bluetooth update active: ${failure.message}");stopSelf(startId);return START_NOT_STICKY}
        runtime.clearMessage()
        operation=scope.launch {
            try{
                if(intent!!.action==INSPECT)runtime.controller.inspect(requireNotNull(intent.getStringExtra(ADDRESS)){"Choose a Bluetooth dimmer"},intent.getStringArrayListExtra("expectedUid"))
                else runtime.controller.execute(requireNotNull(intent.getStringExtra(REVIEW)){"Inspect this dimmer again"},intent.getBooleanExtra(RETRY,false))
            }catch(cancelled:CancellationException){throw cancelled}
            catch(failure:Exception){runtime.fail(failure.message ?: "The Bluetooth update could not start")}
            finally{stopForeground(STOP_FOREGROUND_REMOVE);stopSelf()}
        }
        return START_NOT_STICKY
    }
    private fun foreground(){
        val open=PendingIntent.getActivity(this,61,Intent(this,BleTrialActivity::class.java),PendingIntent.FLAG_IMMUTABLE)
        val stop=PendingIntent.getService(this,62,Intent(this,BleTrialService::class.java).setAction(STOP),PendingIntent.FLAG_IMMUTABLE)
        val notification=Notification.Builder(this,"ble-trial").setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle("Vimar: Bluetooth update").setContentText("Open to see progress. Stop preserves the saved transfer state.")
            .setContentIntent(open).setOngoing(true).addAction(Notification.Action.Builder(null,"Stop",stop).build()).build()
        if(Build.VERSION.SDK_INT>=29)startForeground(6,notification,ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)else startForeground(6,notification)
    }
    override fun onDestroy(){operation?.cancel();scope.cancel();super.onDestroy()}
    companion object {
        const val INSPECT="org.openvimar.updater.BLE_TRIAL_INSPECT"
        const val EXECUTE="org.openvimar.updater.BLE_TRIAL_EXECUTE"
        const val STOP="org.openvimar.updater.BLE_TRIAL_STOP"
        const val ADDRESS="address";const val REVIEW="review";const val RETRY="confirmedResetRetry"
    }
}
