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
import android.widget.CheckBox
import android.widget.EditText
import android.widget.ScrollView
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
    private lateinit var content:LinearLayout
    private var transportFactory:(()->Transport)?=null
    private lateinit var owner:AndroidNetworkOwner
    private val transports=java.util.concurrent.CopyOnWriteArrayList<Transport>()
    private val profile=BrokerProfile("ui-auto","ssl://broker.invalid",listOf(ZigbeeNetwork("ui-topic","Home","alpha")))
    private class Transport(private val fail:Boolean,private val failure:Exception?=null,
        private val gate:CompletableDeferred<Unit>?=null):MqttConnection {
        val subscriptions=java.util.concurrent.CopyOnWriteArrayList<List<String>>()
        val publications=java.util.concurrent.CopyOnWriteArrayList<String>()
        var connectedProfile:String?=null
        var connectedServer:String?=null
        var credentialsPresent=false
        val incoming=Channel<MqttSignal>(Channel.UNLIMITED)
        override val events=incoming.receiveAsFlow()
        override var connected=false
        override suspend fun connect(profile:BrokerProfile,credentials:BrokerCredentials?) {
            connectedProfile=profile.id;connectedServer=profile.serverUri
            credentialsPresent=credentials!=null
            gate?.await()
            failure?.let {throw it}
            if(fail)throw ConnectException("synthetic offline broker")
            connected=true
        }
        override suspend fun subscribe(filters:List<String>) {subscriptions+=filters.toList()}
        override suspend fun publish(topic:String,payload:ByteArray) {publications+=topic;error("GUI restoration must not publish commands")}
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
    private fun show(activated:Boolean,saved:List<BrokerProfile> = listOf(profile)) {
        val store=BrokerProfileStore(ctx);saved.forEach {store.save(it)}
        if(activated)store.activate(profile.id)
        owner=AndroidNetworkOwner(ctx,networkScope,{(transportFactory?.invoke()?:Transport(transports.isNotEmpty())).also {transports+=it}})
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
            val status=TextView(activity);content=LinearLayout(activity).apply {orientation=LinearLayout.VERTICAL}
            val dock=LinearLayout(activity).apply {orientation=LinearLayout.VERTICAL}
            val scrolling=ScrollView(activity).apply {isFillViewport=true;addView(content)}
            root.addView(status);root.addView(scrolling,LinearLayout.LayoutParams(-1,0,1f));root.addView(dock)
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
            control.requestRectangleOnScreen(Rect(0,0,control.width,control.height),true)
        }
        instrumentation.waitForIdleSync()
        // Scrolling and keyboard transitions can outlive the first idle frame.
        awaitCondition("Connection control must be focused and visible: $text") {
            var ready=false
            instrumentation.runOnMainSync {
                val control=nodes().filterIsInstance<TextView>().firstOrNull {it.text.toString()==text&&it.isShown&&it.isEnabled}
                ready=root.hasWindowFocus()&&control?.isAttachedToWindow==true&&control.getGlobalVisibleRect(bounds)
            }
            ready
        }
        val started=SystemClock.uptimeMillis()
        for(action in listOf(MotionEvent.ACTION_DOWN,MotionEvent.ACTION_UP)) {
            val event=MotionEvent.obtain(started,SystemClock.uptimeMillis(),action,bounds.exactCenterX(),bounds.exactCenterY(),0)
            try {instrumentation.sendPointerSync(event)}finally {event.recycle()}
        }
        instrumentation.waitForIdleSync()
    }
    private fun awaitCondition(message:String,condition:()->Boolean) {
        val end=System.currentTimeMillis()+15000
        while(System.currentTimeMillis()<end) {
            instrumentation.waitForIdleSync()
            if(condition())return
            Thread.sleep(50)
        }
        assertTrue(message,condition())
    }
    private fun present(action:SavedConnectionsUi.()->Unit) {
        instrumentation.runOnMainSync {screen!!.action()};instrumentation.waitForIdleSync()
    }
    private fun fill(label:String,value:String) {
        instrumentation.runOnMainSync {
            nodes().filterIsInstance<EditText>().single {it.hint.toString()==label}.setText(value)
        }
        instrumentation.waitForIdleSync()
    }
    private fun row(prefix:String) {
        val end=System.currentTimeMillis()+15000
        var observed=emptyList<String>()
        while(System.currentTimeMillis()<end) {
            instrumentation.waitForIdleSync()
            var clicked=false
            // StateFlow rendering can replace the row. Resolve and use its
            // attached View in one main-thread action after the window is ready.
            instrumentation.runOnMainSync {
                observed=nodes().mapNotNull {it.contentDescription?.toString()}
                val control=nodes().firstOrNull {it.contentDescription?.toString()?.startsWith(prefix)==true}
                if(root.hasWindowFocus()&&control?.isAttachedToWindow==true&&control.isEnabled)
                    clicked=control.performClick()
            }
            if(clicked){instrumentation.waitForIdleSync();return}
            Thread.sleep(50)
        }
        fail("Missing ready connection row $prefix; observed descriptions: $observed")
    }
    private fun dialogAction(title:String,label:String) {
        fun walk(node:android.view.accessibility.AccessibilityNodeInfo):List<android.view.accessibility.AccessibilityNodeInfo> =
            listOf(node)+(0 until node.childCount).flatMap {node.getChild(it)?.let(::walk).orEmpty()}
        val end=System.currentTimeMillis()+10000
        while(System.currentTimeMillis()<end) {
            instrumentation.waitForIdleSync()
            val views=instrumentation.uiAutomation.rootInActiveWindow?.let(::walk).orEmpty()
            if(views.any {it.text?.toString()==title}) {
                val button=views.firstOrNull {it.className?.toString()=="android.widget.Button"&&it.text?.toString()?.equals(label,true)==true}
                if(button!=null) {assertTrue(button.performAction(android.view.accessibility.AccessibilityNodeInfo.ACTION_CLICK));instrumentation.waitForIdleSync();return}
            }
            Thread.sleep(50)
        }
        error("Missing confirmation $title / $label")
    }
    private fun addTopic(name:String,base:String) {
        present {add()};fill("Topic name (required)",name);fill("MQTT base topic (required)",base);click("Save topic")
    }
    private fun seedCredentials() {
        BrokerCredentials("synthetic-user","synthetic-password".toCharArray()).use {BrokerSecretStore(ctx).save(profile,it)}
        present {showDetail(profile.id)};awaitView("Change credentials")
    }
    private fun assertCredentials(username:String?,password:String) {
        val saved=requireNotNull(owner.profile(profile.id))
        requireNotNull(BrokerSecretStore(ctx).load(saved)).use {
            assertEquals(username,it.username);assertTrue("Saved password must match the reviewed choice",it.password.contentEquals(password.toCharArray()))
        }
    }
    private fun assertNoCommands() {assertTrue("UI configuration must never publish device commands",transports.all {it.publications.isEmpty()})}
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
    fun testAuthenticationFailureWaitsForExplicitRetryAndPreservesActivation() {
        transportFactory={Transport(false,if(transports.isEmpty())org.eclipse.paho.client.mqttv3.MqttSecurityException(
            org.eclipse.paho.client.mqttv3.MqttException.REASON_CODE_FAILED_AUTHENTICATION.toInt()) else null)}
        show(activated=false);click("Connect");awaitView("Retry connection")
        assertEquals(profile.id,BrokerProfileStore(ctx).activatedId());assertFalse(owner.state.value.connected)
        assertTrue(owner.state.value.connectionError);assertFalse(owner.state.value.reconnecting)
        assertEquals(1,transports.size)
        click("Retry connection");awaitView("Connected");awaitView("Disconnect")
        assertEquals(2,transports.size);assertEquals(profile.id,owner.activeProfileId)
        assertEquals(profile.id,BrokerProfileStore(ctx).activatedId());assertNoCommands()
    }
    fun testCancellingPendingConnectionRevokesActivationWithoutReplayingIt() {
        val gate=CompletableDeferred<Unit>();transportFactory={Transport(false,gate=gate)}
        show(activated=false);click("Connect");awaitView("Cancel connection")
        awaitCondition("The fake connect must actually have started") {transports.isNotEmpty()}
        click("Cancel connection");awaitView("Connect")
        assertNull(owner.activeProfileId);assertNull(BrokerProfileStore(ctx).activatedId())
        assertFalse(owner.state.value.connected);assertTrue(transports.none {it.connected})
        gate.complete(Unit);instrumentation.waitForIdleSync()
        assertNull(owner.activeProfileId);assertEquals(1,transports.size);assertNoCommands()
    }
    fun testSwitchingSavedProfilesRequiresConfirmationAndCancelKeepsTheCurrentSession() {
        transportFactory={Transport(false)}
        val other=BrokerProfile("other-broker","ssl://other.invalid",listOf(ZigbeeNetwork("other-topic","Workshop","workshop")),label="Workshop broker")
        show(activated=false,saved=listOf(profile,other));click("Connect");awaitView("Connected")
        present {showDetail(other.id)};click("Connect")
        dialogAction("Switch to Workshop broker?","Cancel");awaitView("Connect")
        assertEquals(profile.id,owner.activeProfileId);assertEquals(profile.id,BrokerProfileStore(ctx).activatedId())
        assertTrue(transports.single().connected)
        click("Connect");dialogAction("Switch to Workshop broker?","Switch and connect");awaitView("Connected")
        assertEquals(other.id,owner.activeProfileId);assertEquals(other.id,BrokerProfileStore(ctx).activatedId())
        assertEquals(other.id,transports.last().connectedProfile);assertFalse(transports.first().connected)
        assertEquals(setOf(profile.id,other.id),owner.loadProfiles().map {it.id}.toSet());assertNoCommands()
    }
    fun testSavingANewConnectionCommitsNamedTopicsWithoutActivatingIt() {
        show(activated=false);present {openList();render(content);add()}
        fill("Connection name (required)","New workshop");fill("Broker address (required)","ssl://workshop.invalid:8883")
        row("Zigbee topics (");addTopic("Workshop","workshop/zigbee")
        assertEquals(listOf(profile.id),owner.loadProfiles().map {it.id})
        present {back()};click("Save connection");awaitView("Connect")
        val saved=owner.loadProfiles().single {it.label=="New workshop"}
        assertEquals("ssl://workshop.invalid:8883",saved.serverUri)
        assertEquals("Workshop",saved.networks.single().label);assertEquals("workshop/zigbee",saved.networks.single().baseTopic)
        assertNull(BrokerProfileStore(ctx).activatedId());assertTrue(transports.isEmpty());assertNoCommands()
    }
    fun testDraftTopicRemovalLimitAndDiscardNeverChangeTheSavedProfile() {
        show(activated=false);present {editCurrent()};row("Zigbee topics (")
        addTopic("Workshop","workshop");addTopic("Upstairs","upstairs")
        assertFalse(screen!!.canAdd);present {add()}
        assertTrue(nodes().filterIsInstance<TextView>().any {it.text.toString()=="Up to 3 topics per connection."})
        row("Remove topic Workshop");row("Confirm remove topic Workshop")
        assertTrue(screen!!.canAdd);addTopic("Garden","garden");assertFalse(screen!!.canAdd)
        assertEquals(profile,owner.profile(profile.id))
        present {back()};click("Cancel");dialogAction("Discard changes?","Keep editing")
        assertEquals(profile,owner.profile(profile.id));row("Zigbee topics (")
        assertFalse(screen!!.canAdd);present {back()}
        click("Cancel");dialogAction("Discard changes?","Discard");awaitView("Connect")
        assertEquals(profile,owner.profile(profile.id));assertNull(BrokerProfileStore(ctx).activatedId())
        assertTrue(transports.isEmpty());assertNoCommands()
    }
    fun testActiveConnectionAndTopicLabelEditsKeepTheTransportAndBinding() {
        transportFactory={Transport(false)};show(activated=false);click("Connect");awaitView("Connected")
        present {editCurrent()};fill("Connection name (required)","Renamed broker");click("Save connection");awaitView("Connected")
        assertEquals("Renamed broker",owner.profile(profile.id)!!.label);assertEquals(1,transports.size)
        row("Zigbee topics (");row("Home.");fill("Topic name (required)","Renamed home");click("Save topic")
        awaitCondition("The topic label must be saved") {owner.profile(profile.id)!!.networks.single().label=="Renamed home"}
        assertEquals(profile.networks.single().id,owner.profile(profile.id)!!.networks.single().id)
        assertEquals(1,transports.size);assertTrue(transports.single().connected)
        assertEquals(profile.id,BrokerProfileStore(ctx).activatedId());assertNoCommands()
    }
    fun testActiveBaseTopicChangeCanBeCancelledThenRebindsAndReconnects() {
        transportFactory={Transport(false)};show(activated=false);click("Connect");awaitView("Connected")
        row("Zigbee topics (");row("Home.");fill("MQTT base topic (required)","changed/zigbee")
        click("Save and reconnect");dialogAction("Change MQTT base topic?","Keep editing")
        assertEquals(profile,owner.profile(profile.id));assertEquals(1,transports.size)
        click("Save and reconnect");dialogAction("Change MQTT base topic?","Save and reconnect")
        awaitCondition("The rebound topic must be committed") {owner.profile(profile.id)!!.networks.single().baseTopic=="changed/zigbee"}
        awaitCondition("A fresh fake transport must finish subscribing") {transports.size==2&&owner.state.value.connected}
        val topic=owner.profile(profile.id)!!.networks.single()
        assertFalse(topic.id==profile.networks.single().id)
        assertTrue(transports.last().subscriptions.flatten().contains("changed/zigbee/bridge/devices"))
        assertEquals(profile.id,BrokerProfileStore(ctx).activatedId());assertNoCommands()
    }
    fun testUsernameOnlyCredentialSaveKeepsPasswordAndDiscardKeepsTheSavedPair() {
        show(activated=false);seedCredentials();click("Change credentials");click("Change username")
        fill("Username (optional)","replacement-user");click("Save credentials");awaitView("Change credentials")
        assertCredentials("replacement-user","synthetic-password")
        click("Change credentials");fill("New password","discarded-synthetic-password")
        click("Cancel");dialogAction("Discard changes?","Keep editing")
        assertCredentials("replacement-user","synthetic-password")
        assertEquals("discarded-synthetic-password",nodes().filterIsInstance<EditText>().single {it.hint.toString()=="New password"}.text.toString())
        click("Cancel");dialogAction("Discard changes?","Discard");awaitView("Change credentials")
        assertCredentials("replacement-user","synthetic-password")
        assertNull(BrokerProfileStore(ctx).activatedId());assertTrue(transports.isEmpty());assertNoCommands()
    }
    fun testExplicitEmptyPasswordAndAnonymousCredentialsAreDifferentSavedChoices() {
        show(activated=false);seedCredentials();click("Change credentials")
        fill("New password","ignored-when-empty-is-selected");click("Sign-in options");click("Use an empty password")
        assertFalse(nodes().filterIsInstance<EditText>().single {it.hint.toString()=="New password"}.isEnabled)
        click("Save credentials");awaitView("Change credentials");assertCredentials("synthetic-user","")
        click("Change credentials");click("Change username");fill("Username (optional)","")
        click("Save credentials");awaitView("Change credentials");assertCredentials(null,"")
        click("Change credentials");click("Sign-in options");click("Use no credentials")
        assertFalse(nodes().filterIsInstance<CheckBox>().single {it.text.toString()=="Use an empty password"}.isEnabled)
        assertFalse(nodes().filterIsInstance<EditText>().single {it.hint.toString()=="New password"}.isEnabled)
        click("Save credentials");awaitView("Add credentials")
        assertFalse(owner.hasCredentials(profile));assertNull(BrokerSecretStore(ctx).load(profile))
        assertNull(BrokerProfileStore(ctx).activatedId());assertTrue(transports.isEmpty());assertNoCommands()
    }
    fun testActivePasswordReplacementReconnectsWithoutRevealingSavedSecrets() {
        transportFactory={Transport(false)};show(activated=false);seedCredentials();click("Connect");awaitView("Connected")
        click("Change credentials")
        assertTrue(nodes().filterIsInstance<EditText>().all {it.text.isEmpty()})
        fill("New password","replacement-synthetic-password")
        assertFalse(screen!!.saveState().toString().contains("replacement-synthetic-password"))
        click("Save and reconnect");awaitView("Connected");awaitView("Change credentials")
        assertCredentials("synthetic-user","replacement-synthetic-password")
        assertEquals(2,transports.size);assertTrue(transports.last().credentialsPresent)
        assertEquals(profile.id,BrokerProfileStore(ctx).activatedId());assertNoCommands()
    }
    fun testChangingAnActiveEndpointRequiresConfirmationAndDropsOldCredentials() {
        transportFactory={Transport(false)};show(activated=false);seedCredentials();click("Connect");awaitView("Connected")
        present {editCurrent()};fill("Broker address (required)","ssl://replacement.invalid:8883")
        click("Save and reconnect");dialogAction("Credentials for the new broker","Keep editing")
        assertEquals(profile,owner.profile(profile.id));assertCredentials("synthetic-user","synthetic-password")
        assertEquals(profile.id,BrokerProfileStore(ctx).activatedId());assertEquals(1,transports.size)
        click("Save and reconnect");dialogAction("Credentials for the new broker","Save without credentials");awaitView("Connect")
        val rebound=owner.profile(profile.id)!!
        assertEquals("ssl://replacement.invalid:8883",rebound.serverUri)
        assertFalse(rebound.networks.single().id==profile.networks.single().id)
        assertNull(owner.activeProfileId);assertNull(BrokerProfileStore(ctx).activatedId());assertFalse(owner.hasCredentials(rebound))
        assertEquals(1,transports.size)
        click("Connect");awaitView("Connected")
        assertEquals("ssl://replacement.invalid:8883",transports.last().connectedServer)
        assertFalse(transports.last().credentialsPresent);assertNoCommands();capture("reviewed-endpoint-change")
    }
    fun testUnavailableCredentialsRequireAReplacementInsteadOfSilentlyKeepingUnreadableData() {
        show(activated=false);seedCredentials()
        // Corrupt only this synthetic profile's envelope in isolated preferences.
        ctx.getSharedPreferences("mqtt-secrets-v1",0).edit().putString(profile.id,"invalid-synthetic-envelope").commit()
        present {showDetail(profile.id)};awaitView("Saved credentials unavailable");click("Change credentials")
        val save=nodes().filterIsInstance<TextView>().single {it.text.toString()=="Save credentials"}
        assertFalse(save.isEnabled);fill("Username (optional)","recovered-user");assertFalse(save.isEnabled)
        fill("New password","recovered-synthetic-password");click("Save credentials");awaitView("Change credentials")
        assertCredentials("recovered-user","recovered-synthetic-password")
        assertNull(BrokerProfileStore(ctx).activatedId());assertTrue(transports.isEmpty());assertNoCommands()
    }
    fun testOfflineSavedTopicRequiresConfirmationWithoutActivatingAConnection() {
        show(activated=false);awaitView("Connect");row("Zigbee topics (");row("Home.")
        fill("MQTT base topic (required)","offline/new-topic");click("Save topic")
        dialogAction("Change MQTT base topic?","Keep editing");assertEquals(profile,owner.profile(profile.id))
        click("Save topic");dialogAction("Change MQTT base topic?","Save topic")
        awaitCondition("The reviewed offline topic must be saved") {owner.profile(profile.id)!!.networks.single().baseTopic=="offline/new-topic"}
        assertFalse(owner.profile(profile.id)!!.networks.single().id==profile.networks.single().id)
        assertNull(owner.activeProfileId);assertNull(BrokerProfileStore(ctx).activatedId())
        assertTrue(transports.isEmpty());assertNoCommands()
    }
}
