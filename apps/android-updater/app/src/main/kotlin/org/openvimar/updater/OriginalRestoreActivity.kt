package org.openvimar.updater

import android.app.*
import android.content.*
import android.hardware.usb.UsbManager
import android.net.Uri
import android.os.*
import android.widget.*
import android.view.View
import androidx.core.content.ContextCompat
import kotlinx.coroutines.*
import org.openvimar.updater.installer.*
import java.util.UUID

/** Device-specific private backup. Selecting/rotating this screen is read-only. */
class OriginalRestoreActivity:Activity() {
    override fun attachBaseContext(base:Context)=super.attachBaseContext(NativeUi.themedContext(base))
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
    private var service:OriginalRestoreService?=null
    private var bound=false;private var observing:Job?=null;private var foreground=false
    private var hash:String?=null;private var selectedDevice:String?=null;private var pendingPermission:String?=null
    private lateinit var exportButton:Button;private lateinit var status:TextView;private lateinit var progress:ProgressBar;private lateinit var restore:android.widget.Button;private lateinit var stop:android.widget.Button
    private val manager by lazy{getSystemService(USB_SERVICE) as UsbManager}
    private val connection=object:ServiceConnection {
        override fun onServiceConnected(name:ComponentName,binder:IBinder){service=(binder as OriginalRestoreService.LocalBinder).service;observing=scope.launch{service!!.state.collect{render(it)}}}
        override fun onServiceDisconnected(name:ComponentName){service=null;status.text="USB service disconnected. Reopen the backup to continue.";restore.isEnabled=false}
    }
    private val permission=object:BroadcastReceiver(){override fun onReceive(context:Context,intent:Intent){
        if(intent.action!="$packageName.RESTORE_USB_PERMISSION"||intent.dataString!=pendingPermission)return
        pendingPermission=null
        val device=manager.deviceList.values.firstOrNull{it.deviceName==selectedDevice}
        if(device!=null&&manager.hasPermission(device)&&foreground)review(device.deviceName)else status.text="USB access was not granted. Select the DK again."
    }}
    override fun onCreate(saved:Bundle?){
        super.onCreate(saved);NativeUi.systemBars(this);hash=intent.getStringExtra("backup")?:saved?.getString("backup")
        val body=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(20.dp,12.dp,20.dp,24.dp);setBackgroundColor(getColor(R.color.ui_surface))}
        body.addView(NativeUi.taskHeader(this,"Original firmware"){finish()})
        body.addView(NativeUi.label(this,intent.getStringExtra("deviceName")?:"Saved backup",20,true),LinearLayout.LayoutParams(-1,-2).apply{topMargin=24.dp})
        body.addView(NativeUi.label(this,"The original firmware is saved privately on this phone. Restoring it replaces the custom firmware and its settings.",15,secondary=true),LinearLayout.LayoutParams(-1,-2).apply{topMargin=12.dp})
        status=NativeUi.status(this);body.addView(status,LinearLayout.LayoutParams(-1,-2).apply{topMargin=24.dp})
        progress=ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal).apply{max=1000;visibility=View.GONE};body.addView(progress)
        exportButton=NativeUi.button(this,"Export backup copy"){export()};body.addView(exportButton,LinearLayout.LayoutParams(-1,-2).apply{topMargin=16.dp})
        restore=NativeUi.button(this,"Restore original firmware",filled=true,danger=true){chooseProbe()};body.addView(restore)
        stop=NativeUi.button(this,"Stop restoration",danger=true){service?.stop()}.apply{visibility=View.GONE};body.addView(stop)
        val scroll=ScrollView(this).apply{isFillViewport=true;defaultFocusHighlightEnabled=false;setBackgroundColor(getColor(R.color.ui_surface));addView(body)}
        NativeUi.insets(scroll)
        val center=FrameLayout(this).apply{setBackgroundColor(getColor(R.color.ui_surface));addView(scroll,FrameLayout.LayoutParams(-1,-1,android.view.Gravity.TOP or android.view.Gravity.CENTER_HORIZONTAL))}
        center.addOnLayoutChangeListener{_,_,_,_,_,_,_,_,_->val width=minOf(center.width,720.dp);val params=scroll.layoutParams as FrameLayout.LayoutParams;if(width>0&&params.width!=width){params.width=width;scroll.layoutParams=params}}
        setContentView(center)
        ContextCompat.registerReceiver(this,permission,IntentFilter("$packageName.RESTORE_USB_PERMISSION"),ContextCompat.RECEIVER_NOT_EXPORTED)
        bound=bindService(Intent(this,OriginalRestoreService::class.java),connection,BIND_AUTO_CREATE)
        if(hash==null){status.text="Open a saved original backup from Devices.";restore.isEnabled=false}
    }
    private val Int.dp get()=NativeUi.dp(this@OriginalRestoreActivity,this)
    private fun render(state:OriginalRestoreState){
        val same=state.backupSha256==null||state.backupSha256==hash
        status.text=when {
            state.busy&&!same->"Another device is being restored. Open its backup to see progress."
            hash==null->"Open a saved original backup from Devices."
            !same->"Original backup is saved on this phone."
            else->state.message
        }
        progress.visibility=if(same&&state.total>0)View.VISIBLE else View.GONE
        if(same&&state.total>0){progress.progress=(state.done.toLong()*1000/state.total).toInt();progress.contentDescription="${state.done.toLong()*100/state.total}% verified progress"}
        restore.isEnabled=hash!=null&&!state.busy;exportButton.isEnabled=hash!=null&&!state.busy
        stop.visibility=if(state.busy&&same)View.VISIBLE else View.GONE
    }
    private fun export(){if(service?.state?.value?.busy==true)return;startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/zip").putExtra(Intent.EXTRA_TITLE,"vimar-original-backup.zip"),81)}
    private fun chooseProbe(){
        if(service?.state?.value?.busy==true||hash==null)return
        val devices=manager.deviceList.values.filter{it.vendorId==0x1366}.sortedBy{it.deviceName}
        if(devices.isEmpty()){status.text="Connect the DK’s J-Link USB port to your phone and its SWD wires to this dimmer.";return}
        fun select(index:Int){val device=devices[index];selectedDevice=device.deviceName
            if(manager.hasPermission(device))review(device.deviceName)else{pendingPermission="vimar-updater://restore/${UUID.randomUUID()}";manager.requestPermission(device,PendingIntent.getBroadcast(this,0,Intent("$packageName.RESTORE_USB_PERMISSION").setPackage(packageName).setData(Uri.parse(pendingPermission)),PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))}}
        if(devices.size==1)select(0)else AlertDialog.Builder(this).setTitle("Select DK").setItems(devices.map{it.productName?:it.deviceName}.toTypedArray()){_,i->select(i)}.setNegativeButton("Cancel",null).show()
    }
    private fun review(device:String){
        val digest=hash?:return;val link=service?:return
        scope.launch{runCatching{withContext(Dispatchers.IO){AndroidInitialInstallPersistence(this@OriginalRestoreActivity).reopenOriginal(digest)}}
            .onSuccess{original->if(foreground)AlertDialog.Builder(this@OriginalRestoreActivity).setTitle("Restore original firmware?")
                .setMessage("Device ${"%08x-%08x".format(original.identity.uid0,original.identity.uid1)}\n\nThis replaces all custom firmware and settings with the saved original. The connected device’s UID, FICR and UICR must match. Keep USB and power connected. After verification, disconnect the DK and power-cycle the dimmer.")
                .setPositiveButton("Restore"){_,_->if(foreground&&hash==digest&&service===link&&link.state.value.busy==false){ContextCompat.startForegroundService(this@OriginalRestoreActivity,Intent(this@OriginalRestoreActivity,OriginalRestoreService::class.java));link.start(digest,device)}}
                .setNegativeButton("Cancel",null).show().getButton(AlertDialog.BUTTON_POSITIVE).setTextColor(getColor(R.color.ui_error))}
            .onFailure{status.text=it.message?:"Backup is unavailable"}}
    }
    @Deprecated("Android callback")override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?){super.onActivityResult(requestCode,resultCode,data);if(requestCode!=81||resultCode!=RESULT_OK)return;val uri=data?.data?:return;val digest=hash?:return
        scope.launch{runCatching{withContext(Dispatchers.IO){val bytes=AndroidInitialInstallPersistence(this@OriginalRestoreActivity).originalBytes(digest);val port=AndroidInitialInstallDocuments.export(contentResolver,uri){!isActive};require(port.create(bytes)==uri.toString());require(port.reopen(uri.toString()).contentEquals(bytes))}}.onSuccess{status.text="Backup copy exported."}.onFailure{status.text=it.message?:"Could not export backup"}}
    }
    override fun onResume(){super.onResume();foreground=true}
    override fun onPause(){foreground=false;super.onPause()}
    override fun onSaveInstanceState(out:Bundle){super.onSaveInstanceState(out);out.putString("backup",hash)}
    override fun onDestroy(){observing?.cancel();if(bound)unbindService(connection);unregisterReceiver(permission);scope.cancel();super.onDestroy()}
}
