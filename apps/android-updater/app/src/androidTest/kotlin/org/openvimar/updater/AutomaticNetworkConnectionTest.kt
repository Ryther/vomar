package org.openvimar.updater

import android.content.Context
import android.content.ContextWrapper
import android.test.AndroidTestCase
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.receiveAsFlow

/** Real owner/store/bridge with synthetic transport: never accesses a broker or radio. */
class AutomaticNetworkConnectionTest:AndroidTestCase() {
    fun testAutomaticSubscriptionTimeoutIsRetryableAndExplicitDisconnectStillClearsActivation()=runBlocking {
        val ctx=isolated();val prefs=ctx.getSharedPreferences("mqtt-secrets-v1",0)
        prefs.edit().clear().commit();ctx.getSharedPreferences("mqtt-profile-v1",0).edit().clear().commit()
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
        val profile=BrokerProfile("timeout","ssl://broker.invalid",listOf(ZigbeeNetwork("a","Home","alpha")))
        try {withTimeout(5000) {
            BrokerProfileStore(ctx).apply {save(profile);activate(profile.id)}
            val owner=AndroidNetworkOwner(ctx,scope,{
                object:MqttConnection {
                    override val events=kotlinx.coroutines.flow.emptyFlow<MqttSignal>()
                    override val connected=true
                    override suspend fun connect(profile:BrokerProfile,credentials:BrokerCredentials?) {}
                    override suspend fun subscribe(filters:List<String>) {awaitCancellation()}
                    override suspend fun publish(topic:String,payload:ByteArray) {error("No command")}
                    override suspend fun disconnect() {}
                    override fun close() {}
                }
            },connectTimeoutMs=50)
            owner.state.first {it.reconnecting && it.connectionError}
            assertFalse(owner.state.value.connected)
            assertEquals(profile.id,BrokerProfileStore(ctx).activatedId())
            owner.disconnect()
            assertNull(BrokerProfileStore(ctx).activatedId())
        }} finally {scope.cancel();prefs.edit().clear().commit()}
    }

