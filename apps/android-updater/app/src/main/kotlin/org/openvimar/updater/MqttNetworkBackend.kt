package org.openvimar.updater

import java.io.Closeable
import kotlinx.coroutines.flow.Flow

internal data class MqttMessageEnvelope(val topic:String,val payload:ByteArray,val retained:Boolean=false)
internal sealed interface MqttSignal {
    data class Message(val value:MqttMessageEnvelope):MqttSignal
    data class Lost(val description:String="Broker connection lost"):MqttSignal
}
/** Single-session transport. No automatic reconnect or queued mutation replay. */
internal interface MqttConnection:Closeable {
    val events:Flow<MqttSignal>
    val connected:Boolean
    suspend fun connect(profile:BrokerProfile,credentials:BrokerCredentials?)
    suspend fun subscribe(filters:List<String>)
    suspend fun publish(topic:String,payload:ByteArray)
    suspend fun disconnect()
}
internal class NetworkLostException:java.io.IOException("Broker connection lost; operation outcome may be unknown")
internal data class NetworkBackendState(val connected:Boolean=false,val status:String="Not connected",val devices:List<DeviceRecord> = emptyList(),val inventoryReceived:Boolean=false,val connectionError:Boolean=false)
internal data class OtaAvailability(val available:Boolean,val source:String?,val fileVersion:Long?=null)
internal data class BluetoothPreparation(val submitted:Boolean,val message:String)
