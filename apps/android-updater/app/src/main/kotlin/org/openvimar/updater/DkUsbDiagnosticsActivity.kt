package org.openvimar.updater

import android.app.Activity
import android.app.AlertDialog
import android.app.PendingIntent
import android.content.*
import android.content.pm.PackageManager
import android.hardware.usb.*
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.provider.DocumentsContract
import android.view.View
import android.widget.*
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.io.File
import java.time.Instant
import java.util.Locale
import java.util.UUID

/** Explicit, read-only USB diagnostics. No device is opened until the user
 * selects Test and Android grants access. This Activity has no flashing API. */
class DkUsbDiagnosticsActivity : Activity() {
    override fun attachBaseContext(newBase:Context){super.attachBaseContext(NativeUi.themedContext(newBase))}
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val manager by lazy { getSystemService(USB_SERVICE) as UsbManager }
    private lateinit var status: TextView
    private lateinit var details: TextView
    private lateinit var test: Button
    private lateinit var identityTest: Button
    private lateinit var watchStart: Button
    private lateinit var watchStop: Button
    private lateinit var watchExport: Button
    private val watch=DkSwdWatchPolicy()
    private var watchJob:Job?=null
    private var showingWatch=false
    private var restoredWatchReport:String?=null
    private var pendingWatchExport:String?=null
    private var watchPermissionDenied=false
    private data class WatchPermission(val token:DkSwdWatchToken,val deviceName:String,val uri:String,val result:CompletableDeferred<Boolean>)
    private var watchPermission:WatchPermission?=null
    @Volatile private var foreground=false
    private var watchAccessSession=""
    private var watchStartedAt:String?=null
    private var backupStateLoaded=false
    private val usbLock=Any()
    private var activeConnection:UsbDeviceConnection?=null
    private lateinit var backupTest: Button
    private lateinit var backupStatus: TextView
    private lateinit var backupProgress: ProgressBar
    private lateinit var backupStop: Button
    private lateinit var backupSave: Button
    private lateinit var export: Button
    private lateinit var detailsToggle:Button
    private var detailsExpanded=false
    private var report = JSONObject()
    private var pendingDevice: String? = null
    private enum class Operation { USB, SWD_IDENTITY, BACKUP }
    private var pendingOperation = Operation.USB
    private var busy = false
    private var backupRunning = false
    private var backupService: DkBackupService? = null
    private var backupBound = false
    private var backupStateJob: Job? = null
    private var verifiedBackup: File? = null
    private var pendingBackupExport: String? = null
    private val backupConnection=object: ServiceConnection {
        override fun onServiceConnected(name: ComponentName,binder: IBinder) {
            backupService=(binder as DkBackupService.LocalBinder).service
            backupStateJob?.cancel()
            backupStateJob=scope.launch {backupService!!.state.collect {renderBackup(it)}}
        }
        override fun onServiceDisconnected(name: ComponentName) {
            backupService=null;backupStateLoaded=false;backupStateJob?.cancel()
            backupRunning=false;backupStatus.text="Backup service disconnected; partial data is unavailable"
            updateButtons()
        }
    }
    private val permissionAction get() = "$packageName.DK_USB_PERMISSION"
    private val permissionReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            if (intent.action != permissionAction) return
            if(intent.dataString?.startsWith("vimar-updater://usb-watch/")==true) {
                val pending=watchPermission ?: return
                if(intent.dataString!=pending.uri||!foreground||!watch.accepts(pending.token))return
                val device=manager.deviceList.values.firstOrNull {it.deviceName==pending.deviceName}
                pending.result.complete(device!=null&&manager.hasPermission(device));return
            }
            if(!foreground||watch.snapshot().running||watch.snapshot().inFlight)return
            // onResume may already have consumed the permission grant. Ignore a
            // delayed/duplicate broadcast instead of overwriting its result.
            val requestedDevice = pendingDevice ?: return
            if (busy) return
            val device = manager.deviceList.values.firstOrNull { it.deviceName == requestedDevice }
            if (device != null && manager.hasPermission(device)) probe(device)
            else {
                pendingDevice = null
                recordFailure("USB permission was not granted. Tap Test DK to retry.")
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        NativeUi.systemBars(this)
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(16), dp(20), dp(24))
            setBackgroundColor(getColor(R.color.ui_surface))
        }
        fun text(value: String, size: Float = 15f) = NativeUi.label(this,value,size.toInt()).apply {setPadding(0,dp(6),0,dp(6))}
        fun button(label: String,primary:Boolean=false,action: () -> Unit) = NativeUi.button(this,label,primary,action=action)
        fun add(view:View,gap:Int=8){body.addView(view,LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(gap)})}
        add(NativeUi.taskHeader(this,"DK tools"){finish()},0)
        add(text("Connect the DK’s J-Link USB port to your phone with a USB host adapter."),0)
        status = text("Ready to look for a target",16f).apply {
            accessibilityLiveRegion=View.ACCESSIBILITY_LIVE_REGION_POLITE
            setPadding(dp(16),dp(16),dp(16),dp(16));background=NativeUi.shape(this@DkUsbDiagnosticsActivity,getColor(R.color.ui_panel),10)
            minimumHeight=dp(72)
        }
        add(status,12)
        test = button("Check USB connection") { discover(Operation.USB) }
        identityTest = button("Read target identity (SWD)") { discover(Operation.SWD_IDENTITY) }
        watchStart=button("Start SWD monitor",true) {startWatch()}
        watchStop=button("Stop monitor") {stopWatch()}.apply {isEnabled=false;visibility=View.GONE}
        val watchActions=LinearLayout(this).apply{gravity=android.view.Gravity.CENTER_VERTICAL}
        watchActions.addView(watchStart,LinearLayout.LayoutParams(0,-2,1f))
        watchActions.addView(watchStop,LinearLayout.LayoutParams(0,-2,1f).apply{marginStart=dp(8)})
        add(watchActions)
        add(text("Adjust the contacts until nRF52840 is detected. Stop the monitor before starting a backup."),4)
        add(NativeUi.label(this,"Original firmware backup",20,true),24)
        add(text("Two matching copies of the device memory. Keep the DK and target connected while both passes finish."),4)
        backupTest=button("Create verified backup") {discover(Operation.BACKUP)};add(backupTest)
        backupStatus=text("Your verified backup will be available to save here.").apply {accessibilityLiveRegion=View.ACCESSIBILITY_LIVE_REGION_POLITE};add(backupStatus,4)
        backupProgress=ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal).apply {
            max=1000;visibility=View.GONE;progressTintList=android.content.res.ColorStateList.valueOf(getColor(R.color.ui_primary))
        }
        body.addView(backupProgress,LinearLayout.LayoutParams(-1,dp(6)).apply{topMargin=dp(8)})
        backupStop=button("Stop backup") {backupService?.cancelBackup()
            ?: startService(Intent(this,DkBackupService::class.java).setAction(DkBackupService.STOP))}.apply {isEnabled=false}
        add(backupStop)
        backupSave=button("Save backup to files or cloud") {
            verifiedBackup?.let {file->
                pendingBackupExport=file.name
                startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                    type="application/zip";addCategory(Intent.CATEGORY_OPENABLE);putExtra(Intent.EXTRA_TITLE,file.name)
                },602)
            }
        }.apply {isEnabled=false}
        add(backupSave)
        add(NativeUi.label(this,"Checks and reports",20,true),24)
        val extraChecks=LinearLayout(this).apply {orientation=LinearLayout.VERTICAL;visibility=View.GONE}
        extraChecks.addView(test,LinearLayout.LayoutParams(-1,-2));extraChecks.addView(identityTest,LinearLayout.LayoutParams(-1,-2))
        extraChecks.addView(text("These tools only read the target. They do not halt, reset, erase or program it. Backups stay on this phone until you save them."))
        add(NativeUi.disclosure(this,"More connection checks","Hide connection checks",extraChecks))
        add(extraChecks,0)
        export = button("Save diagnostic report") {
            startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                type = "application/json"; addCategory(Intent.CATEGORY_OPENABLE)
                putExtra(Intent.EXTRA_TITLE, "dk-usb-${System.currentTimeMillis()}.json")
            }, 601)
        }
        add(export)
        watchExport=button("Save monitor report") {exportWatch()}.apply {isEnabled=false};add(watchExport,0)
        details = text("No diagnostic report yet.").apply {setTextIsSelectable(true);visibility=View.GONE}
        detailsToggle=button("Technical details") {detailsExpanded=!detailsExpanded;updateButtons()}
        add(detailsToggle,0);add(details,0)
        val viewport=ScrollView(this).apply {isFillViewport=true;setBackgroundColor(getColor(R.color.ui_surface));NativeUi.insets(this);addView(body)}
        val centered=FrameLayout(this).apply {
            setBackgroundColor(getColor(R.color.ui_surface))
            addView(viewport,FrameLayout.LayoutParams(-1,-1,android.view.Gravity.TOP or android.view.Gravity.CENTER_HORIZONTAL))
        }
        centered.addOnLayoutChangeListener{_,_,_,_,_,_,_,_,_->
            val width=minOf(centered.width,dp(720));val params=viewport.layoutParams as FrameLayout.LayoutParams
            if(width>0&&params.width!=width){params.width=width;viewport.layoutParams=params}
        }
        setContentView(centered)
        ContextCompat.registerReceiver(this, permissionReceiver, IntentFilter(permissionAction), ContextCompat.RECEIVER_NOT_EXPORTED)
        restoredWatchReport=savedInstanceState?.getString("watchReport")?.let {raw->runCatching {
            JSONObject(raw).put("running",false).put("attemptInFlight",false).put("restoredWithoutAutomaticResume",true).toString(2)
        }.getOrNull()}
        pendingWatchExport=savedInstanceState?.getString("pendingWatchExport")
        detailsExpanded=savedInstanceState?.getBoolean("detailsExpanded",false) ?: false
        showingWatch=savedInstanceState?.getBoolean("showingWatch",false) ?: false
        pendingDevice = savedInstanceState?.getString("pendingDevice")
        pendingBackupExport=savedInstanceState?.getString("pendingBackupExport")
        pendingOperation = savedInstanceState?.getString("pendingOperation")?.let {
            runCatching { Operation.valueOf(it) }.getOrDefault(Operation.USB)
        } ?: Operation.USB
        savedInstanceState?.getString("report")?.let {
            runCatching { report = JSONObject(it); showReport() }
        }
        export.isEnabled = report.length() > 0
        if(showingWatch){status.text="Monitor stopped when this screen closed. Tap Start SWD monitor to try again.";details.visibility=View.GONE}
        updateButtons()
    }

    override fun onStart() {
        super.onStart()
        foreground=true;backupStateLoaded=false;updateButtons()
        backupBound=bindService(Intent(this,DkBackupService::class.java),backupConnection,BIND_AUTO_CREATE)
    }
    override fun onStop() {
        foreground=false;stopWatch();closeActiveUsb()
        backupStateJob?.cancel();backupStateJob=null
        if(backupBound)unbindService(backupConnection)
        backupBound=false;backupService=null;backupStateLoaded=false
        super.onStop()
    }
    private fun updateButtons() {
        val monitoring=watch.snapshot().let {it.running||it.inFlight}||watchJob?.isCompleted==false
        val available=backupStateLoaded&&!busy&&!backupRunning&&!monitoring&&pendingDevice==null
        test.isEnabled=available
        identityTest.isEnabled=available
        backupTest.isEnabled=available
        watchStart.isEnabled=available
        watchStop.isEnabled=watch.snapshot().running
        watchStop.visibility=if(monitoring)View.VISIBLE else View.GONE
        watchExport.isEnabled=!busy&&(watch.snapshot().totalAttempts>0||restoredWatchReport!=null)
        watchExport.visibility=if(watch.snapshot().totalAttempts>0||restoredWatchReport!=null)View.VISIBLE else View.GONE
        backupStop.isEnabled=backupRunning
        backupSave.isEnabled=verifiedBackup!=null&&!backupRunning&&!monitoring
        export.isEnabled=report.length()>0&&!busy
        export.text=if(showingWatch)"Save previous diagnostic report" else "Save diagnostic report"
        details.visibility=if(!showingWatch&&detailsExpanded)View.VISIBLE else View.GONE
        export.visibility=if(report.length()>0)View.VISIBLE else View.GONE
        detailsToggle.visibility=if(showingWatch||report.length()==0)View.GONE else View.VISIBLE
        detailsToggle.text=if(detailsExpanded)"Hide technical details" else "Technical details"
        backupStop.visibility=if(backupRunning)View.VISIBLE else View.GONE
        backupSave.visibility=if(verifiedBackup!=null)View.VISIBLE else View.GONE
        backupStatus.visibility=if(showingWatch&&!backupRunning)View.GONE else View.VISIBLE
    }
    private fun renderBackup(state: DkBackupServiceState) {
        backupStateLoaded=true
        if(state.running&&watch.snapshot().running)stopWatch()
        backupRunning=state.running;verifiedBackup=state.verifiedFile
        backupStatus.text=state.message
        backupProgress.visibility=if(state.running)View.VISIBLE else View.GONE
        backupProgress.isIndeterminate=state.running&&state.progress==null
        state.progress?.let {backupProgress.progress=(it.completedBytes*1000/it.totalBytes).toInt()}
        state.diagnostic?.let {snapshot->
            // Opening the running service from its notification can create a fresh
            // Activity. A replayed old ZIP has no attempt snapshot to adopt.
            if(report.length()==0)report=JSONObject().put("schema",1).put("type","dk-backup-request")
                .put("backupRequestId",snapshot.requestId).put("timestamp",snapshot.observations["startedAt"] ?: Instant.now().toString())
                .put("androidApi",Build.VERSION.SDK_INT).put("phoneModel",Build.MODEL)
                .put("appVersion",snapshot.observations["appVersion"] ?: packageManager.getPackageInfo(packageName,0).versionName ?: "Unknown")
                .put("resetAttempted",false).put("haltAttempted",false).put("memoryWrite",false)
                .put("eraseAttempted",false).put("flashed",false).put("targetSupplyChanged",false)
            snapshot.fieldsFor(report.optString("backupRequestId").takeIf {it.isNotEmpty()})?.let {fields->
                fields.forEach {(key,value)->report.put(key,if(value is Map<*,*>)JSONObject(value) else value)}
                export.isEnabled=true
                showReport()
            }
        }
        updateButtons()
    }

    override fun onResume() {
        super.onResume()
        watchPermission?.let {pending->
            if(watch.accepts(pending.token)&&manager.deviceList.values.any {it.deviceName==pending.deviceName&&manager.hasPermission(it)})pending.result.complete(true)
        }
        if (!busy&&backupStateLoaded) pendingDevice?.let { name ->
            manager.deviceList.values.firstOrNull { it.deviceName == name && manager.hasPermission(it) }?.let { probe(it) }
        }
    }

    private fun discover(operation: Operation) {
        if (busy || backupRunning || !backupStateLoaded || watch.snapshot().let{it.running||it.inFlight} || watchJob?.isCompleted==false || pendingDevice!=null) return
        showingWatch=false;details.visibility=View.VISIBLE
        pendingOperation = operation
        report = JSONObject().put("schema", 1)
            .put("type", when(operation) {Operation.USB->"dk-usb-read-only";Operation.SWD_IDENTITY->"dk-swd-read-only";Operation.BACKUP->"dk-backup-request"})
            .put("timestamp", Instant.now().toString()).put("androidApi", Build.VERSION.SDK_INT)
            .put("phoneModel", Build.MODEL)
            .put("appVersion", packageManager.getPackageInfo(packageName, 0).versionName ?: "Unknown")
            .put("swdAttempted", false).put("memoryRead", false).put("flashed", false)
            .put("resetAttempted", false).put("haltAttempted", false).put("memoryWrite", false)
            .put("eraseAttempted", false).put("targetSupplyChanged", false)
        if(operation==Operation.BACKUP)report.put("backupRequestId",UUID.randomUUID().toString())
        val host = packageManager.hasSystemFeature(PackageManager.FEATURE_USB_HOST)
        report.put("usbHostSupported", host)
        val devices = manager.deviceList.values.toList()
        report.put("usbDevices", JSONArray().apply {
            devices.forEach { device ->
                put(JSONObject().put("vendorId", device.vendorId).put("productId", device.productId)
                    .put("class", device.deviceClass).put("subclass", device.deviceSubclass)
                    .put("protocol", device.deviceProtocol).put("interfaces", device.interfaceCount)
                    .put("interfaceDescriptors", JSONArray(describeInterfaces(device).map { it.reportFields() })))
            }
        })
        if (!host) { recordFailure("This phone does not report USB host support."); return }
        val candidates = devices.filter { it.vendorId == 0x1366 && it.productId == 0x1060 }
        when (candidates.size) {
            0 -> recordFailure(if (devices.any { it.vendorId == 0x1366 })
                "A SEGGER device was found, but this diagnostic currently supports J-Link 1366:1060 only. Save the report."
                else "DK not found. Check the USB data cable, OTG adapter and the DK's J-Link port, then tap Test DK.")
            1 -> requestAccess(candidates.single())
            else -> AlertDialog.Builder(this).setTitle("Choose DK")
                .setItems(candidates.map { it.deviceName }.toTypedArray()) { _, index -> requestAccess(candidates[index]) }
                .setNegativeButton("Cancel", null).show()
        }
    }

    private fun requestAccess(device: UsbDevice) {
        pendingDevice = device.deviceName
        updateButtons()
        if (manager.hasPermission(device)) { probe(device); return }
        status.text = "Allow USB access in Android"
        manager.requestPermission(device, PendingIntent.getBroadcast(this, 0,
            Intent(permissionAction).setPackage(packageName), PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE))
    }

    private fun probe(device: UsbDevice) {
        if (busy || backupRunning || !backupStateLoaded || watch.snapshot().let{it.running||it.inFlight}) return
        pendingDevice = null
        val operation = pendingOperation
        val selection = DkJlinkInterfaceSelector.select(device.vendorId, device.productId, describeInterfaces(device))
        report.put("interfaceSelection", JSONObject(selection.reportFields()))
        if (selection.error != null) { recordFailure(selection.error); return }
        if(operation==Operation.BACKUP) {
            try {
                ContextCompat.startForegroundService(this,Intent(this,DkBackupService::class.java)
                    .setAction(DkBackupService.START).putExtra(DkBackupService.DEVICE,device.deviceName)
                    .putExtra(DkBackupService.REQUEST_ID,report.getString("backupRequestId")))
                backupRunning=true;verifiedBackup=null;backupStatus.text="Starting read-only double backup";updateButtons()
                export.isEnabled=true;showReport()
            } catch(error: Exception) {backupRunning=false;backupStatus.text=error.message ?: "Android could not start the backup service";recordFailure(backupStatus.text.toString())}
            return
        }
        busy = true; test.isEnabled = false; identityTest.isEnabled = false; export.isEnabled = false
        updateButtons()
        status.text = if (operation == Operation.USB) "Reading J-Link diagnostics…" else "Reading target identity over SWD…"
        scope.launch {
            var usbObserved: JSONObject? = null
            val swdObserved = linkedMapOf<String, Any>()
            try {
                val observed = withContext(Dispatchers.IO) {
                    readDevice(device, selection, operation, swdObserved) { usbObserved = it }
                }
                report.put("probe", observed).put("success", true)
                status.text = if (operation == Operation.USB) "DK USB communication works" else "Target chip identity read"
            } catch (error: Exception) {
                if (error is CancellationException) throw error
                report.put("success", false).put("error", error.message ?: error.javaClass.simpleName)
                status.text = if (operation == Operation.USB) "DK test could not complete" else "SWD identity read could not complete"
            } finally {
                usbObserved?.let { report.put("probe", it) }
                if (operation == Operation.SWD_IDENTITY) {
                    report.put("swd", JSONObject(swdObserved))
                        .put("swdAttempted", swdObserved["swdLineSynchronizationAttempted"] == true)
                        .put("memoryReadAttempted", swdObserved["ficrReadAttempted"] == true)
                        .put("memoryRead", swdObserved.containsKey("part"))
                    usbObserved?.put("swdVerified", swdObserved["dpidr"] == "0x2ba01477")
                }
                busy = false; updateButtons(); export.isEnabled = true
                showReport()
            }
        }
    }

    private fun describeInterfaces(device: UsbDevice): List<DkUsbInterfaceDescriptor> =
        (0 until device.interfaceCount).map { index ->
            val port = device.getInterface(index)
            DkUsbInterfaceDescriptor(index, port.id, port.alternateSetting, port.interfaceClass,
                port.interfaceSubclass, port.interfaceProtocol, port.name,
                (0 until port.endpointCount).map { endpointIndex ->
                    val endpoint = port.getEndpoint(endpointIndex)
                    DkUsbEndpointDescriptor(endpoint.address, endpoint.attributes, endpoint.maxPacketSize, endpoint.interval)
                })
        }

    private fun readDevice(device: UsbDevice, selection: DkJlinkInterfaceSelection,
        operation: Operation, swdObserved: MutableMap<String, Any>,
        onObservation: (String,Any)->Unit={_,_->}, checkActive:()->Unit={scope.ensureActive();if(!foreground)throw CancellationException("Screen is not active")},
        onUsbObserved: (JSONObject) -> Unit): JSONObject {
        checkActive()
        if (!manager.hasPermission(device)) throw IOException("USB permission is missing")
        val selected = selection.port ?: throw IOException(selection.error ?: "J-Link interface was not selected")
        val port = device.getInterface(selected.index)
        val endpoints = (0 until port.endpointCount).map(port::getEndpoint)
        val input = endpoints.singleOrNull { it.address == selection.input?.address }
            ?: throw IOException("J-Link input endpoint is missing")
        val output = endpoints.singleOrNull { it.address == selection.output?.address }
            ?: throw IOException("J-Link output endpoint is missing")
        val usbLease=DkUsbOperationGate.acquire(if(operation==Operation.USB)"USB diagnostics" else "SWD identity monitor") ?: run {
            onObservation("usbOperationBusy",true)
            throw IOException("The DK is in use by another operation. Wait for it to finish or stop it first.")
        }
        try {
            val connection = manager.openDevice(device) ?: throw IOException("Android could not open the DK")
            var claimed = false
            try {
                synchronized(usbLock){checkActive();activeConnection=connection}
                claimed = connection.claimInterface(port, false)
                if (!claimed) throw IOException("J-Link interface is busy; close other USB tools and retry")
                val channel = DkSwdBufferedChannel(object : DkBulkChannel {
                    override fun write(bytes: ByteArray): Int {
                        usbLease.checkCurrent();checkActive()
                        val count=connection.bulkTransfer(output, bytes, bytes.size, 2000)
                        checkActive();return count
                    }
                    override fun read(maxBytes: Int): ByteArray {
                        usbLease.checkCurrent();checkActive()
                        val buffer = ByteArray(maxBytes)
                        val count = connection.bulkTransfer(input, buffer, buffer.size, 2000)
                        usbLease.checkCurrent();checkActive()
                        if (count <= 0) throw IOException("J-Link USB read timed out or the DK was disconnected")
                        return buffer.copyOf(count)
                    }
                })
                val observed = DkJlinkReadOnly.probe(channel)
                val probeReport = JSONObject().put("vendorId", device.vendorId).put("productId", device.productId)
                    .put("interface", port.id).put("interfaceIndex", selected.index).put("alternateSetting", port.alternateSetting)
                    .put("inputEndpoint", input.address).put("outputEndpoint", output.address)
                    .put("firmware", observed.firmware).put("targetMillivolts", observed.targetMillivolts)
                    .put("targetVoltage", String.format(Locale.ROOT, "%.3f V", observed.targetMillivolts / 1000.0))
                    .put("swdVerified", false)
                onUsbObserved(probeReport)
                if (operation == Operation.SWD_IDENTITY) {
                    if (observed.targetMillivolts !in 1700..3600)
                        throw IOException("Target reference voltage is outside 1.7–3.6 V; SWD was not started")
                    DkSwdReadOnly.probe(channel) { key, value -> checkActive();swdObserved[key] = value;onObservation(key,value) }
                }
                return probeReport
            } finally {
                synchronized(usbLock){if(activeConnection===connection)activeConnection=null}
                try{if(claimed)connection.releaseInterface(port)}finally{connection.close()}
            }
        } finally {usbLease.close()}
    }

    private fun recordFailure(message: String) {
        report.put("success", false).put("error", message)
        status.text = message; updateButtons(); export.isEnabled = true; showReport()
    }

    private fun showReport() {
        if(showingWatch){details.visibility=View.GONE;return}
        val probe=report.optJSONObject("probe")
        val swd=report.optJSONObject("swd")
        val backup=report.optJSONObject("backup")
        fun optional(section: JSONObject?,key: String)=section?.takeIf {it.has(key)&&!it.isNull(key)}?.optString(key)
        details.text=DkDiagnosticPresentation.format(DkDiagnosticReportView(
            type=report.optString("type"),raw=report.toString(2),
            success=if(report.has("success")&&!report.isNull("success"))report.optBoolean("success") else null,
            probeFirmware=optional(probe,"firmware"),targetVoltage=optional(probe,"targetVoltage"),
            targetChip=optional(swd,"targetChip"),uid=swd?.optJSONArray("uid")?.toString(),
            backupPhase=optional(backup,"phase"),backupOutcome=optional(backup,"outcome"),
            backupMessage=optional(backup,"message"),error=optional(report,"error")))
    }

    @Deprecated("Legacy Activity document-result API")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if(requestCode==602&&resultCode==RESULT_OK) {
            val uri=data?.data ?: return
            val name=pendingBackupExport ?: return
            pendingBackupExport=null
            scope.launch {
                try {
                    withContext(Dispatchers.IO) {
                        val file=DkBackupStore(File(filesDir,DkBackupService.DIRECTORY)).resolveVerified(name)
                            ?: throw IOException("The verified private backup is unavailable")
                        val context=currentCoroutineContext()
                        val output=contentResolver.openOutputStream(uri) ?: throw IOException("Could not open the backup destination")
                        output.use {destination->file.inputStream().use {source->
                            val bytes=ByteArray(8192)
                            while(true) {context.ensureActive();val count=source.read(bytes);if(count<0)break;destination.write(bytes,0,count)}
                        }}
                    }
                    backupStatus.text="Verified backup saved"
                } catch(error: Exception) {
                    withContext(NonCancellable+Dispatchers.IO) {runCatching {DocumentsContract.deleteDocument(contentResolver,uri)}}
                    if(error !is CancellationException)backupStatus.text="Backup could not be saved: ${error.message}"
                }
            }
            return
        }
        if(requestCode==603) {
            val snapshot=pendingWatchExport;pendingWatchExport=null
            if(resultCode==RESULT_OK&&snapshot!=null)data?.data?.let {uri->
                try {val output=contentResolver.openOutputStream(uri) ?: throw IOException("Could not open the report destination")
                    output.use{it.write(snapshot.toByteArray(Charsets.UTF_8))};status.text="Monitor report saved. The previous diagnostic report is unchanged."}
                catch(error:Exception){status.text="Monitor report could not be saved: ${error.message}"}
            }
            return
        }
        if (requestCode == 601 && resultCode == RESULT_OK) data?.data?.let { uri ->
            try {
                val output = contentResolver.openOutputStream(uri) ?: throw IOException("Could not open the report destination")
                output.use { it.write(report.toString(2).toByteArray(Charsets.UTF_8)) }
                Toast.makeText(this, "Diagnostic report saved", Toast.LENGTH_SHORT).show()
            } catch (error: Exception) { status.text = "Report could not be saved: ${error.message}" }
        }
    }

    override fun onSaveInstanceState(outState: Bundle) {
        stopWatch()
        outState.putString("watchReport",watchReportText());outState.putString("pendingWatchExport",pendingWatchExport)
        outState.putBoolean("showingWatch",showingWatch)
        outState.putBoolean("detailsExpanded",detailsExpanded)
        outState.putString("report", report.toString()); outState.putString("pendingDevice", pendingDevice)
        outState.putString("pendingOperation", pendingOperation.name)
        outState.putString("pendingBackupExport",pendingBackupExport)
        super.onSaveInstanceState(outState)
    }

    override fun onDestroy() {
        stopWatch();closeActiveUsb();unregisterReceiver(permissionReceiver); scope.cancel(); super.onDestroy()
    }
    private fun closeActiveUsb() {
        val connection=synchronized(usbLock){activeConnection.also{activeConnection=null}}
        runCatching{connection?.close()}
    }
    private fun renderWatch() {
        if(!showingWatch)return
        val current=watch.snapshot()
        if(status.text.toString()!=current.message)status.text=current.message
        status.setTextColor(getColor(when(current.kind){
            DkSwdWatchKind.IDENTITY->R.color.ui_current
            DkSwdWatchKind.SWD_PARTIAL,DkSwdWatchKind.VOLTAGE->R.color.ui_available
            else->R.color.ui_text
        }))
        details.visibility=View.GONE;updateButtons()
    }
    private fun stopWatch() {
        if(!watch.stop()&&watchJob?.isCompleted!=false)return
        watchPermission?.result?.cancel();watchPermission=null
        watchJob?.cancel();closeActiveUsb()
        restoredWatchReport=JSONObject(watch.reportFields()).toString(2)
        if(showingWatch)renderWatch()
    }
    private fun watchReportText():String? = if(watch.snapshot().totalAttempts>0)JSONObject(watch.reportFields())
        .put("androidApi",Build.VERSION.SDK_INT).put("phoneModel",Build.MODEL).put("startedAt",watchStartedAt)
        .put("appVersion",packageManager.getPackageInfo(packageName,0).versionName ?: "Unknown").toString(2) else restoredWatchReport
    private fun exportWatch() {
        stopWatch()
        scope.launch {
            watchJob?.join()
            val snapshot=watchReportText() ?: return@launch
            pendingWatchExport=snapshot
            startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                type="application/json";addCategory(Intent.CATEGORY_OPENABLE)
                putExtra(Intent.EXTRA_TITLE,"dk-swd-monitor-${System.currentTimeMillis()}.json")
            },603)
        }
    }
    private fun startWatch() {
        if(!foreground||!backupStateLoaded||busy||backupRunning||pendingDevice!=null||watchJob?.isCompleted==false||!watch.start())return
        showingWatch=true;restoredWatchReport=null;watchPermissionDenied=false;watchAccessSession=UUID.randomUUID().toString();watchStartedAt=Instant.now().toString()
        renderWatch()
        status.post {if(showingWatch&&foreground)status.requestRectangleOnScreen(android.graphics.Rect(0,0,status.width,status.height+watchStop.height),true)}
        watchJob=scope.launch {
            try {
                while(watch.snapshot().running) {
                    val token=watch.beginAttempt() ?: break
                    var failure:String?=null
                    try {
                        fun observe(key:String,value:Any) {
                            if(watch.observe(token,key,value))scope.launch {if(foreground&&watch.accepts(token))renderWatch()}
                        }
                        val devices=manager.deviceList.values.filter{it.vendorId==0x1366&&it.productId==0x1060}
                        observe("dkPresent",devices.isNotEmpty())
                        if(!packageManager.hasSystemFeature(PackageManager.FEATURE_USB_HOST))throw IOException("USB host is unavailable")
                        if(devices.isEmpty())throw IOException("DK absent")
                        if(devices.size!=1){observe("ambiguousDk",true);throw IOException("Connect only one DK")}
                        val device=devices.single();observe("usbDeviceName",device.deviceName)
                        observe("usbPermissionGranted",manager.hasPermission(device))
                        if(!manager.hasPermission(device)) {
                            if(watchPermissionDenied)throw IOException("USB permission was denied; stop and start to retry")
                            val result=CompletableDeferred<Boolean>()
                            val uri="vimar-updater://usb-watch/$watchAccessSession/${token.generation}/${token.attempt}"
                            watchPermission=WatchPermission(token,device.deviceName,uri,result)
                            manager.requestPermission(device,PendingIntent.getBroadcast(this@DkUsbDiagnosticsActivity,84,
                                Intent(permissionAction).setPackage(packageName).setData(android.net.Uri.parse(uri)),
                                PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE))
                            val granted=result.await();watchPermission=null
                            if(!granted){watchPermissionDenied=true;observe("usbPermissionDenied",true);throw IOException("USB permission denied")}
                            observe("usbPermissionGranted",true)
                        }
                        val selection=DkJlinkInterfaceSelector.select(device.vendorId,device.productId,describeInterfaces(device))
                        selection.error?.let{throw IOException(it)}
                        withContext(Dispatchers.IO) {
                            val context=currentCoroutineContext()
                            val checkActive={context.ensureActive();if(!foreground||!watch.accepts(token))throw CancellationException("Monitor stopped")}
                            readDevice(device,selection,Operation.SWD_IDENTITY,linkedMapOf(),::observe,checkActive) {probe->
                                observe("probeFirmware",probe.getString("firmware"));observe("targetMillivolts",probe.getInt("targetMillivolts"))
                            }
                        }
                    } catch(error:CancellationException){failure="Monitor stopped";throw error}
                    catch(error:Exception){failure=error.message ?: error.javaClass.simpleName}
                    finally {watch.complete(token,failure);if(foreground)renderWatch()}
                    delay(1000)
                }
            } finally {
                closeActiveUsb()
                if(foreground&&showingWatch)renderWatch()
                updateButtons()
            }
        }
        watchJob?.invokeOnCompletion{if(foreground)updateButtons()}
    }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
}