    fun testMetadataEditDoesNotRestartRejectedAuthentication()=runBlocking {
        val ctx=isolated();val prefs=ctx.getSharedPreferences("mqtt-secrets-v1",0)
        prefs.edit().clear().commit();ctx.getSharedPreferences("mqtt-profile-v1",0).edit().clear().commit()
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);var attempts=0
        val profile=BrokerProfile("rejected","ssl://broker.invalid",listOf(ZigbeeNetwork("a","Home","alpha")))
        try {withTimeout(5000) {
            BrokerProfileStore(ctx).apply {save(profile);activate(profile.id)}
            val owner=AndroidNetworkOwner(ctx,scope,{
                object:MqttConnection {
                    override val events=kotlinx.coroutines.flow.emptyFlow<MqttSignal>()
                    override val connected=false
                    override suspend fun connect(profile:BrokerProfile,credentials:BrokerCredentials?) {
                        attempts++;throw org.eclipse.paho.client.mqttv3.MqttException(org.eclipse.paho.client.mqttv3.MqttException.REASON_CODE_FAILED_AUTHENTICATION.toInt())
                    }
                    override suspend fun subscribe(filters:List<String>) {error("No subscription")}
                    override suspend fun publish(topic:String,payload:ByteArray) {error("No command")}
                    override suspend fun disconnect() {}
                    override fun close() {}
                }
            })
            owner.state.first {it.connectionError}
            assertFalse(owner.state.value.reconnecting)
            owner.saveProfile(profile.copy(label="Renamed"))
            delay(1200);assertEquals(1,attempts)
            assertFalse(owner.state.value.reconnecting)
            owner.disconnect()
        }} finally {scope.cancel();prefs.edit().clear().commit()}
    }
    fun testExplicitDisconnectCancelsSuspendedAutomaticConnectionBeforeTakingLifecycleLock()=runBlocking {
        val ctx=isolated();val prefs=ctx.getSharedPreferences("mqtt-secrets-v1",0)
        prefs.edit().clear().commit();ctx.getSharedPreferences("mqtt-profile-v1",0).edit().clear().commit()
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined)
        val entered=CompletableDeferred<Unit>();val cleaned=CompletableDeferred<Unit>()
        val profile=BrokerProfile("suspended","ssl://broker.invalid",listOf(ZigbeeNetwork("a","Home","alpha")))
        try {withTimeout(5000) {
            BrokerProfileStore(ctx).apply {save(profile);activate(profile.id)}
            val owner=AndroidNetworkOwner(ctx,scope,{
                object:MqttConnection {
                    override val events=kotlinx.coroutines.flow.emptyFlow<MqttSignal>()
                    override val connected=false
                    override suspend fun connect(profile:BrokerProfile,credentials:BrokerCredentials?) {entered.complete(Unit);awaitCancellation()}
                    override suspend fun subscribe(filters:List<String>) {error("No subscription")}
                    override suspend fun publish(topic:String,payload:ByteArray) {error("No command")}
                    override suspend fun disconnect(){withContext(NonCancellable){yield();cleaned.complete(Unit)}}
                    override fun close() {}
                }
            })
            entered.await()
            withTimeout(1000) {owner.disconnect()}
            cleaned.await()
            assertNull(owner.activeProfileId);assertNull(BrokerProfileStore(ctx).activatedId())
            assertFalse(owner.state.value.connected);assertFalse(owner.state.value.reconnecting)
        }} finally {scope.cancel();prefs.edit().clear().commit()}
    }
    private fun isolated()=object:ContextWrapper(context) {
        override fun getApplicationContext():Context=this
        override fun getSharedPreferences(name:String,mode:Int)=super.getSharedPreferences("automatic-connection-test-$name",mode)
    }
    private class Transport:MqttConnection {
        val incoming=Channel<MqttSignal>(Channel.UNLIMITED)
        override val events=incoming.receiveAsFlow()
        override var connected=false
        val subscriptions=mutableListOf<String>()
        var publishes=0
        override suspend fun connect(profile:BrokerProfile,credentials:BrokerCredentials?) { connected=true }
        override suspend fun subscribe(filters:List<String>) { subscriptions.addAll(filters) }
        override suspend fun publish(topic:String,payload:ByteArray) { publishes++;error("Restoration must never publish commands") }
        override suspend fun disconnect(){close()}
        override fun close(){connected=false;incoming.close()}
        suspend fun lose(){connected=false;incoming.send(MqttSignal.Lost())}
    }
    fun testActivationRestoresSubscriptionsAndLossReconnectsWithoutPublishingCommands()=runBlocking {
        val ctx=isolated();val prefs=ctx.getSharedPreferences("mqtt-secrets-v1",0)
        prefs.edit().clear().commit();ctx.getSharedPreferences("mqtt-profile-v1",0).edit().clear().commit()
        val scopes=mutableListOf<CoroutineScope>();val transports=mutableListOf<Transport>()
        fun owner():AndroidNetworkOwner {
            val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);scopes+=scope
            return AndroidNetworkOwner(ctx,scope,{Transport().also {transports+=it}})
        }
        val profile=BrokerProfile("automatic","ssl://broker.invalid",listOf(ZigbeeNetwork("a","Ground floor","alpha"),ZigbeeNetwork("b","First floor","beta")))
        try {withTimeout(10000) {
            val first=owner();first.saveProfile(profile)
            assertTrue(transports.isEmpty()) // Saving alone never activates a connection.
            first.connect(profile)
            assertTrue(first.state.value.connected)
            assertEquals(profile.id,BrokerProfileStore(ctx).activatedId())
            // Simulated process loss retains activation, while its transport disappears.
            scopes.last().cancel();transports.last().close()
            val restored=owner()
            restored.state.first { it.connected }
            assertEquals(profile.id,restored.activeProfileId)
            assertEquals(2,transports.size)
            assertTrue(transports.last().subscriptions.containsAll(listOf("alpha/bridge/devices","beta/bridge/devices")))
            transports.last().lose()
            restored.state.first { it.reconnecting }
            assertFalse(restored.state.value.connected)
            restored.state.first { it.connected }
            assertEquals(3,transports.size)
            assertTrue(transports.all { it.publishes==0 })
            restored.disconnect()
            assertNull(BrokerProfileStore(ctx).activatedId())
            scopes.last().cancel()
            val disabled=owner()
            assertNull(disabled.activeProfileId);assertFalse(disabled.state.value.connected)
            assertEquals(3,transports.size)
        }} finally {scopes.forEach {it.cancel()};transports.forEach {it.close()};prefs.edit().clear().commit()}
    }

    fun testDisconnectDuringBackoffAndSwitchToAnotherProfileCancelOldReconnect()=runBlocking {
        val ctx=isolated();val prefs=ctx.getSharedPreferences("mqtt-secrets-v1",0)
        prefs.edit().clear().commit();ctx.getSharedPreferences("mqtt-profile-v1",0).edit().clear().commit()
        val scope=CoroutineScope(SupervisorJob()+Dispatchers.Unconfined);val transports=mutableListOf<Transport>()
        val owner=AndroidNetworkOwner(ctx,scope,{Transport().also {transports+=it}})
        val first=BrokerProfile("first","ssl://broker.invalid",listOf(ZigbeeNetwork("a","Home","alpha")))
        val second=BrokerProfile("second","ssl://other.invalid",listOf(ZigbeeNetwork("b","Other","beta")))
        try {withTimeout(10000) {
            owner.saveProfile(first);owner.saveProfile(second);owner.connect(first)
            transports.last().lose();owner.state.first {it.reconnecting}
            owner.disconnect()
            assertNull(owner.activeProfileId);assertNull(BrokerProfileStore(ctx).activatedId())
            delay(1200);assertEquals(1,transports.size)
            owner.connect(first);transports.last().lose();owner.state.first {it.reconnecting}
            owner.connect(second)
            assertEquals(second.id,owner.activeProfileId)
            assertEquals(second.id,BrokerProfileStore(ctx).activatedId())
            delay(1200);assertEquals(3,transports.size)
            assertTrue(transports.last().subscriptions.all {it.startsWith("beta/")})
            assertTrue(transports.all {it.publishes==0})
            owner.disconnect()
        }} finally {scope.cancel();transports.forEach {it.close()};prefs.edit().clear().commit()}
    }
}
