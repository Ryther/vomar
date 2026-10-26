package org.openvimar.updater

import android.app.Activity
import android.app.AlertDialog
import android.content.*
import android.content.pm.PackageManager
import android.content.res.ColorStateList
import android.content.res.Configuration
import android.graphics.Typeface
import android.net.Uri
import android.os.*
import android.text.TextUtils
import android.view.View
import android.view.Gravity
import android.widget.*
import androidx.core.view.ViewCompat
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.combine

/** A view of the service; presentation never grants BLE/update authority. */
class MainActivity : Activity() {
    private var service: UpdateService? = null
    private var bound = false
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var observing: Job? = null
    private var pendingExport: ByteArray? = null
    private var exportPreparing = false
    private var pendingImport: String? = null
    private var candidatePicker: BluetoothCandidatePicker? = null
    private var offerIdentityRecord = false
    private var current = SessionPresentation()
    private lateinit var fleet: NativeFleetUi
    private var message = ""
    private var optionsExpanded = false
    private var helpExpanded = false
    private var detailsExpanded = false
    private var renderedKey: String? = null
    private lateinit var screen: LinearLayout
    private lateinit var deviceHeader: LinearLayout
    private lateinit var packageLabel: TextView
    private lateinit var packageVersion: TextView
    private lateinit var verification: TextView
    private lateinit var actionsScroll: ScrollView
    private lateinit var content: LinearLayout
    private lateinit var stageTitle: TextView
    private lateinit var explanation: TextView
    private lateinit var status: TextView
    private lateinit var progress: ProgressBar
    private lateinit var primary: Button
    private lateinit var probe: Button
    private lateinit var stop: Button
    private lateinit var offline: Button
    private lateinit var resume: Button
    private lateinit var helpToggle: Button
    private lateinit var help: TextView
    private lateinit var optionsToggle: Button
    private lateinit var options: LinearLayout
    private lateinit var changePackage: Button
    private lateinit var export: Button
    private lateinit var detailsToggle: Button
    private lateinit var details: TextView

    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            val attached = (binder as UpdateService.LocalBinder).service
            service = attached
            observing?.cancel()
            observing = scope.launch {
                launch {
                    combine(attached.presentation, attached.status) { state, text -> state to text }.collect { (state, text) ->
                        current = state
                        message = text
                        fleet.serviceStatus(text)
                        fleet.historyStatus(attached.lastBootHistoryAddress,attached.lastBootHistoryMessage,state.busy)
                        render()
                        dispatchPendingImport()
                        if(offerIdentityRecord&&!state.busy&&text.startsWith("Paused:")){
                            offerIdentityRecord=false;showError(text)
                        }
                    }
                }
                launch { attached.commonReleasePending.collect { fleet.commonReleasePending(it) } }
                launch { attached.commonBootstrapAvailable.collect { fleet.commonBootstrapPending(it) } }
                launch {
                    attached.reportedIdentity.collect { observed ->
                        if(observed!=null&&offerIdentityRecord){
                            offerIdentityRecord=false
                            fleet.offerIdentity(observed.address,observed.identity.uid)
                        }
                    }
                }
                launch {
                    attached.reportedBootHistory.collect { observed ->
                        if(observed!=null){
                            val captured=observed.reportBytes()
                            fleet.historyResult(observed.address,observed.identity.uid,observed.observedAtMillis,observed.summary){exportHistorySnapshot(captured)}
                        }
                    }
                }
            }
            if (pendingImport != null) dispatchPendingImport()
            else if (!attached.presentation.value.inspected && !attached.presentation.value.busy) attached.inspect()
        }
        override fun onServiceDisconnected(name: ComponentName) { service = null; render() }
    }

    private fun dp(value: Int) = (value * resources.displayMetrics.density + 0.5f).toInt()
    private fun heading(value: TextView) { ViewCompat.setAccessibilityHeading(value, true) }
    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun label(size: Float = 16f, secondary: Boolean = false) = TextView(this).apply {
        textSize = size
        setTextColor(getColor(if (secondary) R.color.ui_text_secondary else R.color.ui_text))
        setTextIsSelectable(false)
    }
    private fun add(view: View, parent: LinearLayout = content, gap: Int = 8) {
        parent.addView(view, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(gap) })
    }
    private fun action(labelId: Int, parent: LinearLayout = content, filled: Boolean = false, utility: Boolean = false, run: () -> Unit): Button {
        val view = NativeUi.button(this,getString(labelId),filled,action=run).apply {
            textSize = if (utility) 14f else 16f
            gravity = if (utility) Gravity.START or Gravity.CENTER_VERTICAL else Gravity.CENTER
            minHeight = dp(48)
            minimumHeight = dp(48)
            setPaddingRelative(if (utility) 0 else dp(16), dp(10), if (utility) 0 else dp(16), dp(10))
            val foreground = when { filled -> R.color.ui_on_primary; utility -> R.color.ui_text_secondary; else -> R.color.ui_primary }
            setTextColor(ColorStateList(arrayOf(intArrayOf(android.R.attr.state_enabled), intArrayOf()),
                intArrayOf(getColor(foreground), getColor(R.color.ui_on_disabled))))
        }
        add(view, parent)
        return view
    }

    override fun attachBaseContext(newBase: Context) {
        super.attachBaseContext(NativeUi.themedContext(newBase))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        pendingExport = savedInstanceState?.getByteArray(EXPORT_SNAPSHOT)
        pendingImport = savedInstanceState?.getString("pendingImport")
        optionsExpanded = savedInstanceState?.getBoolean("optionsExpanded") ?: false
        helpExpanded = savedInstanceState?.getBoolean("helpExpanded") ?: false
        detailsExpanded = savedInstanceState?.getBoolean("detailsExpanded") ?: false
        screen = column().apply { setBackgroundColor(getColor(R.color.ui_surface)) }
        val columnInset = dp(20) + maxOf(0, (resources.displayMetrics.widthPixels - dp(600)) / 2)
        deviceHeader = column().apply { setPadding(columnInset, dp(16), columnInset, dp(12)) }
        packageLabel = label(20f).apply {
            setTypeface(typeface, Typeface.BOLD)
            maxLines = if (resources.configuration.screenHeightDp < 480) 1 else 2
            ellipsize = TextUtils.TruncateAt.END
            heading(this)
        }
        deviceHeader.addView(packageLabel, LinearLayout.LayoutParams(-1, -2))
        packageVersion = label(14f, true)
        add(packageVersion, deviceHeader, 4)
        verification = label(14f, true)
        add(verification, deviceHeader, 4)
        screen.addView(deviceHeader, LinearLayout.LayoutParams(-1, -2))
        content = column().apply {
            setPadding(dp(20), dp(8), dp(20), dp(24))
            // Wider windows retain a readable phone-sized task column.
            val maxWidth = dp(600)
            if (resources.displayMetrics.widthPixels > maxWidth) {
                val inset = (resources.displayMetrics.widthPixels - maxWidth) / 2
                setPadding(inset + dp(20), dp(8), inset + dp(20), dp(24))
            }
        }
        actionsScroll = ScrollView(this).apply { addView(content); isFillViewport = true }
        screen.addView(actionsScroll, LinearLayout.LayoutParams(-1, 0, 1f))
        stageTitle = label(22f).apply { setTypeface(typeface, Typeface.BOLD); heading(this) }
        add(stageTitle, gap=12)
        explanation = label(16f, true)
        add(explanation)
        status = label().apply { accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE }
        add(status, gap=16)
        progress = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            max = 100
            progressTintList = ColorStateList.valueOf(getColor(R.color.ui_primary))
            indeterminateTintList = ColorStateList.valueOf(getColor(R.color.ui_primary))
        }
        add(progress)
        primary = action(R.string.action_start, filled=true) { runPrimary() }
        probe = action(R.string.action_probe) {
            val available = freshActions()
            if (available?.canProbe == true) launchProbe()
            else if (available?.canRequestProbePermission == true) requestBluetooth()
        }
        stop = action(R.string.action_stop) { if (actions().canStop) service?.stopUpdate() }
        offline = action(R.string.action_offline) { if (freshActions()?.canConfirm == true) operator(false) }
        resume = action(R.string.action_resume_check) {
            val available = freshActions()
            if (available?.canRequestResumePermission == true) requestBluetooth()
            else if (available?.canResume == true) launchUpdate(true)
        }
        helpToggle = action(R.string.connection_help, utility=true) { helpExpanded = !helpExpanded; render() }
        help = label(16f, true).apply { text = getString(R.string.connection_help_text) }
        add(help)
        optionsToggle = action(R.string.more_options, utility=true) { optionsExpanded = !optionsExpanded; render() }
        options = column()
        add(options, gap=0)
        changePackage = action(R.string.change_package, options, utility=true) { if (actions().canImport) choosePackage() }
        export = action(R.string.action_export, options, utility=true) { if (freshActions()?.canExport == true) exportReport() }
        detailsToggle = action(R.string.action_details, options, utility=true) { detailsExpanded = !detailsExpanded; render() }
        details = label(14f, true).apply { setTextIsSelectable(true) }
        add(details, options)
        fleet = NativeFleetUi(this, screen, ::choosePackage, ::chooseZigbeeList, ::exportReport, ::requestBluetooth, ::searchBluetooth, ::prepareBluetoothUpdate)
        fleet.setHistoryReader(::readRecoveryHistory)
        fleet.restoreState(savedInstanceState)
        setContentView(fleet.root)
        if (Build.VERSION.SDK_INT >= 33) onBackInvokedDispatcher.registerOnBackInvokedCallback(
            android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT) { if (!fleet.back()) finish() }
        NativeUi.systemBars(this)
        fleet.root.requestApplyInsets()
        render()
    }

    private fun permissionsReady() = PermissionPolicy.required(Build.VERSION.SDK_INT).all { checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED }
    private fun readRecoveryHistory(record:DeviceRecord){
        val address=record.address?:return
        if(!permissionsReady()){requestBluetooth();showError("Grant Bluetooth permissions, then choose Read recovery history again.");return}
        val attached=service?:run{showError("The Bluetooth service is connecting. Try again in a moment.");return}
        runCatching{attached.inspectBootHistory(address,record.uid.takeIf{it.size==2})}
            .onSuccess{accepted->if(accepted)fleet.historyStarted(record)else showError("Wait for the current Bluetooth operation to finish before reading history.")}
            .onFailure{showError(it.message?:"Recovery history could not be read. Check Bluetooth and try again.")}
    }
    private fun exportHistorySnapshot(bytes:ByteArray){
        if(pendingExport!=null||exportPreparing){showError("Finish choosing a destination for the current report first.");return}
        pendingExport=bytes.copyOf()
        runCatching{startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).setType("application/json").addCategory(Intent.CATEGORY_OPENABLE)
            .putExtra(Intent.EXTRA_TITLE,"vimar-recovery-history.json"),EXPORT)}
            .onFailure{pendingExport=null;showError(it.message?:"Choose a location for the history report.")}
    }
    private fun actions() = UiPolicy.actions(current, permissionsReady(), service != null)
    private fun shown(view: View, visible: Boolean) { view.visibility = if (visible) View.VISIBLE else View.GONE }
    private fun render() {
        if (!::primary.isInitialized) return
        val pkg = current.packageSummary
        packageLabel.text = pkg?.name ?: getString(R.string.no_device)
        packageLabel.contentDescription = pkg?.name ?: getString(R.string.no_device)
        packageLabel.tooltipText = pkg?.name
        packageVersion.text = pkg?.let { getString(R.string.target_version, it.targetVersion) } ?: getString(R.string.select_package_hint)
        verification.text = getString(when {
            !current.loaded -> R.string.selection_not_verified
            current.imagesVerified -> R.string.firmware_verified
            current.bluetoothVerified -> R.string.bluetooth_previously_verified
            else -> R.string.package_verified
        })
        shown(verification, pkg != null)
        val key = pkg?.let { it.digest + it.address }
        if (key != renderedKey) {
            renderedKey = key
            optionsExpanded = false; detailsExpanded = false
            actionsScroll.scrollTo(0, 0)
        }
        val policy = actions()
        val loading = service == null || !current.inspected || current.busy
        val result = current.loaded && current.imagesVerified
        val title = when {
            current.busy -> when(current.operation) {
                SessionOperation.IMPORT -> R.string.importing_package
                SessionOperation.PROBE -> R.string.checking_bluetooth
                SessionOperation.UPDATE -> R.string.installing_firmware
                SessionOperation.EXPORT -> R.string.preparing_report
                SessionOperation.OPERATOR -> R.string.saving_outcome
                SessionOperation.PREPARE -> R.string.checking_resume
                else -> R.string.preparing_session
            }
            !current.inspected || service == null -> R.string.preparing_session
            !current.loaded || pkg == null -> R.string.package_step
            result -> if(current.operatorOnline == true) R.string.result_recorded else R.string.result_step
            !permissionsReady() -> R.string.prepare_step
            current.hasCheckpoint -> R.string.resume_step
            else -> R.string.ready_step
        }
        stageTitle.setText(title)
        explanation.setText(when {
            current.busy && current.operation == SessionOperation.PROBE -> R.string.probe_explanation
            current.busy && current.operation in listOf(SessionOperation.UPDATE,SessionOperation.IMPORT) -> R.string.stop_explanation
            loading -> R.string.wait_for_session
            !current.loaded || pkg == null -> R.string.empty_package
            result && current.operatorOnline == true -> R.string.online_recorded_help
            result -> R.string.result_instructions
            !permissionsReady() -> R.string.permission_explanation
            else -> R.string.ready_instructions
        })
        val compactBusy = current.busy && current.operation in listOf(SessionOperation.EXPORT, SessionOperation.OPERATOR, SessionOperation.PREPARE)
        shown(explanation, !compactBusy)
        val visibleMessage = UpdateCopy.visibleStatus(message)
        status.text = visibleMessage
        shown(status, !compactBusy && visibleMessage.isNotBlank() && !visibleMessage.startsWith("Import a ZIP package to begin"))
        val displayedProgress = current.progressPercent.takeIf { current.operation == SessionOperation.UPDATE }
        status.accessibilityLiveRegion = if(current.busy && displayedProgress != null) View.ACCESSIBILITY_LIVE_REGION_NONE else View.ACCESSIBILITY_LIVE_REGION_POLITE
        shown(progress, loading)
        progress.isIndeterminate = displayedProgress == null
        displayedProgress?.let { progress.progress=it }
        progress.contentDescription = if(displayedProgress != null) getString(R.string.progress_percent,displayedProgress) else getString(title)
        val primaryLabel = when(policy.primary) {
            PrimaryAction.IMPORT -> R.string.action_import
            PrimaryAction.PERMISSIONS -> R.string.action_permissions
            PrimaryAction.START -> R.string.action_start
            PrimaryAction.RESUME -> R.string.action_resume
            PrimaryAction.CONFIRM_ONLINE -> R.string.action_online
            PrimaryAction.EXPORT -> R.string.action_export
            PrimaryAction.NONE -> R.string.action_start
        }
        primary.setText(primaryLabel)
        shown(primary,policy.primary != PrimaryAction.NONE && pendingImport == null)
        primary.isEnabled = policy.primary != PrimaryAction.NONE && pendingImport == null
        shown(probe,(policy.canProbe && !result) || (result && current.operatorOnline == false && (policy.canProbe || policy.canRequestProbePermission)))
        probe.isEnabled = policy.canProbe || policy.canRequestProbePermission
        probe.setText(if(policy.canRequestProbePermission) R.string.permission_for_probe else R.string.action_probe)
        shown(stop,policy.canStop)
        shown(offline,policy.canConfirm)
        shown(resume,result && (policy.canResume || (policy.canRequestResumePermission && current.operatorOnline != false)) && !current.resetAcknowledged)
        resume.setText(if(policy.canRequestResumePermission) R.string.permission_for_resume else R.string.action_resume_check)
        shown(helpToggle,pkg != null && !result)
        helpToggle.isEnabled = !current.busy
        helpToggle.setText(if(helpExpanded) R.string.hide_connection_help else R.string.connection_help)
        ViewCompat.setStateDescription(helpToggle, getString(if(helpExpanded) R.string.section_open else R.string.section_closed))
        shown(help,helpExpanded && pkg != null && !result)
        shown(optionsToggle,pkg != null || current.reportAvailable)
        optionsToggle.isEnabled = !current.busy
        optionsToggle.setText(if(optionsExpanded) R.string.fewer_options else R.string.more_options)
        ViewCompat.setStateDescription(optionsToggle, getString(if(optionsExpanded) R.string.section_open else R.string.section_closed))
        shown(options,optionsExpanded && !current.busy)
        shown(changePackage,policy.canImport)
        shown(export,policy.canExport && policy.primary != PrimaryAction.EXPORT)
        shown(detailsToggle,pkg != null)
        detailsToggle.setText(if(detailsExpanded) R.string.hide_details else R.string.action_details)
        ViewCompat.setStateDescription(detailsToggle, getString(if(detailsExpanded) R.string.section_open else R.string.section_closed))
        details.text = pkg?.let { getString(R.string.package_details,it.address,it.uid.joinToString(" "),it.digest,it.mainHash,it.migrationVersion) } ?: ""
        // Full name remains available for long identities truncated only in the pinned header.
        if(pkg != null) details.text = pkg.name + "\n" + details.text
        shown(details,detailsExpanded && pkg != null)
        if (::fleet.isInitialized) fleet.present(current)
    }

    /** Bind every device action to the identity actually rendered, not merely the newest package. */
    private fun freshActions(): UiActions? {
        val attached = service ?: return null
        val fresh = attached.presentation.value
        if (fresh.packageSummary != current.packageSummary) {
            current = fresh
            render()
            showError(getString(R.string.device_changed))
            return null
        }
        return UiPolicy.actions(fresh, permissionsReady(), true)
    }
    private fun runPrimary() {
        when(freshActions()?.primary) {
            PrimaryAction.IMPORT -> choosePackage()
            PrimaryAction.PERMISSIONS -> requestBluetooth()
            PrimaryAction.START -> { primary.isEnabled=false; launchUpdate(false) }
            PrimaryAction.RESUME -> { primary.isEnabled=false; launchUpdate(true) }
            PrimaryAction.CONFIRM_ONLINE -> operator(true)
            PrimaryAction.EXPORT -> exportReport()
            else -> Unit
        }
    }
    internal fun refreshSelectedSession(){service?.refresh()}
    internal fun showUpdateSession() { fleet.showSession() }
    @Deprecated("Android compatibility fallback")
    override fun onBackPressed() { if (!fleet.back()) super.onBackPressed() }

    private fun chooseZigbeeList() {
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            type="application/json"; addCategory(Intent.CATEGORY_OPENABLE)
        }, IMPORT_ZIGBEE)
    }
    private fun choosePackage() {
        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply { type="application/zip";addCategory(Intent.CATEGORY_OPENABLE) },IMPORT)
    }
    private fun dispatchPendingImport() {
        val uri = pendingImport ?: return
        val attached = service ?: return
        if (attached.presentation.value.busy) return
        try {
            // Keep the service started; direct admission avoids racing an automatic inspection.
            startService(Intent(this,UpdateService::class.java))
            if(attached.importDocument(uri)) pendingImport=null
        }catch(failure:Exception){pendingImport=null;showError(failure.message ?: getString(R.string.import_failed))}
    }
    private fun exportReport() {
        if(pendingExport!=null||exportPreparing){showError("Finish choosing a destination for the current report first.");return}
        exportPreparing=true
        scope.launch {
            try {
                captureExportSnapshot()
                try {
                    startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                        type="application/json";addCategory(Intent.CATEGORY_OPENABLE);putExtra(Intent.EXTRA_TITLE,"vimar-update-report.json")
                    },EXPORT)
                }catch(failure:Exception){pendingExport=null;throw failure}
            }catch(failure:CancellationException){throw failure}
            catch(failure:Exception){showError(failure.message ?: getString(R.string.report_missing))}
            finally{exportPreparing=false}
        }
    }
    override fun onStart(){super.onStart();bound=bindService(Intent(this,UpdateService::class.java),connection,Context.BIND_AUTO_CREATE)}
    override fun onResume(){super.onResume();render();if(::fleet.isInitialized)fleet.resume()}
    override fun onStop(){candidatePicker?.close();observing?.cancel();if(bound)unbindService(connection);bound=false;service=null;super.onStop()}

    private fun searchBluetooth(){
        if(!bluetoothReadyForAction())return
        if(current.busy){showError("Wait for the current operation to finish.");return}
        candidatePicker?.close()
        candidatePicker=BluetoothCandidatePicker(this).also { picker ->
            picker.show(allowLegacy=service?.commonReleasePending?.value==true&&!fleet.isRegisteringDevice()) { address ->
                val attached=service ?: return@show
                offerIdentityRecord=true
                val common=attached.commonReleasePending.value&&!fleet.isRegisteringDevice()
                val accepted=if(common)attached.selectCommonTarget(address) else attached.inspectIdentity(address)
                if(!accepted)offerIdentityRecord=false
                if(common)fleet.showSession()
            }
        }
    }
    internal fun stopCurrentUpdate(){service?.stopUpdate()}
    private fun prepareBluetoothUpdate(){
        if(!bluetoothReadyForAction())return
        val attached=service ?: return
        fun begin(confirmed:Boolean){
            val intent=Intent(this,UpdateService::class.java).setAction(UpdateService.BOOTSTRAP)
                .putExtra(UpdateService.CONFIRMED,confirmed)
            androidx.core.content.ContextCompat.startForegroundService(this,intent)
        }
        if(attached.bootstrapResetUncertain.value){
            AlertDialog.Builder(this).setTitle("Confirm another restart request")
                .setMessage("The previous restart response was lost. Keep the dimmer powered. Send another restart request only if it has not moved to the next stage.")
                .setNegativeButton("Cancel",null).setPositiveButton("Send restart request"){_,_->begin(true)}.show()
        }else begin(false)
    }

    private fun requestBluetooth() {
        val missing = PermissionPolicy.required(Build.VERSION.SDK_INT).filter { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isNotEmpty()) requestPermissions(missing.toTypedArray(), PERMISSIONS)
        else if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), PERMISSIONS)
        } else { message = getString(R.string.permissions_ready); render() }
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != PERMISSIONS) return
        val bluetoothReady = PermissionPolicy.required(Build.VERSION.SDK_INT).all {
            checkSelfPermission(it) == PackageManager.PERMISSION_GRANTED
        }
        message = if (bluetoothReady) {
            getString(R.string.permissions_ready)
        } else {
            getString(R.string.permissions_denied)
        }
        render()
    }

    private fun bluetoothReadyForAction(): Boolean {
        if (service == null) { showError(getString(R.string.service_loading)); return false }
        if (PermissionPolicy.required(Build.VERSION.SDK_INT).any { checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }) {
            showError(getString(R.string.permissions_request))
            requestBluetooth()
            return false
        }
        return true
    }

    private fun launchProbe() {
        if (!bluetoothReadyForAction()) return
        try {
            startForegroundService(Intent(this, UpdateService::class.java).setAction(UpdateService.PROBE))
        } catch (failure: Exception) {
            showError(failure.message ?: "Bluetooth check did not start")
        }
    }

    private fun launchUpdate(resume: Boolean) {
        if (!bluetoothReadyForAction()) return
        val reviewedTarget = current.packageSummary
        scope.launch {
            try {
                if (resume) {
                    val offer = service!!.prepareResume()
                    if (offer.needsConfirmation) showResetRetryConfirmation(reviewedTarget) { sendUpdate(true, offer.id, true) }
                    else sendUpdate(true, offer.id, false)
                } else sendUpdate(false, null, false)
            } catch (failure: CancellationException) {
                throw failure
            } catch (failure: Exception) {
                showError(failure.message ?: "Cannot read saved progress. Export the report for diagnosis.")
                render()
            }
        }
    }

    internal fun showResetRetryConfirmation(target: PackageSummary? = current.packageSummary, onAuthorized: () -> Unit): AlertDialog {
        val explanation = getString(R.string.reset_confirmation)
        val reviewedMessage = target?.let { getString(R.string.reset_confirmation_device, it.name, it.targetVersion, explanation) } ?: explanation
        return AlertDialog.Builder(this).setTitle(R.string.reset_confirmation_title)
            .setMessage(reviewedMessage)
            .setNegativeButton(R.string.action_cancel, null)
            .setPositiveButton(R.string.action_authorize_reset) { _, _ -> onAuthorized() }.show()
    }

    private fun sendUpdate(resume: Boolean, offerId: String?, confirmed: Boolean) {
        current.packageSummary?.let { fleet.beginBatch(it, resume) }
        startForegroundService(Intent(this, UpdateService::class.java).apply {
            action = if (resume) UpdateService.RESUME else UpdateService.START
            putExtra(UpdateService.CONFIRMED, confirmed)
            putExtra(UpdateService.OFFER, offerId)
        })
    }

    private fun operator(online: Boolean) {
        try {
            service?.confirmOperator(online)
        } catch (failure: Exception) {
            showError(failure.message ?: "Result was not saved")
        }
    }

    @Deprecated("Platform activity result API remains supported on API26–35")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if(requestCode==EXPORT){
            // The result consumes exactly the snapshot promised to this picker.
            // Cancellation, a missing URI and provider failure all permit an
            // explicit retry. A stale result cannot select a newer report.
            val bytes=pendingExport.also{pendingExport=null}
            val destination=data?.data
            if(resultCode!=RESULT_OK||destination==null)return
            if(bytes==null){showError("The selected report is no longer available. Choose Save report again.");return}
            scope.launch{
                try{
                    withContext(Dispatchers.IO){contentResolver.openOutputStream(destination)?.use{it.write(bytes)}?:error("Destination unavailable. Choose another location for the report.")}
                    message=getString(R.string.report_exported);render()
                }catch(failure:CancellationException){throw failure}
                catch(failure:Exception){showError(failure.message?:"The report could not be saved. Choose another destination and retry.")}
            }
            return
        }
        val uri: Uri = data?.data ?: return
        if (resultCode != RESULT_OK) return
        scope.launch {
            try {
                when (requestCode) {
                    IMPORT_ZIGBEE -> {
                        val text = withContext(Dispatchers.IO) {
                            contentResolver.openInputStream(uri)?.use { input ->
                                val output=java.io.ByteArrayOutputStream(); val buffer=ByteArray(8192)
                                while(true) { val count=input.read(buffer); if(count<0)break
                                    require(output.size()+count<=2*1024*1024) { "Device list exceeds 2 MB. Export a smaller list." }
                                    output.write(buffer,0,count)
                                }
                                output.toString("UTF-8")
                            } ?: error("Cannot open this device list. Choose another JSON file.")
                        }
                        fleet.acceptZigbeeList(text)
                    }
                    IMPORT -> {
                        fleet.showSession()
                        pendingImport = uri.toString()
                        dispatchPendingImport()
                    }
                }
            } catch (failure: CancellationException) {
                throw failure
            } catch (failure: Exception) {
                showError(failure.message ?: "Document unavailable")
            }
        }
    }

    /** Snapshot binds the picker destination to the selected report at the user’s export action. */
    internal suspend fun captureExportSnapshot() {
        check(pendingExport==null){"Finish choosing a destination for the current report first."}
        val bytes=AndroidSessionOwner.get(applicationContext).report()
        check(pendingExport==null){"A report destination is already being selected."}
        pendingExport=bytes.copyOf()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        if (::fleet.isInitialized) fleet.saveState(outState)
        outState.putByteArray(EXPORT_SNAPSHOT, pendingExport)
        outState.putString("pendingImport", pendingImport)
        outState.putBoolean("optionsExpanded", optionsExpanded)
        outState.putBoolean("helpExpanded", helpExpanded)
        outState.putBoolean("detailsExpanded", detailsExpanded)
        super.onSaveInstanceState(outState)
    }

    private fun showError(message: String) {
        AlertDialog.Builder(this).setTitle(R.string.error_title).setMessage(UpdateCopy.failure(message)).setPositiveButton(R.string.action_close, null).show()
    }

    override fun onDestroy() {
        candidatePicker?.close()
        scope.cancel()
        if (::fleet.isInitialized) fleet.close()
        super.onDestroy()
    }

    companion object {
        private const val EXPORT_SNAPSHOT = "exportReportSnapshot"
        private const val IMPORT = 1
        private const val EXPORT = 2
        private const val PERMISSIONS = 3
        private const val IMPORT_ZIGBEE = 4
    }
}
