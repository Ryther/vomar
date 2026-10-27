package org.openvimar.updater

import android.content.Context
import android.content.ContextWrapper
import android.graphics.Bitmap
import android.graphics.Rect
import android.os.SystemClock
import android.test.ActivityInstrumentationTestCase2
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import java.io.File
import java.net.ConnectException
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.flow.receiveAsFlow

/** Production connection controls in a native window, isolated preferences and no real networking. */
@Suppress("DEPRECATION")
class AutomaticConnectionUiTest:ActivityInstrumentationTestCase2<MainActivity>(MainActivity::class.java) {
    private val networkScope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
    private val uiScope=CoroutineScope(SupervisorJob()+Dispatchers.Main)
    private var screen:SavedConnectionsUi?=null
    private lateinit var ctx:Context
    private lateinit var root:LinearLayout
    private lateinit var owner:AndroidNetworkOwner
    private val transports=java.util.concurrent.CopyOnWriteArrayList<Transport>()
    private val profile=BrokerProfile("ui-auto","ssl://broker.invalid",listOf(ZigbeeNetwork("ui-topic","Home","alpha")))
    private class Transport(private val fail:Boolean):MqttConnection {
        val incoming=Channel<MqttSignal>(Channel.UNLIMITED)
        override val events=incoming.receiveAsFlow()
        override var connected=false
        override suspend fun connect(profile:BrokerProfile,credentials:BrokerCredentials?) {
            if(fail)throw ConnectException("synthetic offline broker")
            connected=true
        }
        override suspend fun subscribe(filters:List<String>) {}
        override suspend fun publish(topic:String,payload:ByteArray) { error("GUI restoration must not publish commands") }
        override suspend fun disconnect(){close()}
        override fun close(){connected=false;incoming.close()}
        suspend fun lose(){connected=false;incoming.send(MqttSignal.Lost())}
    }
    override fun setUp() {
        super.setUp();setActivityInitialTouchMode(true);instrumentation.setInTouchMode(true)
        ctx=object:ContextWrapper(activity) {
            override fun getApplicationContext():Context=this
            override fun getSharedPreferences(name:String,mode:Int)=super.getSharedPreferences("auto-ui-test-$name",mode)
        }
        ctx.getSharedPreferences("mqtt-secrets-v1",0).edit().clear().commit()
        ctx.getSharedPreferences("mqtt-profile-v1",0).edit().clear().commit()
    }
    override fun tearDown() {
        instrumentation.runOnMainSync {screen?.close()}
        uiScope.cancel();networkScope.cancel();transports.forEach {it.close()}
        ctx.getSharedPreferences("mqtt-secrets-v1",0).edit().clear().commit()
        super.tearDown()
    }
    private fun show(activated:Boolean) {
        val store=BrokerProfileStore(ctx);store.save(profile)
        if(activated)store.activate(profile.id)
        owner=AndroidNetworkOwner(ctx,networkScope,{Transport(transports.isNotEmpty()).also {transports+=it}})
        instrumentation.runOnMainSync {
            root=LinearLayout(activity).apply {
                orientation=LinearLayout.VERTICAL;setBackgroundColor(activity.getColor(R.color.ui_surface))
            }
            ViewCompat.setOnApplyWindowInsetsListener(root) {view,insets->
                val bars=insets.getInsets(WindowInsetsCompat.Type.systemBars())
                view.setPadding(NativeUi.dp(activity,20)+bars.left,NativeUi.dp(activity,8)+bars.top,
                    NativeUi.dp(activity,20)+bars.right,NativeUi.dp(activity,16)+bars.bottom)
                insets
            }
            val status=TextView(activity);val content=LinearLayout(activity).apply {orientation=LinearLayout.VERTICAL}
            val dock=LinearLayout(activity).apply {orientation=LinearLayout.VERTICAL}
            root.addView(status);root.addView(content,LinearLayout.LayoutParams(-1,0,1f));root.addView(dock)
            screen=SavedConnectionsUi(activity,owner,uiScope,{_,_,_,_->},{},{},
                {view->dock.removeAllViews();view?.let {dock.addView(it)}},{text,_->status.text=text})
            screen!!.showDetail(profile.id);screen!!.render(content);activity.setContentView(root)
            ViewCompat.requestApplyInsets(root)
            uiScope.launch {owner.state.collect {screen!!.updateState()}}
        }
    }
    private fun nodes(view:View=root):List<View> = listOf(view)+if(view is ViewGroup)(0 until view.childCount).flatMap {nodes(view.getChildAt(it))}else emptyList()
    private fun awaitView(text:String) {
        val end=System.currentTimeMillis()+15000
        while(System.currentTimeMillis()<end) {
            var found=false
            instrumentation.runOnMainSync {found=root.hasWindowFocus()&&nodes().filterIsInstance<TextView>().any {it.text.toString()==text&&it.isShown&&it.isEnabled&&it.width>0&&it.height>0}}
            if(found)return
            Thread.sleep(50)
        }
        error("Missing rendered connection control: $text")
    }
    private fun click(text:String) {
        awaitView(text)
        val bounds=Rect()
        instrumentation.runOnMainSync {
            val control=nodes().filterIsInstance<TextView>().first {it.text.toString()==text&&it.isShown&&it.isEnabled}
            check(root.hasWindowFocus()&&control.getGlobalVisibleRect(bounds))
        }
        val started=SystemClock.uptimeMillis()
        for(action in listOf(MotionEvent.ACTION_DOWN,MotionEvent.ACTION_UP)) {
            val event=MotionEvent.obtain(started,SystemClock.uptimeMillis(),action,bounds.exactCenterX(),bounds.exactCenterY(),0)
            try {instrumentation.sendPointerSync(event)}finally {event.recycle()}
        }
    }
    private fun capture(name:String) {
        instrumentation.waitForIdleSync()
        instrumentation.runOnMainSync {check(root.hasWindowFocus()) {"An OS window is obscuring the connection screen"}}
        val image=instrumentation.uiAutomation.takeScreenshot()
        try {File(activity.getExternalFilesDir("network-reconnect-review"),"$name.png").outputStream().use {image.compress(Bitmap.CompressFormat.PNG,100,it)}}finally {image.recycle()}
    }
    fun testActivatedProfileRestoresAndOfflineDisconnectDisablesFutureConnections() {
        show(activated=true)
        awaitView("Connected");awaitView("Disconnect");capture("restored")
        runBlocking {transports.first().lose()}
        awaitView("Reconnecting");awaitView("Disconnect");capture("reconnecting")
        click("Disconnect");awaitView("Connect");capture("disabled")
        assertNull(BrokerProfileStore(ctx).activatedId())
        assertNull(owner.activeProfileId);assertFalse(owner.state.value.connected)
        val count=transports.size;Thread.sleep(1500);assertEquals(count,transports.size)
    }
    fun testMerelySavedProfileStaysDisconnectedUntilConnectIsPressed() {
        show(activated=false)
        awaitView("Connect");assertTrue(transports.isEmpty());assertNull(BrokerProfileStore(ctx).activatedId())
        click("Connect");awaitView("Disconnect");awaitView("Connected")
        assertEquals(profile.id,BrokerProfileStore(ctx).activatedId())
        click("Disconnect");awaitView("Connect");assertNull(BrokerProfileStore(ctx).activatedId())
    }
}
