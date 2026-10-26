package org.openvimar.updater

import android.test.ActivityInstrumentationTestCase2
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ScrollView

/** Missing backup is read-only. No USB, radio, original bytes or grant injected. */
@Suppress("DEPRECATION")
class OriginalRestoreUiTest:ActivityInstrumentationTestCase2<OriginalRestoreActivity>(OriginalRestoreActivity::class.java){
    private fun nodes(view:View):List<View> = listOf(view)+if(view is ViewGroup)(0 until view.childCount).flatMap{nodes(view.getChildAt(it))}else emptyList()
    fun testOpeningWithoutDeviceBackupCannotRestoreAndKeepsScrollableControls(){
        val screen=activity;instrumentation.waitForIdleSync()
        val views=nodes(screen.window.decorView)
        assertFalse(views.filterIsInstance<Button>().single{it.text=="Restore original firmware"}.isEnabled)
        assertEquals(1,views.filterIsInstance<ScrollView>().size)
        val pm=screen.packageManager
        assertFalse(pm.getActivityInfo(android.content.ComponentName(screen,OriginalRestoreActivity::class.java),0).exported)
        assertFalse(pm.getServiceInfo(android.content.ComponentName(screen,org.openvimar.updater.installer.OriginalRestoreService::class.java),0).exported)
    }
    fun testAnotherDevicesRestoreCannotLookLikeThisDevicesProgressOrEnableStop(){
        val screen=activity;instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync{
            (OriginalRestoreActivity::class.java.getDeclaredField("observing").apply{isAccessible=true}.get(screen) as? kotlinx.coroutines.Job)?.cancel()
            val state=org.openvimar.updater.installer.OriginalRestoreState(busy=true,done=50,total=100,message="Other target write",backupSha256="a".repeat(64))
            OriginalRestoreActivity::class.java.getDeclaredMethod("render",org.openvimar.updater.installer.OriginalRestoreState::class.java).apply{isAccessible=true}.invoke(screen,state)
        }
        instrumentation.waitForIdleSync()
        val views=nodes(screen.window.decorView)
        assertTrue(views.filterIsInstance<android.widget.TextView>().any{it.text.toString().startsWith("Another device is being restored")})
        assertFalse(views.filterIsInstance<Button>().single{it.text=="Stop restoration"}.isShown)
        assertFalse(views.filterIsInstance<android.widget.ProgressBar>().single().isShown)
        assertFalse(views.filterIsInstance<Button>().single{it.text=="Export backup copy"}.isEnabled)
    }

}
