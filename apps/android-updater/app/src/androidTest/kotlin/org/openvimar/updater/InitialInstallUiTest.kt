package org.openvimar.updater

import android.test.ActivityInstrumentationTestCase2
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Button
import android.graphics.Bitmap
import org.openvimar.installer.InstallBinding
import org.openvimar.installer.TargetIdentity
import org.openvimar.installer.ObservedWatchdogProfile
import org.openvimar.updater.installer.InstallCaptureRequest
import org.openvimar.updater.installer.InitialInstallPhase
import org.openvimar.updater.installer.InitialInstallSnapshot
import java.io.File

/** Real idle first-install screen. No probe, document, network or radio is opened. */
@Suppress("DEPRECATION")
class InitialInstallUiTest:ActivityInstrumentationTestCase2<InitialInstallActivity>(InitialInstallActivity::class.java) {
    private fun nodes(v:View):List<View> = listOf(v)+if(v is ViewGroup)(0 until v.childCount).flatMap{nodes(v.getChildAt(it))}else emptyList()
    private fun field(name:String)=InitialInstallActivity::class.java.getDeclaredField(name).apply{isAccessible=true}
    fun testKeyboardScrollFocusDoesNotWashOutTheWholeScreen(){
        setActivityInitialTouchMode(false);instrumentation.setInTouchMode(false)
        val screen=activity;instrumentation.waitForIdleSync()
        val scroll=nodes(screen.window.decorView).filterIsInstance<android.widget.ScrollView>().single()
        val priorTouchMode=screen.window.decorView.isInTouchMode
        val priorDescendants=scroll.descendantFocusability
        try{
            instrumentation.setInTouchMode(false);instrumentation.waitForIdleSync()
            instrumentation.runOnMainSync{scroll.descendantFocusability=ViewGroup.FOCUS_BLOCK_DESCENDANTS;assertTrue("The viewport must retain keyboard focus and scrolling",scroll.requestFocus())}
            instrumentation.waitForIdleSync();Thread.sleep(500)
            assertTrue(scroll.isFocused)
            assertFalse("Only the viewport focus overlay must be disabled",scroll.defaultFocusHighlightEnabled)
            val location=IntArray(2);instrumentation.runOnMainSync{scroll.getLocationOnScreen(location)}
            val inset=scroll.paddingTop
            val x=location[0]+NativeUi.dp(screen,5)
            val y=location[1]+inset+NativeUi.dp(screen,8)
            val bitmap=instrumentation.uiAutomation.takeScreenshot()
            try{
                assertEquals("Focused viewport must preserve the exact surface role",screen.getColor(R.color.ui_surface),bitmap.getPixel(x,y))
                val config=screen.resources.configuration
                val path=File(instrumentation.targetContext.getExternalFilesDir("ui-review-v060"),"initial-install-keyboard-${config.screenWidthDp}x${config.screenHeightDp}-font${(config.fontScale*100).toInt()}.png")
                path.parentFile!!.mkdirs();path.outputStream().use{bitmap.compress(Bitmap.CompressFormat.PNG,100,it)}
            }finally{bitmap.recycle()}
            val action=nodes(screen.window.decorView).filterIsInstance<Button>().first{it.text.toString()=="Choose firmware"}
            instrumentation.runOnMainSync{scroll.descendantFocusability=priorDescendants;assertTrue("Child actions must retain keyboard focus",action.requestFocus())}
            assertTrue("Child action focus highlighting must remain available",action.defaultFocusHighlightEnabled)
            assertTrue(action.hasFocus())
        }finally{instrumentation.runOnMainSync{scroll.descendantFocusability=priorDescendants};instrumentation.setInTouchMode(priorTouchMode)}
    }
    fun testVerifiedHaltedPresentationKeepsItsTransactionIdentityAndLockedSelectors(){
        val screen=activity;instrumentation.waitForIdleSync();Thread.sleep(250)
        val target=TargetIdentity(0x11223344,0x55667788,0x41414430)
        val digest="b".repeat(64)
        val request=InstallCaptureRequest("b8a22943-5f57-4ae0-a4f8-5f7f2d2e2271","synthetic-held-probe",target,digest)
        val binding=InstallBinding(target,"c".repeat(64),digest,"d".repeat(64),"e".repeat(64),"f".repeat(64),"1".repeat(64),"2".repeat(64))
        instrumentation.runOnMainSync{
            // Presentation injection only: neither the idle service nor USB,
            // the transaction engine, or its verified receipt is modified.
            (field("observing").get(screen) as? kotlinx.coroutines.Job)?.cancel()
            field("selectedDevice").set(screen,"unrelated-preview")
            field("selectedDigest").set(screen,"a".repeat(64))
            field("candidate").setBoolean(screen,false)
            field("snapshot").set(screen,InitialInstallSnapshot(InitialInstallPhase.VERIFIED_HALTED,request,binding,
                archiveSha256=binding.archiveSha256,mutationMayHaveStarted=true,commitMayHaveBeenWritten=true,candidate=true,
                watchdog=ObservedWatchdogProfile(1,1,0x50000,1),watchdogHandoff="paused-reset-before-main-v1"))
            InitialInstallActivity::class.java.getDeclaredMethod("render").apply{isAccessible=true}.invoke(screen)
        }
        instrumentation.waitForIdleSync()
        val views=nodes(screen.window.decorView)
        val texts=views.filterIsInstance<TextView>().map{it.text.toString()}
        listOf("Choose firmware","Read connected device").forEach{label->
            val control=views.filterIsInstance<Button>().single{it.text.toString()==label}
            assertFalse("Held transaction must lock $label",control.isEnabled)
        }
        assertTrue(texts.any{it.contains("Device 11223344-55667788")})
        assertTrue(texts.any{it.startsWith("Firmware")&&it.contains(digest.take(12))})
        assertFalse(texts.any{it.contains("unrelated-preview")||it.contains("SHA-256 ${"a".repeat(12)}")})
        assertFalse(views.any{it.tag=="initial.install.confirm"||it.tag=="initial.capture"})
        assertTrue(views.filterIsInstance<Button>().single{it.text.toString()=="Start verified firmware"}.isEnabled)
        assertFalse(texts.contains("Review and install"))
        assertTrue(texts.any{it.contains("One initial restart is expected")&&it.contains("about 10 seconds")})
    }
    fun testRepairPreviewIsAnExplicitSeparateReviewWithoutNewCaptureOrAutomaticProgramming(){
        val screen=activity;instrumentation.waitForIdleSync()
        val target=TargetIdentity(0x11223344,0x55667788,0x41414430)
        val digest="b".repeat(64)
        val request=InstallCaptureRequest("b8a22943-5f57-4ae0-a4f8-5f7f2d2e2271","synthetic-repair-probe",target,digest)
        val binding=InstallBinding(target,"c".repeat(64),digest,"d".repeat(64),"e".repeat(64),"f".repeat(64),"1".repeat(64),"2".repeat(64))
        instrumentation.runOnMainSync{
            (field("observing").get(screen) as? kotlinx.coroutines.Job)?.cancel()
            field("snapshot").set(screen,InitialInstallSnapshot(InitialInstallPhase.AWAITING_RESUME_REVIEW,request,binding,
                archiveSha256=binding.archiveSha256,mutationMayHaveStarted=true,candidate=true,resume=true,
                resumeHeadSha256="3".repeat(64),resumeClassification="Rebuild the previously issued pages, then commit last."))
            InitialInstallActivity::class.java.getDeclaredMethod("render").apply{isAccessible=true}.invoke(screen)
        }
        instrumentation.waitForIdleSync()
        val views=nodes(screen.window.decorView)
        val texts=views.filterIsInstance<TextView>().map{it.text.toString()}
        assertTrue(texts.contains("Repair review ready. Confirm before the complete image check and any needed writes."))
        assertTrue(texts.contains("Rebuild the previously issued pages, then commit last."))
        assertTrue(texts.any{it.contains("UID 11223344-55667788")&&it.contains("Original ${"c".repeat(16)}")})
        assertTrue(texts.any{it.contains("A rebuild resets custom settings")})
        assertTrue(views.filterIsInstance<Button>().single{it.tag=="initial.resume.confirm"}.isEnabled)
        assertFalse(views.any{it.tag=="initial.capture"||it.tag=="initial.install.confirm"})
        listOf("Choose firmware","Read connected device").forEach{label->
            assertFalse(views.filterIsInstance<Button>().single{it.text.toString()==label}.isEnabled)
        }
        // Only presentation is injected: the real service remains idle, with
        // no USB target, approval, transaction or write authority created.
        val service=field("service").get(screen) as? org.openvimar.updater.installer.InitialInstallService
        assertEquals(InitialInstallPhase.IDLE,service?.state?.value?.phase?:InitialInstallPhase.IDLE)
    }
    fun testCandidatePickerRouteSurvivesActivityRecreationWithoutStartingWork(){
        val opened=activity;instrumentation.waitForIdleSync()
        val replacement=java.util.concurrent.atomic.AtomicReference<InitialInstallActivity>()
        val created=java.util.concurrent.CountDownLatch(1)
        val callbacks=object:android.app.Application.ActivityLifecycleCallbacks{
            override fun onActivityCreated(value:android.app.Activity,state:android.os.Bundle?){if(value is InitialInstallActivity&&value!==opened){replacement.set(value);created.countDown()}}
            override fun onActivityStarted(value:android.app.Activity){}
            override fun onActivityResumed(value:android.app.Activity){}
            override fun onActivityPaused(value:android.app.Activity){}
            override fun onActivityStopped(value:android.app.Activity){}
            override fun onActivitySaveInstanceState(value:android.app.Activity,state:android.os.Bundle){}
            override fun onActivityDestroyed(value:android.app.Activity){}
        }
        opened.application.registerActivityLifecycleCallbacks(callbacks)
        try{
            instrumentation.runOnMainSync{opened.recreate()}
            assertTrue("Replacement first-install Activity must be created",created.await(20,java.util.concurrent.TimeUnit.SECONDS))
            instrumentation.waitForIdleSync()
            val restored=checkNotNull(replacement.get())
            assertFalse(nodes(restored.window.decorView).filterIsInstance<TextView>().any{it.text.toString()=="Bench qualification"})
            assertFalse("A pending picker is not a selected or reviewed candidate",field("candidate").getBoolean(restored))
            assertNull(field("rawPackage").get(restored))
            assertFalse(nodes(restored.window.decorView).any{it.tag=="initial.install.confirm"})
            assertTrue(nodes(restored.window.decorView).filterIsInstance<Button>().filter{it.tag=="initial.capture"}.all{!it.isEnabled})
        }finally{
            opened.application.unregisterActivityLifecycleCallbacks(callbacks)
            replacement.get()?.let{restored->instrumentation.runOnMainSync{restored.finish()}}
        }
    }
    fun testOpeningToolsDoesNotAuthorizeCaptureOrFlash(){
        val screen=activity
        instrumentation.waitForIdleSync()
        val views=nodes(screen.window.decorView)
        assertTrue(views.filterIsInstance<TextView>().any{it.text.toString()=="First installation"})
        assertTrue(views.filterIsInstance<TextView>().any{it.text.toString()=="Choose firmware"})
        assertFalse(views.any{it.tag=="initial.install.confirm"})
        assertTrue(views.filterIsInstance<Button>().filter{it.tag=="initial.capture"}.all{!it.isEnabled})
        assertNull(screen.intent.data)
    }
    fun testOwnerBackupProgressStaysVisibleAndUsesMeasuredSnapshot(){
        setActivityInitialTouchMode(true);instrumentation.setInTouchMode(true)
        val screen=activity;instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync{
            (field("observing").get(screen) as? kotlinx.coroutines.Job)?.cancel()
            val target=TargetIdentity(0x11223344,0x55667788,0x41414430)
            val request=InstallCaptureRequest("b8a22943-5f57-4ae0-a4f8-5f7f2d2e2271","synthetic-only",target,"b".repeat(64))
            field("snapshot").set(screen,InitialInstallSnapshot(InitialInstallPhase.CAPTURING,request,progressDone=1048576,progressTotal=2113536,progressLabel="Reading backup 1/2"))
            InitialInstallActivity::class.java.getDeclaredMethod("render").apply{isAccessible=true}.invoke(screen)
        }
        instrumentation.waitForIdleSync()
        val views=nodes(screen.window.decorView);val bar=views.filterIsInstance<android.widget.ProgressBar>().single{it.tag=="initial.progress"}
        assertFalse(bar.isIndeterminate);assertEquals(490,bar.progress)
        val scroll=views.filterIsInstance<android.widget.ScrollView>().single()
        instrumentation.runOnMainSync{scroll.scrollTo(0,10000)};instrumentation.waitForIdleSync()
        assertTrue(bar.isShown);assertFalse(nodes(scroll).contains(bar))
        assertTrue(views.filterIsInstance<TextView>().any{it.text.toString()=="Reading backup 1/2 · 49%"})
        fun captureProgress(name:String){
            val path=File(instrumentation.targetContext.getExternalFilesDir("ui-review-v060"),"$name.png");path.parentFile!!.mkdirs()
            instrumentation.uiAutomation.takeScreenshot().let{bitmap->try{path.outputStream().use{bitmap.compress(Bitmap.CompressFormat.PNG,100,it)}}finally{bitmap.recycle()}}
        }
        captureProgress("owner-backup-progress")
        instrumentation.runOnMainSync{
            val previous=field("snapshot").get(screen) as InitialInstallSnapshot
            field("snapshot").set(screen,previous.copy(phase=InitialInstallPhase.STARTING,progressDone=0x80000,progressTotal=0x100000,progressLabel="Checking firmware"))
            InitialInstallActivity::class.java.getDeclaredMethod("render").apply{isAccessible=true}.invoke(screen)
        }
        instrumentation.waitForIdleSync();assertTrue(bar.isShown);assertEquals(500,bar.progress)
        captureProgress("owner-prestart-progress")
    }
    fun testLightRepairProgressUsesTheSelectedNativeTheme(){
        val prefs=instrumentation.targetContext.getSharedPreferences("fleet-ui",android.content.Context.MODE_PRIVATE)
        val previous=prefs.getString("theme",null)
        try{
            assertTrue(prefs.edit().putString("theme","Light").commit())
            testRepairShowsSeparateStageTotalAndMeasuredEstimate()
            assertEquals(android.content.res.Configuration.UI_MODE_NIGHT_NO,activity.resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK)
        }finally{val edit=prefs.edit();if(previous==null)edit.remove("theme") else edit.putString("theme",previous);assertTrue(edit.commit())}
    }
    fun testRepairShowsSeparateStageTotalAndMeasuredEstimate(){
        setActivityInitialTouchMode(true);instrumentation.setInTouchMode(true)
        val screen=activity;instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync{
            (field("observing").get(screen) as? kotlinx.coroutines.Job)?.cancel()
            field("snapshot").set(screen,InitialInstallSnapshot(InitialInstallPhase.INSTALLING,resume=true,
                progressDone=0x1d000,progressTotal=0x100000,progressLabel="Repairing firmware",
                overallProgressPermille=186,etaMillis=120000,progressMeasuredAtMillis=System.nanoTime()/1_000_000))
            InitialInstallActivity::class.java.getDeclaredMethod("render").apply{isAccessible=true}.invoke(screen)
        }
        instrumentation.waitForIdleSync();val all=nodes(screen.window.decorView)
        val bars=all.filterIsInstance<android.widget.ProgressBar>().filter{it.isShown};assertEquals(2,bars.size)
        assertEquals(110,bars.single{it.tag=="initial.progress"}.progress)
        assertEquals(186,bars.single{it.tag=="initial.overall.progress"}.progress)
        assertTrue(all.filterIsInstance<TextView>().any{it.text.toString()=="Overall repair · 18%"})
        assertTrue(all.filterIsInstance<TextView>().any{it.text.toString()=="About 2 min remaining"})
        val phaseLocation=IntArray(2);val overallLocation=IntArray(2)
        bars.single{it.tag=="initial.progress"}.getLocationOnScreen(phaseLocation)
        bars.single{it.tag=="initial.overall.progress"}.getLocationOnScreen(overallLocation)
        assertTrue("Overall bar must be below current phase",overallLocation[1]>phaseLocation[1])
        val path=File(instrumentation.targetContext.getExternalFilesDir("ui-review-v107"),"repair-overall.png");path.parentFile!!.mkdirs()
        instrumentation.uiAutomation.takeScreenshot().let{bitmap->try{path.outputStream().use{bitmap.compress(Bitmap.CompressFormat.PNG,100,it)}}finally{bitmap.recycle()}}
        instrumentation.runOnMainSync{
            val previous=field("snapshot").get(screen) as InitialInstallSnapshot
            field("snapshot").set(screen,previous.copy(phase=InitialInstallPhase.STARTING,progressDone=0x80000,progressLabel="Checking firmware",overallProgressPermille=500))
            InitialInstallActivity::class.java.getDeclaredMethod("render").apply{isAccessible=true}.invoke(screen)
        }
        instrumentation.waitForIdleSync()
        assertTrue(nodes(screen.window.decorView).filterIsInstance<TextView>().any{it.text.toString()=="Overall verification · 50%"})
    }
    fun testStaleEstimateAndTerminalStatesDoNotShowAFalseCountdown(){
        setActivityInitialTouchMode(true);instrumentation.setInTouchMode(true)
        val screen=activity;instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync{
            (field("observing").get(screen) as? kotlinx.coroutines.Job)?.cancel()
            field("snapshot").set(screen,InitialInstallSnapshot(InitialInstallPhase.INSTALLING,resume=true,
                progressDone=4096,progressTotal=0x100000,progressLabel="Repairing firmware",
                overallProgressPermille=112,etaMillis=120000,progressMeasuredAtMillis=System.nanoTime()/1_000_000-20000))
            InitialInstallActivity::class.java.getDeclaredMethod("render").apply{isAccessible=true}.invoke(screen)
        }
        instrumentation.waitForIdleSync()
        assertTrue(nodes(screen.window.decorView).filterIsInstance<TextView>().any{it.isShown&&it.text.toString()=="Estimating remaining time…"})
        instrumentation.runOnMainSync{
            val previous=field("snapshot").get(screen) as InitialInstallSnapshot
            field("snapshot").set(screen,previous.copy(phase=InitialInstallPhase.FAILED))
            InitialInstallActivity::class.java.getDeclaredMethod("render").apply{isAccessible=true}.invoke(screen)
        }
        instrumentation.waitForIdleSync()
        assertTrue(nodes(screen.window.decorView).filterIsInstance<android.widget.ProgressBar>().none{it.isShown})
    }
    fun testProgressStagesFallbacksEstimateBoundariesAndCompletionAreRenderedFromObservedWork(){
        val screen=activity;instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync{
            (field("observing").get(screen) as? kotlinx.coroutines.Job)?.cancel()
            val now=System.nanoTime()/1_000_000
            val base=InitialInstallSnapshot(InitialInstallPhase.INSTALLING,progressDone=1,progressTotal=4,
                progressLabel="Checking pages",progressMeasuredAtMillis=now)
            fun show(snapshot:InitialInstallSnapshot,stage:Int?,overall:Int?,label:String?,estimate:String?){
                field("snapshot").set(screen,snapshot)
                InitialInstallActivity::class.java.getDeclaredMethod("render").apply{isAccessible=true}.invoke(screen)
                val views=nodes(screen.window.decorView)
                val current=views.filterIsInstance<android.widget.ProgressBar>().single{it.tag=="initial.progress"}
                val total=views.filterIsInstance<android.widget.ProgressBar>().single{it.tag=="initial.overall.progress"}
                assertEquals(stage!=null,current.visibility==View.VISIBLE)
                assertEquals(overall!=null,total.visibility==View.VISIBLE)
                stage?.let{assertEquals(it,current.progress);assertEquals("${snapshot.progressLabel} · ${it/10}%",current.contentDescription.toString())}
                overall?.let{assertEquals(it,total.progress);assertEquals("$label · ${it/10}%",total.contentDescription.toString())}
                val remaining=field("remainingText").get(screen) as TextView
                assertEquals(estimate!=null,remaining.visibility==View.VISIBLE)
                estimate?.let{assertEquals(it,remaining.text.toString())}
            }
            show(base,250,250,"Overall installation","Estimating remaining time…")
            show(base.copy(stageDone=3,stageTotal=4,overallProgressPermille=180,etaMillis=59999),750,180,"Overall installation","Less than a minute remaining")
            show(base.copy(phase=InitialInstallPhase.CAPTURING,etaMillis=60000),250,250,"Overall backup","About 1 min remaining")
            show(base.copy(resume=true,etaMillis=3599999),250,250,"Overall repair","About 60 min remaining")
            show(base.copy(phase=InitialInstallPhase.STARTING,etaMillis=3600000),250,250,"Overall verification","About 1 h 0 min remaining")
            show(base.copy(etaMillis=3660000),250,250,"Overall installation","About 1 h 1 min remaining")
            show(base.copy(etaMillis=0),250,250,"Overall installation","Estimating remaining time…")
            show(base.copy(etaMillis=120000,progressMeasuredAtMillis=null),250,250,"Overall installation","Estimating remaining time…")
            show(base.copy(etaMillis=120000,progressMeasuredAtMillis=now+60000),250,250,"Overall installation","Estimating remaining time…")
            show(base.copy(stageDone=9,stageTotal=4,overallProgressPermille=2000),1000,999,"Overall installation","Estimating remaining time…")
            show(base.copy(stageDone=-1,stageTotal=4,overallProgressPermille=-100),0,0,"Overall installation","Estimating remaining time…")
            show(base.copy(phase=InitialInstallPhase.VERIFIED_HALTED),null,1000,"Overall installation",null)
            show(base.copy(phase=InitialInstallPhase.STARTED),null,1000,"Overall verification",null)
            show(base.copy(phase=InitialInstallPhase.AWAITING_REVIEW),null,null,null,null)
            show(base.copy(progressTotal=0),null,null,null,null)
        }
        // Injected presentation cannot create a backend receipt or admission.
        val service=field("service").get(screen) as? org.openvimar.updater.installer.InitialInstallService
        assertEquals(InitialInstallPhase.IDLE,service?.state?.value?.phase?:InitialInstallPhase.IDLE)
    }
    fun testProgressTickerStopsWhenTheScreenIsPaused(){
        val screen=activity;instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync{
            val handler=field("progressHandler").get(screen) as android.os.Handler
            val tick=field("progressTick").get(screen) as Runnable
            instrumentation.callActivityOnPause(screen)
            assertFalse(field("foreground").getBoolean(screen))
            assertFalse(handler.hasCallbacks(tick))
            tick.run()
            assertFalse("A paused screen must not requeue its countdown",handler.hasCallbacks(tick))
            instrumentation.callActivityOnResume(screen)
            assertTrue(field("foreground").getBoolean(screen))
            tick.run()
            assertTrue(handler.hasCallbacks(tick))
        }
    }
    fun testIdleScreenRemainsScrollableWithVisibleSystemInsets(){
        setActivityInitialTouchMode(true);instrumentation.setInTouchMode(true)
        val screen=activity
        instrumentation.waitForIdleSync()
        val deadline=android.os.SystemClock.elapsedRealtime()+10_000
        while(!screen.hasWindowFocus()&&android.os.SystemClock.elapsedRealtime()<deadline)Thread.sleep(100)
        assertTrue("Capture the focused app, not the launcher's closing task snapshot",screen.hasWindowFocus())
        Thread.sleep(1500) // Software compositor may still be closing its task leash.
        val scroll=nodes(screen.window.decorView).filterIsInstance<android.widget.ScrollView>().single()
        val safe=checkNotNull(androidx.core.view.ViewCompat.getRootWindowInsets(scroll)).getInsets(
            androidx.core.view.WindowInsetsCompat.Type.systemBars() or androidx.core.view.WindowInsetsCompat.Type.displayCutout() or androidx.core.view.WindowInsetsCompat.Type.ime())
        // Android may place navigation at the side or hide a tablet taskbar.
        // Preserve the actual insets on all four edges rather than assuming
        // every configuration has a positive bottom navigation bar.
        val root=scroll.parent as View
        assertEquals(safe.left,root.paddingLeft);assertEquals(safe.top,root.paddingTop)
        assertEquals(safe.right,root.paddingRight);assertEquals(safe.bottom,root.paddingBottom)
        val location=IntArray(2);instrumentation.runOnMainSync{scroll.getLocationOnScreen(location)}
        assertTrue(location[0]+scroll.paddingLeft>=safe.left)
        assertTrue(location[0]+scroll.width-scroll.paddingRight<=screen.resources.displayMetrics.widthPixels-safe.right)
        assertTrue(location[1]+scroll.paddingTop>=safe.top)
        assertTrue(location[1]+scroll.height-scroll.paddingBottom<=screen.resources.displayMetrics.heightPixels-safe.bottom)
        val path=File(instrumentation.targetContext.getExternalFilesDir("ui-review-v060"),"initial-install-${screen.resources.configuration.screenWidthDp}x${screen.resources.configuration.screenHeightDp}-font${(screen.resources.configuration.fontScale*100).toInt()}.png")
        path.parentFile!!.mkdirs()
        instrumentation.uiAutomation.takeScreenshot().let{bitmap->try{path.outputStream().use{bitmap.compress(Bitmap.CompressFormat.PNG,100,it)}}finally{bitmap.recycle()}}
    }
}
