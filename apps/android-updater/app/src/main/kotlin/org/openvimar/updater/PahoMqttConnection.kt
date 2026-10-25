package org.openvimar.updater

import java.io.IOException
import java.util.UUID
import javax.net.ssl.SSLSocketFactory
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import org.eclipse.paho.client.mqttv3.*
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence

internal class PahoMqttConnection:MqttConnection {
    private val incoming=Channel<MqttSignal>(128)
    override val events=incoming.receiveAsFlow()
    @Volatile private var client:MqttAsyncClient?=null
    override val connected get()=client?.isConnected==true
    internal fun options(profile:BrokerProfile,secret:BrokerCredentials?)=MqttConnectOptions().apply {
        val canonical=profile.validated();mqttVersion=MqttConnectOptions.MQTT_VERSION_3_1_1
        isCleanSession=true;isAutomaticReconnect=false;connectionTimeout=15;keepAliveInterval=30
        isHttpsHostnameVerificationEnabled=true
        if(canonical.serverUri.startsWith("ssl:") || canonical.serverUri.startsWith("wss:"))socketFactory=SSLSocketFactory.getDefault()
        secret?.username?.let { userName=it };secret?.let { password=it.password }
    }
    override suspend fun connect(profile:BrokerProfile,credentials:BrokerCredentials?) {
        val canonical=profile.validated();check(client==null) { "MQTT sessions cannot reconnect implicitly" }
        val mqtt=MqttAsyncClient(canonical.serverUri,"openvimar-"+UUID.randomUUID(),MemoryPersistence());client=mqtt
        mqtt.setCallback(object:MqttCallback {
            override fun connectionLost(cause:Throwable?) { incoming.trySend(MqttSignal.Lost()) }
            override fun deliveryComplete(token:IMqttDeliveryToken?) {}
            override fun messageArrived(topic:String?,message:MqttMessage?) {
                if(topic==null || message==null)return
                if(message.payload.size>1024*1024 || !incoming.trySend(MqttSignal.Message(MqttMessageEnvelope(topic,message.payload.copyOf(),message.isRetained))).isSuccess) {
                    incoming.close(IOException("MQTT receive bound exceeded"));mqtt.disconnectForcibly(0,0,false)
                }
            }
        })
        val config=options(canonical,credentials)
        try { action { mqtt.connect(config,null,it) } }
        catch(e:Exception) { withContext(NonCancellable+Dispatchers.IO) { close() };throw e }
        finally { config.password?.fill('\u0000') }
    }
    override suspend fun subscribe(filters:List<String>) {
        require(filters.isNotEmpty() && filters.size<=64);val mqtt=requireNotNull(client);check(mqtt.isConnected)
        action { mqtt.subscribe(filters.toTypedArray(),IntArray(filters.size){1},null,it) }
    }
    override suspend fun publish(topic:String,payload:ByteArray) {
        require(topic.length in 1..1024 && topic.none { it=='+' || it=='#' || it=='\u0000' } && payload.size<=16384)
        val mqtt=requireNotNull(client);check(mqtt.isConnected) { "Broker is not connected; request not queued" }
        // No offline buffer, automatic reconnect or retained command. QoS1 ack is delivery only.
        action { mqtt.publish(topic,MqttMessage(payload.copyOf()).apply { qos=1;isRetained=false },null,it) }
    }
    private suspend fun action(start:(IMqttActionListener)->Unit) = suspendCancellableCoroutine<Unit> { continuation ->
        val listener=object:IMqttActionListener {
            override fun onSuccess(token:IMqttToken?) { if(continuation.isActive)continuation.resume(Unit) }
            override fun onFailure(token:IMqttToken?,error:Throwable?) { if(continuation.isActive)continuation.resumeWithException(IOException("MQTT operation failed",error)) }
        }
        try { start(listener) } catch(e:Exception) { if(continuation.isActive)continuation.resumeWithException(e) }
        // Paho may have delivered before cancellation: callers retain an uncertain checkpoint.
    }
    override suspend fun disconnect()=withContext(Dispatchers.IO) { close() }
    override fun close() {
        val mqtt=client;client=null
        if(mqtt!=null)try { mqtt.disconnectForcibly(0,0,false) } finally { mqtt.close(true) }
        incoming.close()
    }
}
