package org.openvimar.updater

import android.app.Activity
import android.app.AlertDialog
import android.app.PendingIntent
import android.content.*
import android.hardware.usb.UsbManager
import android.net.Uri
import android.os.Bundle
import android.os.IBinder
import android.view.Gravity
import android.view.View
import android.widget.*
import androidx.core.content.ContextCompat
import kotlinx.coroutines.*
import org.json.JSONObject
import org.openvimar.installer.*
import org.openvimar.updater.installer.*
import java.io.ByteArrayOutputStream
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec
import java.util.UUID
import java.util.zip.ZipInputStream

/** Explicit, single-target installation. Rotation restores document selection
 * and observation only; it never restores a capture or installation approval. */
class InitialInstallActivity:Activity() {
    override fun attachBaseContext(base:Context)=super.attachBaseContext(NativeUi.themedContext(base))
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
    private val manager by lazy{getSystemService(USB_SERVICE) as UsbManager}
    private lateinit var body:LinearLayout
    private lateinit var status:TextView
    private lateinit var actions:LinearLayout
    private lateinit var packageSummary:TextView
    private lateinit var targetSummary:TextView
    private lateinit var chooseRelease:Button
    private lateinit var progress:ProgressBar
    private lateinit var progressText:TextView
    private lateinit var recap:TextView
    private lateinit var stepText:TextView
    private lateinit var selectionPanel:LinearLayout
    private lateinit var statusPanel:LinearLayout
    private lateinit var chooseDk:Button
    private var service:InitialInstallService?=null
    private var bound=false
    private var observing:Job?=null
    private var packageJob:Job?=null
    private var selectedUri:Uri?=null
    private var selectedDigest:String?=null
    private var selectedVersion:String?=null
    private var rawPackage:ByteArray?=null
    private var candidate=false
    private var busy=false
    private var foreground=false
    private var selectedDevice:String?=null
    private var pendingPermission:String?=null
    private var pendingExportRequest:String?=null
    private var resumeOriginalUri:Uri?=null
    private var resumeBindingId:String?=null
    private var resumeRelease:String?=null
    private var resumeDeviceName:String?=null
    private var resumeCandidate=false
    private var diagnostic:String?=null
    private var snapshot=InitialInstallSnapshot()
    private val permissionAction get()="$packageName.INITIAL_USB_PERMISSION"
    private val connection=object:ServiceConnection {
        override fun onServiceConnected(name:ComponentName,binder:IBinder){
            service=(binder as InitialInstallService.LocalBinder).service
            observing?.cancel();observing=scope.launch{
                launch{service!!.state.collect{snapshot=it;render()}}
                launch{service!!.inspectedTarget.collect{render()}}
                launch{service!!.inspectedWatchdog.collect{render()}}
                launch{service!!.resumeOptions.collect{render()}}
                launch{service!!.inspectionMessage.collect{render()}}
            }
            render()
        }
        override fun onServiceDisconnected(name:ComponentName){service=null;observing?.cancel();status.text="USB service disconnected. No operation will restart automatically.";renderActions()}
    }
    private val permissions=object:BroadcastReceiver(){
        override fun onReceive(context:Context,intent:Intent){
            if(intent.action!=permissionAction||intent.dataString!=pendingPermission)return
            val device=manager.deviceList.values.firstOrNull{it.deviceName==selectedDevice}
            if(device!=null&&manager.hasPermission(device)){
                if(foreground){pendingPermission=null;inspect(device.deviceName)}
                // A system permission dialog may grant before onResume. Keep
                // that explicit read request pending; it never grants capture.
            } else {pendingPermission=null;status.text="USB access was not granted. Choose the DK and try again.";renderActions()}
        }
    }
    override fun onCreate(savedInstanceState:Bundle?){
        super.onCreate(savedInstanceState);NativeUi.systemBars(this)
        selectedDevice=savedInstanceState?.getString("device")
        selectedUri=savedInstanceState?.getString("uri")?.let(Uri::parse)
        selectedDigest=savedInstanceState?.getString("digest")
        candidate=savedInstanceState?.getBoolean("candidate")?:false
        pendingExportRequest=savedInstanceState?.getString("exportRequest")
        pendingPermission=savedInstanceState?.getString("permissionRequest")
        resumeOriginalUri=savedInstanceState?.getString("resumeOriginal")?.let(Uri::parse)
        resumeBindingId=savedInstanceState?.getString("resumeBinding")
        resumeRelease=savedInstanceState?.getString("resumeRelease")
        resumeDeviceName=savedInstanceState?.getString("resumeDevice")
        resumeCandidate=savedInstanceState?.getBoolean("resumeCandidate")?:false
        val root=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setBackgroundColor(getColor(R.color.ui_surface))}
        NativeUi.insets(root)
        val header=LinearLayout(this).apply{gravity=Gravity.CENTER_VERTICAL;setPadding(dp(20),dp(8),dp(12),0)}
        header.addView(NativeUi.taskHeader(this,"First installation"){leave()},LinearLayout.LayoutParams(0,-2,1f))
        header.addView(NativeUi.actionIcon(this,"help","First installation help"){showHelp()});root.addView(header)
        body=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(dp(20),dp(8),dp(20),dp(20))}
        val scroll=ScrollView(this).apply{isFillViewport=true;defaultFocusHighlightEnabled=false;setBackgroundColor(getColor(R.color.ui_surface));addView(body)}
        root.addView(scroll,LinearLayout.LayoutParams(-1,0,1f))
        stepText=NativeUi.label(this,"1 · Choose firmware",20,true);add(stepText,16)
        selectionPanel=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL};add(selectionPanel,12)
        fun selection(view:View,gap:Int=8){selectionPanel.addView(view,LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(gap)})}
        packageSummary=label("No firmware selected");selection(packageSummary)
        chooseRelease=button("Choose firmware",true){pickPackage()};selection(chooseRelease)
        targetSummary=label("Connect the DK to the dimmer and your phone.");selection(targetSummary,28)
        chooseDk=button("Read connected device"){chooseProbe()};selection(chooseDk)
        actions=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL};add(actions,16)
        statusPanel=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(dp(20),dp(12),dp(20),dp(16));tag="initial.status"}
        recap=NativeUi.label(this,"Choose firmware to begin",13,secondary=true);statusPanel.addView(recap)
        status=NativeUi.label(this,"Ready",16,true).apply{accessibilityLiveRegion=View.ACCESSIBILITY_LIVE_REGION_POLITE};statusPanel.addView(status,LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(8)})
        progress=ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal).apply{max=1000;isIndeterminate=false;visibility=View.GONE;tag="initial.progress"}
        statusPanel.addView(progress,LinearLayout.LayoutParams(-1,dp(8)).apply{topMargin=dp(12)})
        progressText=NativeUi.label(this,"",13,secondary=true);statusPanel.addView(progressText)
        root.addView(statusPanel)
        val center=FrameLayout(this).apply{setBackgroundColor(getColor(R.color.ui_surface));addView(root,FrameLayout.LayoutParams(-1,-1,Gravity.TOP or Gravity.CENTER_HORIZONTAL))}
        center.addOnLayoutChangeListener{_,_,_,_,_,_,_,_,_->val width=minOf(center.width,dp(720));val params=root.layoutParams as FrameLayout.LayoutParams;if(width>0&&params.width!=width){params.width=width;root.layoutParams=params}}
        setContentView(center)
        ContextCompat.registerReceiver(this,permissions,IntentFilter(permissionAction),ContextCompat.RECEIVER_NOT_EXPORTED)
        bound=bindService(Intent(this,InitialInstallService::class.java),connection,BIND_AUTO_CREATE)
        render()
        selectedUri?.let{loadPackage(it,selectedDigest)}
    }
    private fun dp(n:Int)=NativeUi.dp(this,n)
    private fun label(text:String)=NativeUi.label(this,text,15,secondary=true)
    private fun button(text:String,primary:Boolean=false,action:()->Unit)=NativeUi.button(this,text,primary){runCatching(action).onFailure{status.text=it.message?:"The operation could not start. Check the current connection and try again."}}
    private fun add(view:View,gap:Int=8){body.addView(view,LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(gap)})}
    private fun section(text:String)=add(NativeUi.label(this,text,20,true),24)
    private fun pickPackage(){
        if(active()){status.text="Finish or cancel the current operation before changing its release.";return}
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
            .putExtra(Intent.EXTRA_MIME_TYPES,arrayOf("application/zip","application/octet-stream","application/x-zip-compressed")),PACKAGE)
    }
    private fun key()=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(resources.openRawResource(R.raw.firmware_public).use{it.readBytes()}))
    private fun loadPackage(uri:Uri,expected:String?=null){
        packageJob?.cancel();rawPackage=null;busy=true;renderActions();status.text="Checking firmware…"
        packageJob=scope.launch{
            val result=runCatching{withContext(Dispatchers.IO){
                val bytes=contentResolver.openInputStream(uri)?.use{input->val out=ByteArrayOutputStream();val buffer=ByteArray(8192)
                    while(true){ensureActive();val n=input.read(buffer);if(n<0)break;require(n>0&&out.size()+n<=2*1024*1024){"The common ZIP must be at most 2 MiB"};out.write(buffer,0,n)};out.toByteArray()}?:error("The selected release could not be opened")
                val appVersion=packageManager.getPackageInfo(packageName,0).versionName?:error("App version unavailable")
                val qualified=runCatching{CommonRelease.verify(bytes,key(),appVersion)}.getOrNull()
                val manual=if(qualified==null)CandidateRelease.inspectLocal(bytes,key(),appVersion) else null
                val digest=qualified?.releaseSha256?:checkNotNull(manual).releaseSha256
                require(expected==null||expected==digest){"The selected document changed since it was reviewed"}
                val manifest=ZipInputStream(bytes.inputStream()).use{zip->var version="Signed common release"
                    while(true){val entry=zip.nextEntry?:break;if(entry.name=="manifest.json"){version=JSONObject(String(zip.readBytes(),Charsets.UTF_8)).getJSONObject("main").getString("version");break}};version}
                PackageChoice(bytes,digest,manifest,manual!=null)
            }}
            if(!isActive)return@launch
            busy=false
            result.onSuccess{choice->
                fun accept(){selectedUri=uri;selectedDigest=choice.digest;selectedVersion=choice.version;rawPackage=choice.bytes;candidate=choice.manual;status.text="Firmware selected. Connect and read the device.";renderPackage();renderActions()}
                if(choice.manual&&expected==null&&foreground)AlertDialog.Builder(this@InitialInstallActivity).setTitle("Use this firmware?")
                    .setMessage("This local package is beta or has no verified release signature. It has not passed the release checks. Version ${choice.version} will be used only for the device you review.")
                    .setPositiveButton("Use firmware"){_,_->if(foreground&&!active())accept()}.setNegativeButton("Cancel",null).show()
                else accept()
            }
                .onFailure{selectedUri=null;selectedDigest=null;selectedVersion=null;rawPackage=null;status.text=it.message?:"This is not a compatible Vomar firmware package."}
            if(snapshot.phase!=InitialInstallPhase.IDLE)render()else {renderPackage();renderActions()}
        }
    }
    private fun chooseProbe(){
        if(active()){status.text="The current USB transaction must finish or be cancelled before selecting another target.";return}
        val devices=manager.deviceList.values.filter{it.vendorId==0x1366}.sortedBy{it.deviceName}
        if(devices.isEmpty()){status.text="No J-Link USB probe found. Connect the DK’s J-Link USB port using a USB host adapter, then try again.";return}
        fun select(index:Int){val device=devices[index];selectedDevice=device.deviceName
            if(manager.hasPermission(device))inspect(device.deviceName)
            else {pendingPermission="vimar-updater://initial-usb/${UUID.randomUUID()}";val intent=Intent(permissionAction).setPackage(packageName).setData(Uri.parse(pendingPermission))
                manager.requestPermission(device,PendingIntent.getBroadcast(this,0,intent,PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))}}
        if(devices.size==1)select(0) else AlertDialog.Builder(this).setTitle("Select J-Link probe").setItems(devices.map{it.productName?:"J-Link ${it.deviceName}"}.toTypedArray()){_,which->select(which)}.setNegativeButton("Cancel",null).show()
    }
    private fun inspect(device:String){service?.inspectTarget(device)?:run{status.text="USB service is connecting. Try reading the target again."}}
    private fun active()=snapshot.phase in setOf(InitialInstallPhase.CONNECTING,InitialInstallPhase.CAPTURING,InitialInstallPhase.AWAITING_EXPORT,InitialInstallPhase.AWAITING_REVIEW,InitialInstallPhase.AWAITING_RESUME_REVIEW,InitialInstallPhase.INSTALLING,InitialInstallPhase.STARTING)
    private fun lockedSelection()=active()||snapshot.phase==InitialInstallPhase.VERIFIED_HALTED
    private fun render(){
        if(!::status.isInitialized)return
        if(snapshot.phase!=InitialInstallPhase.IDLE)status.text=when(snapshot.phase){
            InitialInstallPhase.CONNECTING->if(snapshot.resume)"Checking the original backup and interrupted installation…" else "Checking the selected release and target…"
            InitialInstallPhase.CAPTURING->if(snapshot.resume)"Checking the target and saved evidence for repair…" else "Reading and comparing two full copies of the original firmware…"
            InitialInstallPhase.AWAITING_EXPORT->"Saving backup…"
            InitialInstallPhase.AWAITING_REVIEW->"Backup saved. Ready to install."
            InitialInstallPhase.AWAITING_RESUME_REVIEW->"Repair review ready. Confirm before the complete image check and any needed writes."
            InitialInstallPhase.INSTALLING->if(snapshot.resume)"Repairing the reviewed installation. Keep USB and power connected." else "Installing firmware and checking each block. Keep USB and power connected."
            InitialInstallPhase.VERIFIED_HALTED->"The complete firmware is verified. Choose Start when you are ready."
            InitialInstallPhase.STARTING->"Rechecking the installed firmware before starting it…"
            InitialInstallPhase.STARTED->"Start acknowledged. Check normal device operation."
            else->snapshot.message
        }
        else if(rawPackage==null)status.text="Choose firmware to begin."
        else service?.inspectionMessage?.value?.takeIf{it.isNotBlank()}?.let{status.text=if(it.startsWith("Inspect the selected"))"Connect and read the device." else it}
        val target=snapshot.request?.target?:service?.inspectedTarget?.value
        targetSummary.text=target?.let{"Device ${"%08x-%08x".format(it.uid0,it.uid1)}"}?:"Connect the DK to the dimmer and your phone."
        renderPackage();renderActions()
    }
    private data class PackageChoice(val bytes:ByteArray,val digest:String,val version:String,val manual:Boolean)
    private fun renderPackage(){
        val digest=snapshot.request?.reviewedReleaseSha256?:selectedDigest
        packageSummary.text=if(digest==null)"No firmware selected" else "Firmware ${selectedVersion?:digest.take(12)}${if(candidate)" · beta / local" else ""}"
        updatePinnedStatus()
    }
    private fun updatePinnedStatus(){
        val step=when(snapshot.phase){
            InitialInstallPhase.FAILED,InitialInstallPhase.CANCELLED->"Installation stopped"
            InitialInstallPhase.IDLE->if(rawPackage==null)"1 · Choose firmware" else if(service?.inspectedTarget?.value==null)"2 · Connect device" else "3 · Back up original firmware"
            InitialInstallPhase.CONNECTING,InitialInstallPhase.CAPTURING,InitialInstallPhase.AWAITING_EXPORT->"3 · Back up original firmware"
            InitialInstallPhase.AWAITING_REVIEW,InitialInstallPhase.AWAITING_RESUME_REVIEW,InitialInstallPhase.INSTALLING->"4 · Install firmware"
            else->"5 · Start device"
        }
        NativeUi.emphasis(chooseRelease,rawPackage==null)
        NativeUi.emphasis(chooseDk,rawPackage!=null&&service?.inspectedTarget?.value==null)
        chooseRelease.text=if(rawPackage==null)"Choose firmware" else "Change firmware"
        chooseDk.text=if(service?.inspectedTarget?.value==null)"Read connected device" else "Change device"
        stepText.text=step;selectionPanel.visibility=if(snapshot.phase==InitialInstallPhase.IDLE)View.VISIBLE else View.GONE
        chooseDk.visibility=if(rawPackage!=null)View.VISIBLE else View.GONE;targetSummary.visibility=chooseDk.visibility
        val target=snapshot.request?.target?:service?.inspectedTarget?.value
        recap.text=listOfNotNull(selectedVersion?.let{"Firmware $it"},target?.let{"Device ${"%08x-%08x".format(it.uid0,it.uid1)}"}).joinToString(" · ")
        recap.visibility=if(recap.text.isBlank())View.GONE else View.VISIBLE
        val tone=when(snapshot.phase){InitialInstallPhase.FAILED->R.color.ui_error;InitialInstallPhase.CANCELLED->R.color.ui_available;InitialInstallPhase.AWAITING_REVIEW,InitialInstallPhase.VERIFIED_HALTED,InitialInstallPhase.STARTED->R.color.ui_current;else->R.color.ui_primary}
        val color=getColor(tone);statusPanel.background=NativeUi.shape(this,android.graphics.Color.argb(if(resources.configuration.uiMode and 0x30==0x20)48 else 22,android.graphics.Color.red(color),android.graphics.Color.green(color),android.graphics.Color.blue(color)))
        status.setTextColor(color)
        val measured=snapshot.progressTotal>0&&snapshot.phase in setOf(InitialInstallPhase.CAPTURING,InitialInstallPhase.INSTALLING,InitialInstallPhase.STARTING)
        progress.visibility=if(measured)View.VISIBLE else View.GONE;progressText.visibility=if(measured)View.VISIBLE else View.GONE
        if(measured){val percent=(snapshot.progressDone.toLong()*100/snapshot.progressTotal).toInt();progress.progress=percent*10;progressText.text="${snapshot.progressLabel} · $percent%";progress.contentDescription=progressText.text}
    }
    private fun renderActions(){
        if(!::actions.isInitialized)return
        listOf(chooseRelease,chooseDk).forEach{it.isEnabled=!lockedSelection()&&!busy&&snapshot.phase==InitialInstallPhase.IDLE}
        chooseDk.isEnabled=chooseDk.isEnabled&&rawPackage!=null
        updatePinnedStatus()
        actions.removeAllViews()
        fun action(label:String,primary:Boolean=false,enabled:Boolean=true,tagValue:String?=null,block:()->Unit){actions.addView(button(label,primary,block).apply{isEnabled=enabled;tag=tagValue},LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(8)})}
        fun copy(text:String){actions.addView(label(text),LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(8)})}
        when(snapshot.phase){
            InitialInstallPhase.IDLE->{
                val options=service?.resumeOptions?.value.orEmpty()
                val option=options.singleOrNull()
                if(option!=null){
                    copy("This target has a retained installation attempt. Reuse its existing original backup; a new capture cannot replace it.")
                    copy("Repair may reinstall the reviewed firmware and reset settings created after the first installation. The approved repair checks the complete image before deciding what is needed.")
                    val matching=rawPackage!=null&&selectedDigest==option.releaseSha256
                    if(!matching)copy("Choose the same common release used for this attempt before selecting its original backup.")
                    if(!option.originalAvailable)copy("The protected original is unavailable in this app. Save the diagnostic report before attempting a manual repair.")
                    if(option.initialExportDocument.startsWith("file:")){
                        resumeOriginalUri=Uri.parse(option.initialExportDocument);resumeBindingId=option.bindingId;resumeRelease=option.releaseSha256;resumeDeviceName=selectedDevice;resumeCandidate=candidate
                    }else action("Choose existing original backup",enabled=matching&&!busy&&option.originalAvailable){pickResumeOriginal(option)}
                    if(resumeOriginalUri!=null&&resumeBindingId==option.bindingId){
                        copy("Original backup selected. Preparing a preview pauses this target and checks its identity and saved evidence; it does not erase or program flash.")
                        action("Prepare repair preview",true,matching&&!busy&&option.originalAvailable&&resumeRelease==selectedDigest&&resumeDeviceName==selectedDevice&&resumeCandidate==candidate,"initial.resume.preview"){prepareRepair(option)}
                    }
                }else{
                    if(rawPackage!=null&&service?.inspectedTarget?.value!=null)action("Backup",true,!busy&&rawPackage!=null&&service?.inspectedTarget?.value!=null,"initial.capture"){reviewCapture()}
                }
            }
            InitialInstallPhase.CONNECTING,InitialInstallPhase.CAPTURING,InitialInstallPhase.INSTALLING,InitialInstallPhase.STARTING->{
                action("Cancel operation"){service?.cancelInstall()}

            }
            InitialInstallPhase.AWAITING_EXPORT->{copy("Saving your verified backup on this phone…");action("Cancel installation"){service?.cancelInstall()}}
            InitialInstallPhase.AWAITING_REVIEW->{
                copy("Your original firmware is saved on this phone and linked to this device.")
                action("Export backup copy"){exportCopy()}
                action("Install firmware",true,tagValue="initial.install.confirm"){reviewInstall()}
                action("Cancel installation"){service?.cancelInstall()}
            }
            InitialInstallPhase.AWAITING_RESUME_REVIEW->{
                copy("The selected backup matches the retained original and this target. Review this repair before continuing.")
                copy(snapshot.resumeClassification?:"Exact repair scope is shown in the reviewed transaction.")
                copy("UID ${snapshot.request?.target?.let{"%08x-%08x".format(it.uid0,it.uid1)}}\nOriginal ${snapshot.archiveSha256?.take(16)}…\nRelease ${snapshot.request?.reviewedReleaseSha256?.take(16)}…")
                copy("A rebuild resets custom settings. A verified image can be checked without rewriting it; an uncommitted verified image needs only its final commit.")
                action("Review and repair",true,tagValue="initial.resume.confirm"){reviewRepair()}
                action("Cancel repair"){service?.cancelInstall()}
            }
            InitialInstallPhase.VERIFIED_HALTED->{
                copy("Firmware installed. Start the device when ready.")
                firstStartNote()?.let(::copy)
                action("Start verified firmware",true){reviewStart()}
            }
            InitialInstallPhase.STARTED->{copy("The new reset vector was checked and the CPU released. Check normal device operation before disconnecting.");firstStartNote()?.let(::copy);action("Prepare another device"){newSession()}}
            InitialInstallPhase.CANCELLED,InitialInstallPhase.FAILED->{
                copy(snapshot.cpuDisposition)
                if(snapshot.mutationMayHaveStarted)copy("Keep this target connected. Preserve its original ZIP and diagnostic report for explicit repair; a fresh backup must not replace its original firmware evidence.")
                else copy("No installation will restart automatically. Prepare a new attempt when you are ready to read a target again.")
                action(if(snapshot.mutationMayHaveStarted)"Prepare a different device" else "Prepare a new attempt"){newSession()}
            }
        }
    }
    private fun exportCopy(){
        pendingExportRequest=snapshot.archiveSha256?:return
        startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/zip").putExtra(Intent.EXTRA_TITLE,"vimar-original-backup.zip"),BACKUP_COPY)
    }
    private fun showHelp(){
        AlertDialog.Builder(this).setTitle("First installation")
            .setMessage("1. Choose a Vomar firmware ZIP. Local and beta packages need your confirmation.\n\n2. Connect the DK’s J-Link port to your phone and its SWD wires to the dimmer.\n\n3. Backup reads the original firmware twice while the CPU is paused. Matching copies are saved privately and linked by the hardware UID. An extra export is optional.\n\n4. Review and install on that exact device. Keep USB and power connected. UICR is preserved.\n\n5. Start the verified firmware. If interrupted after a write, the device stays paused for repair. Backups are removed if app data is cleared or the app is uninstalled; keep an exported copy.")
            .setPositiveButton("Done",null).setNeutralButton("Export report"){_,_->diagnostic=service?.diagnostic()?.toString(2)?:"{}";startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("application/json").putExtra(Intent.EXTRA_TITLE,"vimar-first-install-report.json"),REPORT)}.show()
    }
    private fun firstStartNote():String? {
        val watchdog=snapshot.watchdog?:return null
        if(!watchdog.active||snapshot.watchdogHandoff!="paused-reset-before-main-v1")return null
        val seconds=Math.round((watchdog.crv+1)/32768.0).coerceAtLeast(1)
        return "One initial restart is expected before normal operation. The original watchdog period is about $seconds seconds."
    }
    private fun pickResumeOriginal(option:InitialInstallResumeOption){
        require(snapshot.phase==InitialInstallPhase.IDLE&&selectedDigest==option.releaseSha256)
        resumeBindingId=option.bindingId;resumeRelease=option.releaseSha256;resumeDeviceName=selectedDevice;resumeCandidate=candidate;resumeOriginalUri=null
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
            .putExtra(Intent.EXTRA_MIME_TYPES,arrayOf("application/zip","application/octet-stream","application/x-zip-compressed"))
            .putExtra(android.provider.DocumentsContract.EXTRA_INITIAL_URI,Uri.parse(option.initialExportDocument)),RESUME_ORIGINAL)
    }
    private fun prepareRepair(option:InitialInstallResumeOption){
        val link=service?:return;val target=link.inspectedTarget.value?:return;val device=selectedDevice?:return
        val bytes=rawPackage?:return;val digest=selectedDigest?:return;val uri=resumeOriginalUri?:return
        require(foreground&&snapshot.phase==InitialInstallPhase.IDLE&&!busy&&resumeBindingId==option.bindingId&&resumeRelease==digest&&option.releaseSha256==digest&&resumeDeviceName==device&&resumeCandidate==candidate)
        require(link.resumeOptions.value.any{it.bindingId==option.bindingId&&it.releaseSha256==digest}){"The retained attempt changed. Read the target again."}
        val request=InstallCaptureRequest(UUID.randomUUID().toString(),device,target,digest)
        ContextCompat.startForegroundService(this,Intent(this,InitialInstallService::class.java).setAction(InitialInstallService.OPEN))
        if(candidate)link.prepareResumeCandidate(request,bytes,uri)else link.prepareResumeQualified(request,bytes,uri)
    }
    private fun resumeReview():ResumeOwnerReview?{
        val request=snapshot.request?:return null;val binding=snapshot.binding?:return null;val head=snapshot.resumeHeadSha256?:return null
        return ResumeOwnerReview(request.requestId,binding.id,request.reviewedReleaseSha256,head)
    }
    private fun reviewRepair(){
        val review=resumeReview()?:return
        AlertDialog.Builder(this).setTitle("Continue this repair?")
            .setMessage("${snapshot.resumeClassification?:"Repair the reviewed installation."}\n\nA rebuild resets custom settings created after first installation. The saved original backup is retained. Keep USB and power connected.")
            .setPositiveButton("Continue repair"){_,_->if(foreground&&snapshot.phase==InitialInstallPhase.AWAITING_RESUME_REVIEW&&resumeReview()==review)runCatching{service?.resume(review)}.onFailure{status.text=it.message?:"The repair preview changed. Review the current attempt again."}}
            .setNegativeButton("Cancel",null).show()
    }
    private fun reviewCapture(){
        val link=service?:return;val target=link.inspectedTarget.value?:return
        val bytes=rawPackage?:return;val digest=selectedDigest?:return;val device=selectedDevice?:return;val isCandidate=candidate
        AlertDialog.Builder(this).setTitle("Capture original firmware?").setMessage("The app will halt the selected nRF52840 and read all memory twice. Leave its wiring and power in place. Flash and UICR are not programmed during capture.")
            .setPositiveButton("Capture backup"){_,_->
                if(!foreground||snapshot.phase!=InitialInstallPhase.IDLE||busy||selectedDigest!=digest||candidate!=isCandidate||selectedDevice!=device||service!==link||link.inspectedTarget.value!=target){status.text="The selected release or target changed. Review the current target again.";return@setPositiveButton}
                val request=InstallCaptureRequest(UUID.randomUUID().toString(),device,target,digest)
                runCatching{ContextCompat.startForegroundService(this,Intent(this,InitialInstallService::class.java).setAction(InitialInstallService.OPEN))
                    if(isCandidate)link.beginCandidate(request,bytes)else link.beginQualified(request,bytes)}.onFailure{status.text=it.message?:"Capture could not start. Read the target again."}
            }.setNegativeButton("Cancel",null).show()
    }
    private fun ownerReview():InstallOwnerReview? {val request=snapshot.request?:return null;val binding=snapshot.binding?:return null;return InstallOwnerReview(request.requestId,binding.id,request.reviewedReleaseSha256)}
    private fun reviewInstall(){val review=ownerReview()?:return
        AlertDialog.Builder(this).setTitle(if(snapshot.candidate)"Install beta / local firmware?" else "Replace original firmware?")
            .setMessage("This writes the reviewed common firmware to the target shown above. Your verified original backup is saved on this phone. Keep the phone, DK and target connected. UICR is preserved.")
            .setPositiveButton("Install firmware"){_,_->if(foreground&&snapshot.phase==InitialInstallPhase.AWAITING_REVIEW&&ownerReview()==review)runCatching{service?.install(review)}.onFailure{status.text=it.message?:"Installation review changed. Review the current transaction again."}}.setNegativeButton("Cancel",null).show()}
    private fun reviewStart(){val review=ownerReview()?:return
        AlertDialog.Builder(this).setTitle("Start verified firmware?").setMessage("The app will reconnect to this exact target, recheck the complete installed image and UICR, then start from the new reset vector.")
            .setPositiveButton("Start firmware"){_,_->if(foreground&&snapshot.phase==InitialInstallPhase.VERIFIED_HALTED&&ownerReview()==review)runCatching{
                ContextCompat.startForegroundService(this,Intent(this,InitialInstallService::class.java).setAction(InitialInstallService.OPEN));service?.startVerifiedTarget(review)
            }.onFailure{status.text=it.message?:"The verified transaction changed. Review it again."}}.setNegativeButton("Cancel",null).show()}
    private fun newSession(){service?.newSession();pendingExportRequest=null;selectedDevice=null;resumeBindingId=null;resumeRelease=null;resumeDeviceName=null;resumeOriginalUri=null;render()}
    private fun leave(){if(active())AlertDialog.Builder(this).setTitle("Leave installation?").setMessage("The operation stays in the foreground service. Keep the USB connection in place; reopen this screen to continue.").setPositiveButton("Leave screen"){_,_->finish()}.setNegativeButton("Stay",null).show()else finish()}
    @Deprecated("Deprecated in Java")override fun onBackPressed()=leave()
    override fun onResume(){super.onResume();foreground=true;if(pendingPermission!=null){val device=manager.deviceList.values.firstOrNull{it.deviceName==selectedDevice&&manager.hasPermission(it)};if(device!=null){pendingPermission=null;inspect(device.deviceName)}}}
    override fun onPause(){foreground=false;super.onPause()}
    override fun onSaveInstanceState(out:Bundle){super.onSaveInstanceState(out);selectedUri?.let{out.putString("uri",it.toString())};out.putString("digest",selectedDigest);out.putBoolean("candidate",candidate);out.putString("device",selectedDevice);out.putString("exportRequest",pendingExportRequest);out.putString("permissionRequest",pendingPermission)
        out.putString("resumeOriginal",resumeOriginalUri?.toString());out.putString("resumeBinding",resumeBindingId);out.putString("resumeRelease",resumeRelease);out.putString("resumeDevice",resumeDeviceName);out.putBoolean("resumeCandidate",resumeCandidate)}
    @Deprecated("Deprecated in Java")override fun onActivityResult(requestCode:Int,resultCode:Int,data:Intent?){super.onActivityResult(requestCode,resultCode,data)
        val exportRequest=if(requestCode==ORIGINAL)pendingExportRequest.also{pendingExportRequest=null;renderActions()}else null
        if(resultCode!=RESULT_OK)return;val uri=data?.data?:return
        when(requestCode){
            PACKAGE->{if(active()){status.text="The current transaction already owns its reviewed release.";return};runCatching{contentResolver.takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION)};loadPackage(uri)}
            ORIGINAL->{if(snapshot.phase==InitialInstallPhase.AWAITING_EXPORT&&exportRequest!=null&&snapshot.request?.requestId==exportRequest)runCatching{
                // The receipt remains useful after process death when this
                // provider supports durable SAF grants. Providers that do not
                // support them still require exact same-document verification.
                runCatching{contentResolver.takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_WRITE_URI_PERMISSION)}
                service?.exportOriginal(uri,exportRequest)
            }.onFailure{status.text=it.message?:"Could not export the original backup"}}
            RESUME_ORIGINAL->{
                if(snapshot.phase!=InitialInstallPhase.IDLE){status.text="The active transaction already owns its reviewed backup.";return}
                runCatching{contentResolver.takePersistableUriPermission(uri,Intent.FLAG_GRANT_READ_URI_PERMISSION)}
                resumeOriginalUri=uri;status.text="Original backup selected. Read the target if needed, then explicitly prepare the repair preview.";renderActions()
            }
            BACKUP_COPY->{val hash=pendingExportRequest?:return;pendingExportRequest=null;scope.launch{runCatching{withContext(Dispatchers.IO){
                val bytes=AndroidInitialInstallPersistence(this@InitialInstallActivity).originalBytes(hash)
                val port=AndroidInitialInstallDocuments.export(contentResolver,uri){!isActive}
                require(port.create(bytes)==uri.toString());require(port.reopen(uri.toString()).contentEquals(bytes)){"Exported copy differs"}
            }}.onSuccess{status.text="Backup copy exported."}.onFailure{status.text=it.message?:"Could not export backup copy"}}}
            REPORT->{val text=diagnostic?:return;scope.launch{runCatching{withContext(Dispatchers.IO){contentResolver.openOutputStream(uri,"wt")?.use{it.write(text.toByteArray(Charsets.UTF_8))}?:error("Report destination unavailable")}}.onSuccess{status.text="Diagnostic report saved."}.onFailure{status.text=it.message?:"Could not save the report"}}}
        }
    }
    override fun onDestroy(){observing?.cancel();packageJob?.cancel();if(bound)unbindService(connection);unregisterReceiver(permissions);scope.cancel();super.onDestroy()}
    private companion object{const val PACKAGE=41;const val ORIGINAL=42;const val REPORT=43;const val RESUME_ORIGINAL=44;const val BACKUP_COPY=45}
}
