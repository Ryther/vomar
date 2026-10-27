package org.openvimar.updater

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Binder
import android.os.Build
import android.os.IBinder
import kotlinx.coroutines.*

/** Android lifetime/notification host attached to the single process command owner. */
class UpdateService : Service() {
    inner class LocalBinder : Binder() { val service: UpdateService get() = this@UpdateService }
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private lateinit var controller: SessionController
    private val historyLifetime=HistoryServiceLifetime()
    val status get() = controller.status
    val presentation get() = controller.presentation
    fun inspect(): Boolean = controller.inspect()
    fun refresh(): Boolean = controller.refresh()
    fun importDocument(source: String): Boolean = controller.importDocument(source)
    val commonBootstrapAvailable get()=controller.commonBootstrapAvailable
    val bootstrapResetUncertain get()=controller.bootstrapResetUncertain
    fun startCommonBootstrap(allowResetRetry:Boolean=false):Boolean {foreground();return controller.startCommonBootstrap(allowResetRetry).also{if(!it&&!controller.running)stopForeground(STOP_FOREGROUND_REMOVE)}}
    val reportedIdentity get()=controller.reportedIdentity
    fun inspectIdentity(address:String):Boolean=controller.inspectIdentity(address)
    val reportedBootHistory get()=controller.reportedBootHistory
    val lastBootHistoryAddress get()=controller.lastBootHistoryAddress
    val lastBootHistoryMessage get()=controller.lastBootHistoryMessage
    /** Accepted explicit reads retain a started foreground lifetime across Activity rotation. */
    fun inspectBootHistory(address:String,expectedUid:List<String>?=null):Boolean {
        var accepted=false
        return try {
            foreground()
            accepted=controller.inspectBootHistory(address,expectedUid)
            if(accepted)startService(Intent(this,UpdateService::class.java).setAction(KEEP_HISTORY_OWNER))
            else if(!controller.running)stopForeground(STOP_FOREGROUND_REMOVE)
            accepted
        }catch(failure:Exception){
            if(accepted)controller.stop()
            controller.notifyFailure(failure.message ?: "Android could not retain the diagnostic connection. Keep the app open and retry.")
            if(!controller.running)stopForeground(STOP_FOREGROUND_REMOVE)
            false
        }
    }
    val commonReleasePending get()=controller.commonReleasePending
    fun selectCommonTarget(address:String):Boolean=controller.selectCommonTarget(address)
    val running: Boolean get() = controller.running

    override fun onCreate() {
        super.onCreate()
        controller = AndroidSessionOwner.get(this)
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel("update", "Dimmer connection", NotificationManager.IMPORTANCE_LOW))
        scope.launch {
            controller.busy.collect { busy ->
                if (!busy) {
                    stopForeground(STOP_FOREGROUND_REMOVE)
                    historyLifetime.releaseOnIdle()?.let{stopSelf(it)}
                }
            }
        }
    }

    override fun onBind(intent: Intent): IBinder = LocalBinder()

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            KEEP_HISTORY_OWNER -> {
                // Keeps the already accepted owner; never dispatches a second diagnostic.
                // A late delivery after completion must not create an idle notification.
                if(historyLifetime.keepAlive(startId,controller.running)){foreground()}
                else {stopForeground(STOP_FOREGROUND_REMOVE);stopSelf(startId)}
            }
            START, RESUME, PROBE, BOOTSTRAP -> {
                try {
                    foreground()
                    val accepted = if(intent.action==BOOTSTRAP) controller.startCommonBootstrap(intent.getBooleanExtra(CONFIRMED,false))
                        else if (intent.action == PROBE) controller.probe()
                        else controller.start(intent.action == RESUME,
                            intent.getStringExtra(OFFER), intent.getBooleanExtra(CONFIRMED, false))
                    if (!accepted && !controller.running) stopForeground(STOP_FOREGROUND_REMOVE)
                } catch (failure: Exception) {
                    controller.notifyFailure(failure.message ?: "Android could not start the connection. Keep the app open and retry.")
                    if (!controller.running) stopForeground(STOP_FOREGROUND_REMOVE)
                }
            }
            IMPORT -> intent.getStringExtra(SOURCE)?.let { controller.importDocument(it) }
            STOP -> controller.stop()
        }
        return START_NOT_STICKY
    }

    private fun foreground() {
        val open = android.app.PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), android.app.PendingIntent.FLAG_IMMUTABLE)
        val notification = Notification.Builder(this, "update")
            .setSmallIcon(android.R.drawable.stat_sys_upload).setContentTitle("Vomar: dimmer connection")
            .setContentText("Open the app to see progress or stop the operation.")
            .setContentIntent(open).setOngoing(true).build()
        if (Build.VERSION.SDK_INT >= 29) startForeground(1, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        else startForeground(1, notification)
    }

    suspend fun prepareResume(): SessionController.ResumeOffer = controller.prepareResume()
    fun stopUpdate() = controller.stop()
    fun confirmOperator(online: Boolean) {
        check(controller.confirmOperator(online)) { "Wait for the current operation to finish" }
    }
    suspend fun report(): ByteArray = controller.report()

    override fun onDestroy() {
        controller.detachUpdateHost()
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val KEEP_HISTORY_OWNER="org.openvimar.updater.KEEP_HISTORY_OWNER"
        const val BOOTSTRAP = "org.openvimar.updater.BOOTSTRAP"
        const val START = "org.openvimar.updater.START"
        const val RESUME = "org.openvimar.updater.RESUME"
        const val PROBE = "org.openvimar.updater.PROBE"
        const val IMPORT = "org.openvimar.updater.IMPORT"
        const val STOP = "org.openvimar.updater.STOP"
        const val CONFIRMED = "confirmedResetRetry"
        const val OFFER = "resumeOffer"
        const val SOURCE = "importSource"
    }
}
