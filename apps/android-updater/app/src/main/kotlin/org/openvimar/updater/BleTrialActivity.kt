package org.openvimar.updater

import android.app.Activity
import android.app.AlertDialog
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.combine

/** One explicit BLE candidate trial. No service/radio operation on launch or restore. */
class BleTrialActivity:Activity() {
    override fun attachBaseContext(newBase:Context){super.attachBaseContext(NativeUi.themedContext(newBase))}
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
    private val runtime get()=AndroidBleTrialOwner.get(this)
    private lateinit var candidate:TextView
    private lateinit var target:TextView
    private lateinit var operationName:TextView
    private lateinit var operation:TextView
    private val selectedRecord by lazy{intent.getStringExtra("deviceId")?.let{id->FleetStore(this).devices.firstOrNull{it.id==id}}}
    private var displayedAddress:String?=null
    private var displayedName:String?=null
    private lateinit var status:TextView
    private lateinit var progress:ProgressBar
    private lateinit var choose:Button
    private lateinit var find:Button
    private lateinit var run:Button
    private lateinit var stop:Button
    private lateinit var export:Button
    private lateinit var pairing:Button
    private var picker:BluetoothCandidatePicker?=null
    private var dialog:AlertDialog?=null
    private var importing=false
    private var exporting=false
    private var foreground=false
    private var pendingExport:ByteArray?=null
    private fun dp(v:Int)=NativeUi.dp(this,v)
    override fun onCreate(savedInstanceState:Bundle?){
        super.onCreate(savedInstanceState)
        pendingExport=savedInstanceState?.getByteArray("reportSnapshot")
        val root=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setBackgroundColor(getColor(R.color.ui_surface))}
        val pairingOnly=intent.getBooleanExtra("pairingOnly",false)
        root.addView(NativeUi.taskHeader(this,if(pairingOnly)"Zigbee pairing" else "Update firmware"){finish()}.apply{setPadding(dp(8),dp(8),dp(20),dp(8))})
        // Keep current feedback and Stop available independently of the task scroll.
        // Long errors remain readable by scrolling this bounded status viewport.
        operationName=NativeUi.label(this,"",15,true).apply{
            tag="ble.trial.name";visibility=View.GONE;maxLines=1;ellipsize=android.text.TextUtils.TruncateAt.END
        }
        root.addView(operationName,LinearLayout.LayoutParams(-1,-2).apply{setMargins(dp(20),0,dp(20),dp(4))})
        operation=NativeUi.label(this,"",15,true).apply{tag="ble.trial.operation";visibility=View.GONE}
        root.addView(operation,LinearLayout.LayoutParams(-1,-2).apply{setMargins(dp(20),0,dp(20),dp(8))})
        status=NativeUi.status(this).apply{tag="ble.trial.status"}
        progress=ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal).apply{max=100;progressTintList=android.content.res.ColorStateList.valueOf(getColor(R.color.ui_primary))}
        val feedback=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;addView(status);addView(progress,LinearLayout.LayoutParams(-1,dp(4)))}
        val feedbackScroll=object:ScrollView(this){
            override fun onMeasure(widthMeasureSpec:Int,heightMeasureSpec:Int){
                val bound=minOf(dp(164),resources.displayMetrics.heightPixels/3)
                super.onMeasure(widthMeasureSpec,View.MeasureSpec.makeMeasureSpec(bound,View.MeasureSpec.AT_MOST))
            }
        }.apply{addView(feedback)}
        root.addView(feedbackScroll,LinearLayout.LayoutParams(-1,-2).apply{setMargins(dp(20),0,dp(20),dp(4))})
        val body=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(dp(20),dp(4),dp(20),dp(28))}
        val firmwareBody=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;visibility=if(pairingOnly)View.GONE else View.VISIBLE}
        body.addView(firmwareBody)
        var section=firmwareBody
        val scroll=ScrollView(this).apply{isFillViewport=true;defaultFocusHighlightEnabled=false;tag="ble.trial.content";addView(body)}
        root.addView(scroll,LinearLayout.LayoutParams(-1,0,1f))
        fun add(view:View,gap:Int=12){section.addView(view,LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(gap)})}
        fun label(text:String,heading:Boolean=false):TextView=NativeUi.label(this,text,if(heading)18 else 15,heading,!heading).also{if(heading)ViewCompat.setAccessibilityHeading(it,true);add(it,if(heading)24 else 8)}
        label("Choose firmware for this device.")
        label("Package",true)
        candidate=label("No firmware selected")
        choose=NativeUi.button(this,"Choose firmware",outline=true){chooseCandidate()}.apply{tag="ble.trial.choose"};add(choose)
        label(selectedRecord?.name?:"Dimmer",true)
        label("On older firmware, switch the lamp off before enabling Bluetooth.")
        val help=NativeUi.label(this,"In Home Assistant or Zigbee2MQTT, activate Bluetooth/recovery on this dimmer. Keep it powered. Accept Android pairing; enter 824005 if asked.",15,secondary=true)
        add(NativeUi.disclosure(this,"Connection help","Hide connection help",help),0);add(help,0)
        target=label("Inspect this device before updating.")
        find=NativeUi.button(this,"Inspect device",outline=true){search()}.apply{tag="ble.trial.find"};add(find)
        label("Update",true)
        label("Review the selected dimmer before starting. If interrupted, inspect it again to resume saved progress.")
        run=NativeUi.button(this,"Review Bluetooth update",filled=true){review()}.apply{tag="ble.trial.run"};add(run)
        export=NativeUi.button(this,"Export update report"){exportReport()}.apply{tag="ble.trial.export"};add(export)
        section=body
        label("Zigbee pairing",true)
        label("Forget the previous Zigbee network and pair for two minutes. Dimmer settings are kept. Requires supporting firmware; no firmware package is needed.")
        label("To enable Bluetooth on supporting firmware, hold both buttons for five seconds, release both, then press Down. The LED alternates blue/green.")
        pairing=NativeUi.button(this,"Inspect for Zigbee pairing",outline=true){
            if(runtime.controller.state.value.pairingReview==null)search(pairingMode=true)else reviewPairing()
        }.apply{tag="ble.pairing.review"};add(pairing)
        firmwareBody.removeView(export);add(export)
        stop=NativeUi.button(this,"Stop update",outline=true){startService(Intent(this,BleTrialService::class.java).setAction(BleTrialService.STOP))}.apply{tag="ble.trial.stop"}
        root.addView(stop,LinearLayout.LayoutParams(-1,-2).apply{setMargins(dp(20),dp(8),dp(20),dp(12))})
        val centered=FrameLayout(this).apply{
            setBackgroundColor(getColor(R.color.ui_surface))
            addView(root,FrameLayout.LayoutParams(-1,-1,Gravity.TOP or Gravity.CENTER_HORIZONTAL))
        }
        centered.addOnLayoutChangeListener{_,_,_,_,_,_,_,_,_->
            val width=minOf(centered.width-centered.paddingLeft-centered.paddingRight,dp(720))
            val params=root.layoutParams as FrameLayout.LayoutParams
            if(width>0&&params.width!=width){params.width=width;root.layoutParams=params}
        }
        setContentView(centered);NativeUi.insets(centered);NativeUi.systemBars(this)
        if(Build.VERSION.SDK_INT>=33)onBackInvokedDispatcher.registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT){finish()}
        scope.launch{combine(runtime.controller.state,runtime.selection,runtime.message){_,_,_->Unit}.collect{render()}}
        render()
    }
    private fun render(){
        val state=runtime.controller.state.value;val selection=runtime.selection.value;val busy=state.busy||importing
        candidate.text=selection?.let{"Firmware ${it.version} · recovery ${it.recoveryVersion}\nLocal package · ${it.reference.digest.take(12)}…"} ?: "No firmware selected"
        val address=state.target?.address
        if(address!=displayedAddress){
            displayedAddress=address
            // Optional organisation only. Read once per target; progress never reloads the store.
            displayedName=address?.let{selected->FleetStore(this).devices.firstOrNull{it.address.equals(selected,true)}?.name?.takeIf{it.isNotBlank()}}
        }
        operationName.text=displayedName.orEmpty()
        operationName.visibility=if(displayedName!=null)View.VISIBLE else View.GONE
        operation.visibility=if(state.target!=null)View.VISIBLE else View.GONE
        operation.text=state.target?.let{"${it.address} · ${state.phase.label}"}.orEmpty()
        target.text=state.target?.let{
            if(it.identitySummary!=null)"Inspected firmware ${it.currentVersion ?: "unknown"} → ${it.version}\n${it.identitySummary}"
            else "Compatibility has not been confirmed for this address. Inspect it successfully before reviewing an update."
        } ?: "Inspect this device before reviewing the update."
        status.text=if(importing)"Checking firmware…" else runtime.message.value ?:
            if(intent.getBooleanExtra("pairingOnly",false)&&state.phase==BleTrialPhase.IDLE)
                "Enable Bluetooth on this dimmer, then inspect and review Zigbee pairing." else state.status
        progress.visibility=if(state.progressPercent!=null||busy)View.VISIBLE else View.GONE
        progress.isIndeterminate=state.progressPercent==null;progress.progress=state.progressPercent ?: 0
        choose.isEnabled=!busy
        find.isEnabled=selection!=null&&!busy
        run.isEnabled=state.review!=null&&!busy&&matchesSelected(state.review!!)
        stop.visibility=if(state.busy)View.VISIBLE else View.GONE
        export.visibility=if(runtime.reportAvailable)View.VISIBLE else View.GONE
        export.isEnabled=runtime.reportAvailable&&!busy&&!exporting&&pendingExport==null
        export.text=if(state.pairing)"Export pairing report" else "Export update report"
        pairing.isEnabled=!busy
        pairing.text=if(state.pairingReview==null)"Inspect for Zigbee pairing" else "Review Zigbee pairing"
        stop.text=if(state.pairing)"Stop" else "Stop update"
    }
    private fun matchesSelected(review:BleTrialReviewInfo):Boolean {
        val selected=selectedRecord?:return true
        return (selected.address==null||selected.address.equals(review.address,true))&&(selected.uid.size!=2||selected.uid==review.expectedUid)
    }
    private fun permissionsReady()=PermissionPolicy.required(Build.VERSION.SDK_INT).all{checkSelfPermission(it)==PackageManager.PERMISSION_GRANTED}
    private fun chooseCandidate(){
        if(importing||runtime.controller.state.value.busy)return
        runtime.controller.invalidate()
        runCatching{startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE),IMPORT)}
            .onFailure{runtime.fail(it.message ?: "Choose a Vomar firmware ZIP")}
    }
    private fun search(pairingMode:Boolean=false){
        if((!pairingMode&&runtime.selection.value==null)||runtime.controller.state.value.busy||importing)return
        if(!permissionsReady()){
            runtime.fail("Allow Bluetooth access, then choose Inspect device again.")
            requestPermissions(PermissionPolicy.required(Build.VERSION.SDK_INT).toTypedArray(),PERMISSIONS);return
        }
        fun inspect(address:String){if(foreground&&!runtime.controller.state.value.busy)launchService(Intent(this,BleTrialService::class.java).setAction(if(pairingMode)BleTrialService.INSPECT_PAIRING else BleTrialService.INSPECT).putExtra(BleTrialService.ADDRESS,address)
            .putStringArrayListExtra("expectedUid",selectedRecord?.uid?.takeIf{it.size==2}?.let{ArrayList(it)}))}
        val selected=selectedRecord
        if(selected?.address!=null){inspect(selected.address);return}
        picker?.close();picker=BluetoothCandidatePicker(this).also{it.show(allowLegacy=true){address->inspect(address)}}
    }
    private fun reviewPairing(){
        val held=runtime.controller.state.value.pairingReview ?: return
        val selected=selectedRecord
        if(selected!=null&&((selected.address!=null&&!selected.address.equals(held.address,true))||
            (selected.uid.size==2&&selected.uid!=held.uid))){
            runtime.fail("Inspect the selected device again before pairing.");return
        }
        if(!foreground||runtime.controller.state.value.busy)return
        dialog?.dismiss()
        dialog=AlertDialog.Builder(this).setTitle("Replace Zigbee network?")
            .setMessage("${held.address}\nUID ${held.uid.joinToString(" / ")}\n\nThis forgets the current Zigbee network and searches for two minutes. Dimmer settings and Bluetooth access are kept. Enable permit join on your coordinator before continuing.")
            .setNegativeButton("Cancel"){_,_->runtime.controller.invalidate()}
            .setPositiveButton("Start Zigbee pairing"){_,_->
                if(foreground&&!runtime.controller.state.value.busy)
                    launchService(Intent(this,BleTrialService::class.java).setAction(BleTrialService.EXECUTE_PAIRING).putExtra(BleTrialService.REVIEW,held.id))
            }.create().also{it.setOnCancelListener{runtime.controller.invalidate()};it.show()}
    }
    private fun review(){
        val held=runtime.controller.state.value.review ?: return
        if(!matchesSelected(held)){runtime.fail("Inspect the selected device again before updating.");return}
        if(runtime.controller.state.value.busy||!foreground)return
        val body=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(dp(24),dp(12),dp(24),dp(8))}
        body.addView(NativeUi.label(this,"${held.address}\nFirmware ${held.currentVersion ?: "unknown"} → ${held.version}\n${held.identitySummary}\n\nLocal or beta firmware may not have passed release checks. This update applies only to the selected device.",15))
        val confirm=if(held.resetRetryRequired)CheckBox(this).apply{text="I authorize one retry of the previously uncertain restart";minHeight=dp(48);setTextColor(getColor(R.color.ui_text));body.addView(this)} else null
        val shown=AlertDialog.Builder(this).setTitle(if(held.resumable)"Resume firmware update?" else "Update this device?")
            .setView(ScrollView(this).apply{addView(body)})
            .setNegativeButton("Cancel"){_,_->runtime.controller.invalidate()}.setPositiveButton("Update firmware",null).create()
        dialog=shown
        shown.setOnCancelListener{runtime.controller.invalidate()}
        shown.setOnShowListener{
            val positive=shown.getButton(AlertDialog.BUTTON_POSITIVE)
            positive.isEnabled=confirm?.isChecked ?: true
            confirm?.setOnCheckedChangeListener{_,checked->positive.isEnabled=checked}
            positive.setOnClickListener{
                if(!foreground||isFinishing||runtime.controller.state.value.busy||runtime.controller.state.value.review?.id!=held.id||!matchesSelected(held)||runtime.selection.value?.reference?.digest!=held.digest){shown.dismiss();runtime.fail("The review changed. Inspect this dimmer again.");return@setOnClickListener}
                if(confirm!=null&&!confirm.isChecked)return@setOnClickListener
                shown.dismiss()
                launchService(Intent(this,BleTrialService::class.java).setAction(BleTrialService.EXECUTE).putExtra(BleTrialService.REVIEW,held.id).putExtra(BleTrialService.RETRY,confirm?.isChecked==true))
            }
        }
        shown.show()
    }
    private fun launchService(intent:Intent){
        if(!permissionsReady()){runtime.fail("Bluetooth permission is missing. Allow it, then inspect the dimmer again.");return}
        runCatching{ContextCompat.startForegroundService(this,intent)}.onFailure{runtime.fail("Android could not start the Bluetooth update: ${it.message}")}
    }
    private fun exportReport(){
        if(exporting||pendingExport!=null||runtime.controller.state.value.busy)return
        exporting=true;render()
        scope.launch{
            try{
                val bytes=runtime.reportBytes() ?: error("No update report yet. Inspect a dimmer first.")
                pendingExport=bytes.copyOf()
                startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/json").addCategory(Intent.CATEGORY_OPENABLE).putExtra(Intent.EXTRA_TITLE,"vimar-bluetooth-trial.json"),EXPORT)
            }catch(failure:Exception){pendingExport=null;runtime.fail(failure.message ?: "The update report could not be opened")}
            finally{exporting=false;render()}
        }
    }
    @Deprecated("Android callback") override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?){
        super.onActivityResult(requestCode,resultCode,data)
        if(requestCode==EXPORT){
            val snapshot=pendingExport?.copyOf();pendingExport=null
            if(resultCode==RESULT_OK&&data?.data!=null&&snapshot!=null)scope.launch{
                exporting=true;render()
                try{withContext(Dispatchers.IO){val output=contentResolver.openOutputStream(data.data!!,"wt") ?: error("Report destination unavailable");output.use{it.write(snapshot)}}}
                catch(failure:Exception){runtime.fail(failure.message ?: "Report export failed; choose another location")}
                finally{exporting=false;render()}
            }
            render();return
        }
        if(requestCode==IMPORT&&resultCode==RESULT_OK&&data?.data!=null&&!runtime.controller.state.value.busy){
            importing=true;render();scope.launch{
                try{runtime.importCandidate(data.data!!)}
                catch(cancelled:CancellationException){throw cancelled}
                catch(failure:Exception){runtime.fail(failure.message ?: "This is not a compatible Vomar firmware package")}
                finally{importing=false;render()}
            }
        }
    }
    @Deprecated("Android callback") override fun onRequestPermissionsResult(requestCode:Int,permissions:Array<out String>,grantResults:IntArray){
        super.onRequestPermissionsResult(requestCode,permissions,grantResults)
        if(requestCode==PERMISSIONS)runtime.fail(if(permissionsReady())"Bluetooth access allowed. Choose Inspect device to continue." else "Bluetooth access was not allowed. Allow it in Android settings, then try again.")
    }
    override fun onSaveInstanceState(outState:Bundle){pendingExport?.let{outState.putByteArray("reportSnapshot",it)};super.onSaveInstanceState(outState)}
    override fun onResume(){super.onResume();foreground=true}
    override fun onPause(){foreground=false;super.onPause()}
    override fun onStop(){picker?.close();dialog?.dismiss();super.onStop()}
    override fun onDestroy(){picker?.close();scope.cancel();super.onDestroy()}
    companion object {private const val IMPORT=71;private const val EXPORT=72;private const val PERMISSIONS=73}
}
