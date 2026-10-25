package org.openvimar.updater

import android.content.Intent
import android.content.pm.ActivityInfo
import android.test.ActivityInstrumentationTestCase2
import kotlinx.coroutines.*
import org.openvimar.updater.core.*
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec
import java.util.concurrent.atomic.AtomicInteger

/** Real Activity/service attachments, injected fake BLE, no radio. Requires emulator/device execution. */
@Suppress("DEPRECATION")
class ActivityLifecycleTest : ActivityInstrumentationTestCase2<MainActivity>(MainActivity::class.java) {
    private val harnesses=mutableListOf<Harness>()
    private val openedActivities=java.util.concurrent.CopyOnWriteArrayList<android.app.Activity>()
    private val lifecycle=object:android.app.Application.ActivityLifecycleCallbacks{
        override fun onActivityCreated(activity:android.app.Activity,state:android.os.Bundle?){if(activity is MainActivity)openedActivities.add(activity)}
        override fun onActivityDestroyed(activity:android.app.Activity){openedActivities.remove(activity)}
        override fun onActivityStarted(activity:android.app.Activity){}
        override fun onActivityResumed(activity:android.app.Activity){}
        override fun onActivityPaused(activity:android.app.Activity){}
        override fun onActivityStopped(activity:android.app.Activity){}
        override fun onActivitySaveInstanceState(activity:android.app.Activity,state:android.os.Bundle){}
    }
    override fun setUp(){super.setUp();(instrumentation.targetContext.applicationContext as android.app.Application).registerActivityLifecycleCallbacks(lifecycle)}
    private inner class Harness {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val assets = instrumentation.context.assets
        val pkg = PackageValidator.validate(PackageReader.read(assets.open("synthetic-update.zip")),
            KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(assets.open("synthetic-public.der").use { it.readBytes() })), "0.1.0")
        @Volatile var checkpoint: Checkpoint? = null
        @Volatile var primary = RemoteImage(pkg.manifest.allowedSourceSignedHashes.first(), false, true)
        val uploads = AtomicInteger()
        val resets = AtomicInteger()
        val connects = AtomicInteger()
        var connectAction: suspend () -> Unit = {}
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        var slowImport = false
        val importEntered = CompletableDeferred<Unit>()
        val importRelease = CompletableDeferred<Unit>()
        val selections = AtomicInteger()
        var selected: ValidatedPackage? = pkg
        var packageReads = 0
        var operatorOnline: Boolean? = null
        var reportPresent = false
        var reportBytes = "{\"device\":\"first\"}".toByteArray()
        val reportReads = AtomicInteger()
        val controller = SessionController(scope, object : SessionStore {
            override suspend fun load(bundleDigest: String, address: String) = checkpoint
            override suspend fun save(checkpoint: Checkpoint) { this@Harness.checkpoint = checkpoint }
        }, { packageReads++; selected }, { operatorOnline }, { _, checkActive, commit ->
            if (slowImport) {
                importEntered.complete(Unit)
                withContext(NonCancellable) { importRelease.await() }
            }
            checkActive()
            commit { selections.incrementAndGet() }
        }, {
            object : BleTransport {
                override suspend fun connect(address: String) { connects.incrementAndGet(); connectAction() }
                override suspend fun images() = RemoteImages(primary, RemoteImage(pkg.manifest.targetRecoverySignedHash, true, true))
                override suspend fun upload(data: ByteArray, onAck: suspend (Int) -> Unit) {
                    uploads.incrementAndGet(); entered.complete(Unit); release.await()
                    onAck(data.size); primary = RemoteImage(pkg.manifest.main.signedRegionSha256, false, true)
                }
                override suspend fun reset(): ResetAck { resets.incrementAndGet(); return ResetAck.ACKNOWLEDGED }
                override suspend fun close() { }
            }
        }, { _, online, _ -> operatorOnline=online; reportPresent=true }, { reportReads.incrementAndGet(); reportBytes }, { true }, { reportPresent })
    }

    private fun waitIdle(controller: SessionController) = runBlocking { withTimeout(10000) { controller.awaitIdle() } }

    private fun grantForegroundPrerequisites() {
        PermissionPolicy.required(android.os.Build.VERSION.SDK_INT).forEach { permission ->
            instrumentation.uiAutomation.executeShellCommand("pm grant ${instrumentation.targetContext.packageName} $permission").use { descriptor ->
                java.io.FileInputStream(descriptor.fileDescriptor).use { it.readBytes() }
            }
        }
        instrumentation.runOnMainSync { instrumentation.callActivityOnResume(activity) }
        instrumentation.waitForIdleSync()
    }

    private fun waitInspection(h: Harness) {
        runBlocking { withTimeout(15000) { while(!h.controller.presentation.value.inspected || h.controller.presentation.value.busy) delay(20) } }
        instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync { activity.showUpdateSession() }
        instrumentation.waitForIdleSync()
    }

    private fun capture(name: String) {
        val rendered = java.util.concurrent.CountDownLatch(1)
        instrumentation.runOnMainSync {
            activity.window.decorView.postOnAnimation { activity.window.decorView.postOnAnimation { rendered.countDown() } }
        }
        assertTrue(rendered.await(10, java.util.concurrent.TimeUnit.SECONDS))
        instrumentation.uiAutomation.waitForIdle(1000, 10000)
        val cfg=instrumentation.targetContext.resources.configuration
        val suffix="${cfg.screenWidthDp}x${cfg.screenHeightDp}-${cfg.fontScale}-${cfg.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK}"
        val bitmap=instrumentation.uiAutomation.takeScreenshot()
        assertNotNull(bitmap)
        java.io.File(instrumentation.targetContext.cacheDir,"ui-$name-$suffix.png").outputStream().use {
            assertTrue(bitmap.compress(android.graphics.Bitmap.CompressFormat.PNG,100,it))
        }
    }

    override fun tearDown() {
        val context=instrumentation.targetContext
        try{
            // Each case replaces the process owner with a different fake. Close
            // every recreated Activity before destroying its old bound Service.
            // Otherwise the next case can bind to the preceding fake owner.
            harnesses.forEach{it.controller.stop();it.release.complete(Unit);it.importRelease.complete(Unit);it.scope.cancel()}
            instrumentation.runOnMainSync{openedActivities.toList().forEach{it.finish()}}
            instrumentation.waitForIdleSync()
            context.stopService(Intent(context,UpdateService::class.java))
            runBlocking{withTimeout(15000){
                harnesses.forEach{it.controller.awaitIdle()}
                val manager=context.getSystemService(android.app.ActivityManager::class.java)
                while(manager.getRunningServices(100).any{it.service.className==UpdateService::class.java.name})delay(20)
            }}
            instrumentation.waitForIdleSync()
            AndroidSessionOwner.installForTest(null)
        }finally{
            (context.applicationContext as android.app.Application).unregisterActivityLifecycleCallbacks(lifecycle)
            super.tearDown()
        }
    }

    fun testActiveReadOnlyProbeKeepsStopAvailableAndOtherActionsInactive() {
        val h=Harness();val entered=CompletableDeferred<Unit>();val release=CompletableDeferred<Unit>()
        h.connectAction={entered.complete(Unit);release.await()}
        AndroidSessionOwner.installForTest(h.controller)
        val opened=activity
        waitInspection(h);grantForegroundPrerequisites()
        assertTrue(h.controller.probe())
        runBlocking { withTimeout(15000){entered.await()} }
        instrumentation.waitForIdleSync()
        try {
            instrumentation.runOnMainSync {
                val stop=MainActivity::class.java.getDeclaredField("stop").apply{isAccessible=true}.get(opened) as android.widget.Button
                assertTrue(stop.isShown && stop.isEnabled)
                val primary=MainActivity::class.java.getDeclaredField("primary").apply{isAccessible=true}.get(opened) as android.view.View
                assertFalse(primary.isShown)
                val options=MainActivity::class.java.getDeclaredField("optionsToggle").apply{isAccessible=true}.get(opened) as android.view.View
                assertFalse(options.isEnabled)
            }
            capture("busy-probe")
            assertEquals(0,h.uploads.get()+h.resets.get())
            instrumentation.runOnMainSync {
                val stop=MainActivity::class.java.getDeclaredField("stop").apply{isAccessible=true}.get(opened) as android.widget.Button
                stop.performClick()
            }
            waitIdle(h.controller)
            assertEquals(0,h.uploads.get()+h.resets.get())
        }finally{release.complete(Unit);h.controller.stop();waitIdle(h.controller);h.scope.cancel()}
    }

    fun testEmptySessionOnlyOffersImportWithoutAnyBluetoothOperation() {
        val h=Harness();h.selected=null
        AndroidSessionOwner.installForTest(h.controller)
        val opened=activity
        waitInspection(h)
        instrumentation.runOnMainSync {
            val primary=MainActivity::class.java.getDeclaredField("primary").apply{isAccessible=true}.get(opened) as android.widget.Button
            assertEquals(opened.getString(R.string.action_import),primary.text.toString())
            for(name in listOf("probe","offline","resume","stop")) {
                val view=MainActivity::class.java.getDeclaredField(name).apply{isAccessible=true}.get(opened) as android.view.View
                assertFalse(view.isShown)
            }
        }
        assertEquals(0,h.connects.get()+h.resets.get()+h.uploads.get())
        capture("empty")
        h.scope.cancel()
    }

    fun testRestoredPartialSessionOffersResumeAndAccessibleHeadings() {
        val h=Harness()
        h.selected=h.pkg.copy(manifest=h.pkg.manifest.copy(device=h.pkg.manifest.device.copy(name="Studio · Dimmer con nome molto lungo per verificare la leggibilità e il destinatario sempre riconoscibile")))
        h.checkpoint=Checkpoint(bundleDigest=h.pkg.bundleDigest,bleAddress=h.pkg.manifest.device.bleAddress,phase=Phase.UPLOAD_MAIN)
        AndroidSessionOwner.installForTest(h.controller)
        val opened=activity
        waitInspection(h);grantForegroundPrerequisites()
        instrumentation.runOnMainSync {
            val primary=MainActivity::class.java.getDeclaredField("primary").apply{isAccessible=true}.get(opened) as android.widget.Button
            assertEquals(opened.getString(R.string.action_resume),primary.text.toString())
            assertTrue(primary.isEnabled)
            assertTrue(primary.height >= (48*opened.resources.displayMetrics.density).toInt())
            for(name in listOf("packageLabel","stageTitle")) {
                val view=MainActivity::class.java.getDeclaredField(name).apply{isAccessible=true}.get(opened) as android.view.View
                assertTrue(androidx.core.view.ViewCompat.isAccessibilityHeading(view))
            }
            val header=MainActivity::class.java.getDeclaredField("packageLabel").apply{isAccessible=true}.get(opened) as android.view.View
            val location=IntArray(2);header.getLocationOnScreen(location)
            if(android.os.Build.VERSION.SDK_INT>=30) {
                val top=opened.window.decorView.rootWindowInsets.getInsetsIgnoringVisibility(android.view.WindowInsets.Type.statusBars() or android.view.WindowInsets.Type.displayCutout()).top
                assertTrue("Long device identity must not overlap the status bar: ${location[1]} < $top",location[1]>=top)
            }
        }
        assertEquals(0,h.connects.get())
        capture("resume-long-name")
        h.scope.cancel()
    }

    fun testManualOnlineResultCanBeCorrectedWithoutAnyReset() {
        val h=Harness()
        h.checkpoint=Checkpoint(bundleDigest=h.pkg.bundleDigest,bleAddress=h.pkg.manifest.device.bleAddress,phase=Phase.AWAIT_OPERATOR)
        h.operatorOnline=true;h.reportPresent=true
        AndroidSessionOwner.installForTest(h.controller)
        val opened=activity
        waitInspection(h)
        capture("result")
        instrumentation.runOnMainSync {
            val offline=MainActivity::class.java.getDeclaredField("offline").apply{isAccessible=true}.get(opened) as android.widget.Button
            assertTrue(offline.isShown)
            offline.performClick()
        }
        waitIdle(h.controller)
        assertEquals(false,h.operatorOnline)
        assertEquals(0,h.connects.get()+h.resets.get()+h.uploads.get())
        h.scope.cancel()
    }

    fun testSecondaryResumeRejectsADeviceDifferentFromTheRenderedIdentity() {
        val h=Harness()
        h.checkpoint=Checkpoint(bundleDigest=h.pkg.bundleDigest,bleAddress=h.pkg.manifest.device.bleAddress,phase=Phase.AWAIT_OPERATOR)
        AndroidSessionOwner.installForTest(h.controller)
        val opened=activity
        waitInspection(h);grantForegroundPrerequisites()
        val old=h.controller.presentation.value
        h.selected=h.pkg.copy(bundleDigest="b".repeat(64),manifest=h.pkg.manifest.copy(device=h.pkg.manifest.device.copy(name="Secondo dimmer",bleAddress="AA:BB:CC:DD:EE:02")))
        h.checkpoint=h.checkpoint!!.copy(bundleDigest=h.selected!!.bundleDigest,bleAddress=h.selected!!.manifest.device.bleAddress)
        assertTrue(h.controller.inspect());waitIdle(h.controller);instrumentation.waitForIdleSync()
        val reads=h.packageReads
        instrumentation.runOnMainSync {
            // Model a delayed screen frame while the authoritative selected package has changed.
            MainActivity::class.java.getDeclaredField("current").apply{isAccessible=true}.set(opened,old)
            val resume=MainActivity::class.java.getDeclaredField("resume").apply{isAccessible=true}.get(opened) as android.widget.Button
            assertTrue(resume.isShown)
            resume.performClick()
        }
        waitIdle(h.controller)
        assertEquals(reads,h.packageReads)
        assertEquals(0,h.connects.get()+h.resets.get()+h.uploads.get())
        h.scope.cancel()
    }

    fun testBluetoothProbeButtonConnectsWithoutUploadOrReset() {
        val h = Harness()
        AndroidSessionOwner.installForTest(h.controller)
        val opened = activity
        waitInspection(h)
        try {
            grantForegroundPrerequisites()
            instrumentation.waitForIdleSync()
            var probe: android.widget.Button? = null
            instrumentation.runOnMainSync {
                fun find(view: android.view.View) {
                    if (view is android.widget.Button && view.text.toString() == opened.getString(R.string.action_probe)) probe = view
                    if (view is android.view.ViewGroup) for (i in 0 until view.childCount) find(view.getChildAt(i))
                }
                find(opened.findViewById(android.R.id.content))
            }
            assertNotNull("Read-only Bluetooth verification must be available", probe)
            instrumentation.runOnMainSync { probe!!.performClick() }
            runBlocking { withTimeout(10000) { while (h.connects.get() == 0) delay(20) } }
            waitIdle(h.controller)
            assertEquals(1, h.connects.get())
            assertEquals(0, h.uploads.get())
            assertEquals(0, h.resets.get())
            assertNull(h.checkpoint)
        } finally { h.controller.stop(); h.scope.cancel() }
    }

    fun testDeviceHeaderAndActionsStayInsideSystemBarAndCutoutBounds() {
        val h = Harness()
        AndroidSessionOwner.installForTest(h.controller)
        val opened = activity
        waitInspection(h)
        try {
            instrumentation.waitForIdleSync()
            val safe = android.graphics.Rect()
            val statusBounds = android.graphics.Rect()
            val actionsBounds = android.graphics.Rect()
            var insetsAvailable = false
            instrumentation.runOnMainSync {
                val decor = opened.window.decorView
                val insets = decor.rootWindowInsets
                if (insets != null) {
                    insetsAvailable = true
                    val location = IntArray(2)
                    decor.getLocationOnScreen(location)
                    val edge = if (android.os.Build.VERSION.SDK_INT >= 30) {
                        insets.getInsets(android.view.WindowInsets.Type.systemBars() or android.view.WindowInsets.Type.displayCutout()).let {
                            intArrayOf(it.left, it.top, it.right, it.bottom)
                        }
                    } else {
                        @Suppress("DEPRECATION")
                        val legacy = intArrayOf(insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                            insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
                        if (android.os.Build.VERSION.SDK_INT >= 28) insets.displayCutout?.let {
                            legacy[0] = maxOf(legacy[0], it.safeInsetLeft); legacy[1] = maxOf(legacy[1], it.safeInsetTop)
                            legacy[2] = maxOf(legacy[2], it.safeInsetRight); legacy[3] = maxOf(legacy[3], it.safeInsetBottom)
                        }
                        legacy
                    }
                    safe.set(location[0] + edge[0], location[1] + edge[1],
                        location[0] + decor.width - edge[2], location[1] + decor.height - edge[3])
                    fun bounds(view: android.view.View, out: android.graphics.Rect) {
                        view.getLocationOnScreen(location)
                        out.set(location[0], location[1], location[0] + view.width, location[1] + view.height)
                    }
                    val field = MainActivity::class.java.getDeclaredField("packageLabel").apply { isAccessible = true }
                    val status = field.get(opened) as android.widget.TextView
                    bounds(status, statusBounds)
                    val scrollField = MainActivity::class.java.getDeclaredField("actionsScroll").apply { isAccessible = true }
                    bounds(scrollField.get(opened) as android.view.View, actionsBounds)
                }
            }
            assertTrue("WindowInsets must be available", insetsAvailable)
            assertTrue("Status $statusBounds must stay inside safe bounds $safe", safe.contains(statusBounds))
            assertTrue("Scrollable actions $actionsBounds must stay inside safe bounds $safe", safe.contains(actionsBounds))
            capture("ready")
        } finally { h.scope.cancel() }
    }

    fun testDeviceHeaderRemainsVisibleOutsideScrollableActions() {
        val h = Harness()
        AndroidSessionOwner.installForTest(h.controller)
        val opened = activity
        waitInspection(h)
        try {
            instrumentation.waitForIdleSync()
            var insideScroller = false
            var statusVisible = false
            var statusHeight = 0
            var visibleHeight = 0
            instrumentation.runOnMainSync {
                val field = MainActivity::class.java.getDeclaredField("packageLabel").apply { isAccessible = true }
                val status = field.get(opened) as android.widget.TextView
                var ancestor = status.parent
                while (ancestor is android.view.View) {
                    if (ancestor is android.widget.ScrollView) insideScroller = true
                    ancestor = ancestor.parent
                }
                val root = opened.findViewById<android.view.ViewGroup>(android.R.id.content)
                fun scrollActions(view: android.view.View) {
                    if (view is android.widget.ScrollView) view.fullScroll(android.view.View.FOCUS_DOWN)
                    if (view is android.view.ViewGroup) for (i in 0 until view.childCount) scrollActions(view.getChildAt(i))
                }
                scrollActions(root)
                val visible = android.graphics.Rect()
                statusVisible = status.getGlobalVisibleRect(visible)
                statusHeight = status.height
                visibleHeight = visible.height()
            }
            assertFalse("Status must remain outside scrollable actions", insideScroller)
            assertTrue("Status must remain visible after scrolling actions", statusVisible)
            assertTrue("Status must be laid out", statusHeight > 0)
            assertEquals(statusHeight, visibleHeight)
        } finally { h.scope.cancel() }
    }

    fun testActiveRotationAndServiceRebindDoNotDuplicateFakeUpload() {
        val h = Harness()
        AndroidSessionOwner.installForTest(h.controller)
        val opened = activity
        waitInspection(h)
        try {
            grantForegroundPrerequisites()
            opened.startForegroundService(Intent(opened, UpdateService::class.java).setAction(UpdateService.START))
            runBlocking { withTimeout(10000) { h.entered.await() } }
            instrumentation.runOnMainSync { opened.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE }
            instrumentation.waitForIdleSync()
            assertSame(h.controller, AndroidSessionOwner.get(instrumentation.targetContext))
            assertFalse(h.controller.start(false))
            assertEquals(1, h.uploads.get())
            h.release.complete(Unit)
            waitIdle(h.controller)
            assertEquals(1, h.resets.get())
        } finally {
            h.release.complete(Unit)
            h.controller.stop()
            waitIdle(h.controller)
            h.scope.cancel()
        }
    }

    fun testReopenedSeededSessionHasNoFakeOperationsUntilExplicitResume() {
        val h = Harness()
        h.checkpoint = Checkpoint(bundleDigest = h.pkg.bundleDigest, bleAddress = h.pkg.manifest.device.bleAddress, phase = Phase.UPLOAD_MAIN)
        AndroidSessionOwner.installForTest(h.controller)
        activity
        waitInspection(h)
        instrumentation.waitForIdleSync()
        assertEquals(0, h.connects.get())
        h.controller.start(false)
        waitIdle(h.controller)
        assertEquals(0, h.connects.get())
        val offer = runBlocking { h.controller.prepareResume() }
        h.controller.start(true, offer.id)
        h.release.complete(Unit)
        waitIdle(h.controller)
        assertEquals(1, h.uploads.get())
        h.scope.cancel()
    }

    fun testStaleDialogPositiveClickIsRejectedByRealServiceIntentHandler() {
        val h = Harness()
        h.primary = RemoteImage(h.pkg.manifest.main.signedRegionSha256, false, true)
        h.checkpoint = Checkpoint(bundleDigest = h.pkg.bundleDigest, bleAddress = h.pkg.manifest.device.bleAddress, phase = Phase.FINAL_RESET_INTENT)
        AndroidSessionOwner.installForTest(h.controller)
        val opened = activity
        waitInspection(h)
        // Needed only for Android's connectedDevice foreground prerequisite. The injected transport uses no radio.
        grantForegroundPrerequisites()
        val offer = runBlocking { h.controller.prepareResume() }
        lateinit var dialog: android.app.AlertDialog
        instrumentation.runOnMainSync {
            dialog = opened.showResetRetryConfirmation {
                opened.startForegroundService(Intent(opened, UpdateService::class.java).apply {
                    action = UpdateService.RESUME
                    putExtra(UpdateService.OFFER, offer.id)
                    putExtra(UpdateService.CONFIRMED, true)
                })
            }
        }
        var reviewedText = ""
        instrumentation.runOnMainSync {
            reviewedText=dialog.findViewById<android.widget.TextView>(android.R.id.message).text.toString()
        }
        assertTrue("Reset confirmation must identify the reviewed device",reviewedText.contains(h.pkg.manifest.device.name))
        assertTrue(reviewedText.contains(h.pkg.manifest.main.version))
        capture("reset-confirmation")
        h.controller.importDocument("new-selection")
        waitIdle(h.controller)
        instrumentation.runOnMainSync { dialog.getButton(android.app.AlertDialog.BUTTON_POSITIVE).performClick() }
        instrumentation.waitForIdleSync()
        waitIdle(h.controller)
        assertEquals(0, h.connects.get())
        assertEquals(0, h.resets.get())
        h.scope.cancel()
    }
    fun testSlowImportRemainsOwnedAcrossServiceReplacementAndStop() {
        val h = Harness()
        h.slowImport = true
        AndroidSessionOwner.installForTest(h.controller)
        val opened = activity
        waitInspection(h)
        opened.startService(Intent(opened, UpdateService::class.java).apply {
            action = UpdateService.IMPORT
            putExtra(UpdateService.SOURCE, "slow-provider")
        })
        runBlocking { withTimeout(10000) { h.importEntered.await() } }
        instrumentation.runOnMainSync { opened.finish() }
        instrumentation.waitForIdleSync()
        opened.stopService(Intent(opened, UpdateService::class.java))
        instrumentation.waitForIdleSync()
        opened.startService(Intent(opened, UpdateService::class.java).apply {
            action = UpdateService.IMPORT
            putExtra(UpdateService.SOURCE, "replacement-provider")
        })
        instrumentation.waitForIdleSync()
        assertSame(h.controller, AndroidSessionOwner.get(opened))
        assertTrue(h.controller.busy.value)
        h.controller.stop()
        assertFalse(h.controller.start(false))
        h.importRelease.complete(Unit)
        waitIdle(h.controller)
        assertEquals(0, h.selections.get())
        assertEquals(0, h.connects.get())
        h.scope.cancel()
    }
    private fun pendingExport(opened: MainActivity): ByteArray? {
        var bytes: ByteArray? = null
        instrumentation.runOnMainSync {
            bytes = (MainActivity::class.java.getDeclaredField("pendingExport").apply { isAccessible = true }.get(opened) as? ByteArray)?.copyOf()
        }
        return bytes
    }

    /** Deliver a real callback, then drain only the child coroutine it starts.
     * The service observers are intentionally left running. No picker is launched. */
    private fun deliverExportResult(opened: MainActivity, resultCode: Int, data: Intent?) {
        val launched = mutableListOf<Job>()
        instrumentation.runOnMainSync {
            val activityScope = MainActivity::class.java.getDeclaredField("scope").apply { isAccessible = true }.get(opened) as CoroutineScope
            val parent = requireNotNull(activityScope.coroutineContext[Job])
            val before = parent.children.toSet()
            val callback = MainActivity::class.java.getDeclaredMethod("onActivityResult",
                Int::class.javaPrimitiveType, Int::class.javaPrimitiveType, Intent::class.java).apply { isAccessible = true }
            callback.invoke(opened, 2, resultCode, data)
            launched.addAll(parent.children.filter { it !in before }.toList())
        }
        runBlocking { withTimeout(10000) { launched.forEach { it.join() } } }
        instrumentation.waitForIdleSync()
    }

    private fun exportHarness(): Pair<Harness, MainActivity> {
        val h = Harness().also { harnesses.add(it) }
        AndroidSessionOwner.installForTest(h.controller)
        val opened = activity
        waitInspection(h)
        return h to opened
    }

    private fun assertExplicitRecaptureAvailable(h: Harness, opened: MainActivity) {
        assertNull("The completed/cancelled picker must release its snapshot", pendingExport(opened))
        h.reportBytes = "{\"device\":\"explicit-retry\"}".toByteArray()
        runBlocking { opened.captureExportSnapshot() }
        assertTrue(h.reportBytes.contentEquals(requireNotNull(pendingExport(opened))))
        assertEquals(0, h.connects.get() + h.uploads.get() + h.resets.get())
    }

    fun testCancelledExportResultClearsSnapshotAndAllowsExplicitRecapture() {
        val (h, opened) = exportHarness()
        runBlocking { opened.captureExportSnapshot() }
        assertNotNull(pendingExport(opened))
        deliverExportResult(opened, android.app.Activity.RESULT_CANCELED, null)
        assertExplicitRecaptureAvailable(h, opened)
        assertEquals(2, h.reportReads.get())
    }

    fun testExportResultWithoutUriClearsSnapshotAndAllowsExplicitRecapture() {
        val (h, opened) = exportHarness()
        runBlocking { opened.captureExportSnapshot() }
        assertNotNull(pendingExport(opened))
        deliverExportResult(opened, android.app.Activity.RESULT_OK, Intent())
        assertExplicitRecaptureAvailable(h, opened)
        assertEquals(2, h.reportReads.get())
    }

    fun testUnavailableOutputProviderClearsSnapshotAndAllowsExplicitRecapture() {
        val (h, opened) = exportHarness()
        runBlocking { opened.captureExportSnapshot() }
        // A deliberately unregistered content authority makes the real Android
        // resolver fail without an external provider, picker or production file.
        val unavailable = android.net.Uri.parse("content://org.openvimar.instrumentation.unavailable-provider/export")
        deliverExportResult(opened, android.app.Activity.RESULT_OK, Intent().setData(unavailable))
        assertEquals("Failure must not fall back to another controller report", 1, h.reportReads.get())
        assertExplicitRecaptureAvailable(h, opened)
        assertEquals(2, h.reportReads.get())
    }

    fun testStaleExportSuccessWithoutSnapshotNeverReadsOrWritesNewerReport() {
        val (h, opened) = exportHarness()
        val sentinel = "synthetic destination must remain unchanged".toByteArray()
        val destination = java.io.File(instrumentation.targetContext.cacheDir, "stale-export-${System.nanoTime()}.json")
        try {
            destination.writeBytes(sentinel)
            h.reportBytes = "{\"device\":\"newer-unreviewed-report\"}".toByteArray()
            assertNull(pendingExport(opened))
            deliverExportResult(opened, android.app.Activity.RESULT_OK, Intent().setData(android.net.Uri.fromFile(destination)))
            assertEquals("A stale successful picker cannot select the current report", 0, h.reportReads.get())
            assertTrue("A stale picker cannot write its destination", sentinel.contentEquals(destination.readBytes()))
            assertNull(pendingExport(opened))
            assertEquals(0, h.connects.get() + h.uploads.get() + h.resets.get())
        } finally { destination.delete() }
    }

    fun testExportResultAfterRecreationWhileUnboundWritesOriginalSessionSnapshot() {
        val h = Harness()
        AndroidSessionOwner.installForTest(h.controller)
        val opened = activity
        waitInspection(h)
        val expected = h.reportBytes.copyOf()
        runBlocking { opened.captureExportSnapshot() }
        // A later selected-session report must not change the report promised to this picker.
        h.reportBytes = "{\"device\":\"second\"}".toByteArray()
        val replacement = java.util.concurrent.atomic.AtomicReference<MainActivity>()
        val created = java.util.concurrent.CountDownLatch(1)
        val application = opened.application
        val callbacks = object : android.app.Application.ActivityLifecycleCallbacks {
            override fun onActivityCreated(activity: android.app.Activity, state: android.os.Bundle?) {
                if (activity is MainActivity && activity !== opened) {
                    replacement.set(activity)
                    created.countDown()
                }
            }
            override fun onActivityStarted(activity: android.app.Activity) { }
            override fun onActivityResumed(activity: android.app.Activity) { }
            override fun onActivityPaused(activity: android.app.Activity) { }
            override fun onActivityStopped(activity: android.app.Activity) { }
            override fun onActivitySaveInstanceState(activity: android.app.Activity, state: android.os.Bundle) { }
            override fun onActivityDestroyed(activity: android.app.Activity) { }
        }
        val destination = java.io.File(instrumentation.targetContext.cacheDir, "unbound-export-${System.nanoTime()}.json")
        application.registerActivityLifecycleCallbacks(callbacks)
        try {
            instrumentation.runOnMainSync { opened.recreate() }
            assertTrue(created.await(10, java.util.concurrent.TimeUnit.SECONDS))
            instrumentation.waitForIdleSync()
            val restored = replacement.get()
            instrumentation.runOnMainSync {
                instrumentation.callActivityOnStop(restored)
                val binderField = MainActivity::class.java.getDeclaredField("service").apply { isAccessible = true }
                assertNull(binderField.get(restored))
                val resultCallback = MainActivity::class.java.getDeclaredMethod("onActivityResult",
                    Int::class.javaPrimitiveType, Int::class.javaPrimitiveType, Intent::class.java).apply { isAccessible = true }
                resultCallback.invoke(restored, 2, android.app.Activity.RESULT_OK,
                    Intent().setData(android.net.Uri.fromFile(destination)))
            }
            runBlocking { withTimeout(10000) { while (!destination.exists() || destination.length() == 0L) delay(10) } }
            assertTrue(expected.contentEquals(destination.readBytes()))
            assertEquals(0, h.connects.get())
            assertEquals(0, h.resets.get())
        } finally {
            application.unregisterActivityLifecycleCallbacks(callbacks)
            replacement.get()?.let { restored -> instrumentation.runOnMainSync { restored.finish() } }
            destination.delete()
            h.scope.cancel()
        }
    }
}
