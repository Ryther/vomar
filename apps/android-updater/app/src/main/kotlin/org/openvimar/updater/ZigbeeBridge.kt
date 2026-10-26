package org.openvimar.updater

import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*

internal data class ZigbeeLiveDevice(val record:DeviceRecord,val friendlyName:String,val modelId:String?,val disabled:Boolean=false)
internal data class ZigbeeObservation(val networkId:String,val ieee:String,val retained:Boolean,val receivedAt:Long,val payload:JsonObject)
internal class ZigbeeBridge(private val connection:MqttConnection,private val scope:CoroutineScope,
    private val now:()->Long=System::currentTimeMillis,private val requestTimeoutMs:Long=60000,private val proofSampleDelayMs:Long=1100) {
    private val mutable=MutableStateFlow(NetworkBackendState())
    val state:StateFlow<NetworkBackendState> = mutable.asStateFlow()
    private val observed=MutableSharedFlow<ZigbeeObservation>(extraBufferCapacity=128)
    val observations:SharedFlow<ZigbeeObservation> = observed.asSharedFlow()
    private var profile:BrokerProfile?=null
    private var reader:Job?=null
    private val live=ConcurrentHashMap<String,ZigbeeLiveDevice>()
    private val offline=ConcurrentHashMap.newKeySet<String>()
    private val subscribed=ConcurrentHashMap.newKeySet<String>()
    private data class Contract(val sample:Long,val boot:Long,val ready:Boolean,val recovery:String)
    private val contracts=ConcurrentHashMap<String,Contract>()
    private data class Pending(val topic:String,val id:String,val result:CompletableDeferred<JsonObject>)
    private val pending=ConcurrentHashMap<String,Pending>()
    private fun key(network:String,ieee:String)="$network:$ieee"
    private fun network(id:String)=requireNotNull(profile?.networks?.singleOrNull { it.id==id }) { "Unknown Zigbee network" }
    private fun target(network:String,ieee:String):ZigbeeLiveDevice {
        require(connection.connected && state.value.connected) { "Connect to the configured broker first" }
        require(network !in offline) { "Selected Zigbee bridge is offline" }
        require(ieee.matches(Regex("0x[0-9a-f]{16}"))) { "Exact IEEE address required" }
        return requireNotNull(live[key(network,ieee)]) { "Target absent from the current supported bridge inventory" }.also {
            require(!it.disabled && it.record.firmwareKind==FirmwareKind.CUSTOM && it.modelId=="Vimar30805") { "This operation requires a supported custom Vimar firmware and model" }
        }
    }
    suspend fun connect(profile:BrokerProfile,credentials:BrokerCredentials?) {
        require(reader==null) { "Disconnect before changing broker settings" };val canonical=profile.validated();this.profile=canonical
        mutable.value=NetworkBackendState(status="Connecting")
        try {
            connection.connect(canonical,credentials)
            reader=scope.launch(start=CoroutineStart.UNDISPATCHED) {
                try { connection.events.collect { signal -> when(signal) {
                    is MqttSignal.Message -> consume(signal.value)
                    is MqttSignal.Lost -> lost()
                } } } catch(e:CancellationException) { throw e } catch(_:Exception) { lost() }
            }
            val filters=canonical.networks.flatMap { n -> listOf("${n.baseTopic}/bridge/devices","${n.baseTopic}/bridge/state","${n.baseTopic}/bridge/event","${n.baseTopic}/bridge/response/device/ota_update/+") }
            connection.subscribe(filters);subscribed.addAll(filters)
            mutable.update { it.copy(connected=true,status="Connected · waiting for bridge inventory") }
        } catch(e:Exception) { reader?.cancel();reader=null;connection.disconnect();mutable.value=NetworkBackendState(status="Connection failed",connectionError=true);throw e }
    }
    suspend fun refreshInventory() {
        val current=requireNotNull(profile) { "Connect to a broker first" }
        check(state.value.connected) { "Connect to a broker first" }
        connection.subscribe(current.networks.map { "${it.baseTopic}/bridge/devices" })
    }
    private fun lost() {
        mutable.update { it.copy(connected=false,status="Connection lost · reconnect explicitly",connectionError=true) }
        pending.values.forEach { it.result.completeExceptionally(NetworkLostException()) };pending.clear()
    }
    suspend fun disconnect() {
        reader?.cancelAndJoin();reader=null;lost();connection.disconnect();live.clear();offline.clear();contracts.clear();subscribed.clear()
        mutable.value=NetworkBackendState(status="Disconnected")
    }
    internal fun consume(message:MqttMessageEnvelope) {
        val profile=profile ?: return
        val network=profile.networks.singleOrNull { message.topic.startsWith(it.baseTopic+"/") } ?: return
        val relative=message.topic.removePrefix(network.baseTopic+"/")
        if(message.payload.size>1024*1024) { invalidate(network.id,"Bridge payload exceeds bound");return }
        val value=try { Json.parseToJsonElement(message.payload.toString(Charsets.UTF_8)) } catch(_:Exception) {
            if(relative=="bridge/devices")invalidate(network.id,"Invalid bridge inventory");return
        }
        when {
            relative=="bridge/devices" -> {
                val devices=try { parseDevices(network.id,value,now()).map { incoming->incoming.copy(record=ZigbeeDeviceMetadata.preserveVersion(live[key(network.id,incoming.record.ieee!!)]?.record,incoming.record)) } } catch(_:Exception) { invalidate(network.id,"Invalid bridge inventory");return }
                live.keys.filter { it.startsWith(network.id+":") }.forEach(live::remove)
                devices.forEach { live[key(network.id,it.record.ieee!!)]=it }
                val filters=devices.flatMap { d -> listOf("${network.baseTopic}/${d.friendlyName}","${network.baseTopic}/${d.record.ieee}") }.distinct().filter { subscribed.add(it) }
                if(subscribed.size>12012) { lost();return }
                if(filters.isNotEmpty())scope.launch { try { filters.chunked(64).forEach { connection.subscribe(it) } } catch(_:Exception) { lost() } }
                mutable.update { it.copy(devices=live.values.map { d -> d.record }.sortedBy { d -> d.id },status="Connected · ${live.size} supported devices",inventoryReceived=true) }
            }
            relative=="bridge/state" -> {
                val state=when(value) { is JsonObject -> value.string("state");is JsonPrimitive -> value.content;else -> null }
                if(state=="online")offline.remove(network.id)
                if(state=="offline") { offline.add(network.id);mutable.update { it.copy(status="${network.label} bridge offline") };pending.values.filter { it.topic.startsWith(network.baseTopic+"/") }.forEach { it.result.completeExceptionally(NetworkLostException()) } }
            }
            relative.startsWith("bridge/response/device/ota_update/") && !message.retained -> {
                val response=value as? JsonObject ?: return
                val transaction=response.string("transaction") ?: return
                val request=pending[transaction] ?: return
                if(request.topic!=message.topic)return
                val data=response["data"] as? JsonObject
                if(response.string("status")=="error")request.result.completeExceptionally(IllegalStateException("Bridge refused the correlated request"))
                else if(response.string("status")=="ok" && data?.string("id")==request.id)request.result.complete(data)
            }
            relative=="bridge/event" -> {
                val event=value as? JsonObject ?: return
                val data=event["data"] as? JsonObject ?: return
                val ieee=data.string("ieee_address") ?: return
                if(event.string("type") in setOf("device_announce","device_interview") && live.containsKey(key(network.id,ieee)))
                    observed.tryEmit(ZigbeeObservation(network.id,ieee,message.retained,now(),event))
            }
            !relative.startsWith("bridge/") -> {
                val device=live.values.singleOrNull { it.record.networkId==network.id && relative in setOf(it.friendlyName,it.record.ieee) } ?: return
                val data=value as? JsonObject ?: return
                val refreshed=ZigbeeDeviceMetadata.fromState(device,data,now(),message.retained)
                if(refreshed!=device.record){
                    live[key(network.id,device.record.ieee!!)]=device.copy(record=refreshed)
                    mutable.update { it.copy(devices=live.values.map { d->d.record }.sortedBy { d->d.id }) }
                }
                val contract=parseContract(data)
                if(contract!=null)contracts.compute(key(network.id,device.record.ieee!!)) { _,previous ->
                    if(previous==null || contract.boot!=previous.boot || ((contract.sample-previous.sample) and 0xffffffffL) in 1..0x7fffffffL)contract else previous
                }
                // Retained observations are only a sample baseline, never return/proof authority.
                observed.tryEmit(ZigbeeObservation(network.id,device.record.ieee!!,message.retained,now(),data))
            }
        }
    }
    private fun invalidate(network:String,status:String) {
        live.keys.filter { it.startsWith(network+":") }.forEach(live::remove)
        mutable.update { it.copy(status=status,devices=live.values.map { d -> d.record }) }
    }
    fun requireCustomTarget(network:String,ieee:String)=target(network,ieee)
    suspend fun prepareBluetooth(network:String,ieee:String):BluetoothPreparation {
        val target=target(network,ieee)
        require("enter_recovery" in target.record.capabilities) { "Firmware does not expose selected-unit Bluetooth preparation" }
        connection.publish("${network(network).baseTopic}/$ieee/set","{\"enter_recovery\":true}".toByteArray())
        return BluetoothPreparation(true,"Bluetooth request sent to selected unit · discover and verify it nearby")
    }
    suspend fun check(network:String,ieee:String,source:String?=null):OtaAvailability {
        val device=target(network,ieee)
        require("zigbee_ota" in device.record.capabilities) { "Firmware does not expose OTA support" }
        source?.let(::requireHttpsSource)
        val data=request(network,ieee,"check",source,requestTimeoutMs)
        val available=(data["update_available"] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull
            ?: throw IllegalArgumentException("Invalid correlated OTA availability")
        return OtaAvailability(available,data.string("source"))
    }
    /** Read-only aggregate getter. Cached merged MQTT state cannot pass without a
     * new device sample token. With no baseline we read twice across a RAM tick. */
    suspend fun verifyRecoveryPair(network:String,ieee:String,expectedRecovery:String)=coroutineScope {
        require(expectedRecovery.matches(Regex("[0-9a-f]{64}")))
        target(network,ieee)
        var baseline=contracts[key(network,ieee)]
        repeat(3) {
            val fresh=CompletableDeferred<Contract>()
            val watcher=launch(start=CoroutineStart.UNDISPATCHED) {
                observations.collect { observation ->
                    if(observation.networkId==network && observation.ieee==ieee && !observation.retained)
                        parseContract(observation.payload)?.let { fresh.complete(it) }
                }
            }
            val next=try {
                connection.publish("${network(network).baseTopic}/$ieee/get","{\"ota_contract\":\"\"}".toByteArray())
                withTimeoutOrNull(requestTimeoutMs) { fresh.await() } ?: error("Fresh recovery compatibility is unavailable · Bluetooth migration may be required")
            } finally { watcher.cancelAndJoin() }
            val previous=baseline
            if(previous!=null && (next.boot!=previous.boot || ((next.sample-previous.sample) and 0xffffffffL) in 1..0x7fffffffL)) {
                val device=target(network,ieee);val caps=device.record.capabilities.filterNot { it=="zigbee_ota_profile2" || it.startsWith("recovery_sha256:") }.toMutableSet()
                if(next.ready && next.recovery==expectedRecovery) { caps.add("zigbee_ota_profile2");caps.add("recovery_sha256:"+next.recovery) }
                live[key(network,ieee)]=device.copy(record=device.record.copy(capabilities=caps))
                mutable.update { it.copy(devices=live.values.map { d -> d.record }.sortedBy { d -> d.id }) }
                require(next.ready && next.recovery==expectedRecovery) { "Recovery pair is incompatible · Bluetooth migration is required" }
                return@coroutineScope
            }
            if(previous==null)baseline=next
            delay(proofSampleDelayMs)
        }
        error("No advancing recovery contract sample · check the device or use Bluetooth migration")
    }
    /** Explicit read-only reconciliation: a new OTA CHECK, never UPDATE/SET.
     * The matching live state must arrive during this correlated request.
     */
    suspend fun inspectOtaState(network:String,ieee:String):ZigbeeObservation=coroutineScope {
        val fresh=CompletableDeferred<ZigbeeObservation>()
        val watcher=launch(start=CoroutineStart.UNDISPATCHED) {
            observations.collect { observation ->
                if(observation.networkId==network && observation.ieee==ieee && !observation.retained && observation.payload["update"] is JsonObject)
                    fresh.complete(observation)
            }
        }
        try { check(network,ieee);withTimeout(minOf(requestTimeoutMs,5000)) { fresh.await() } }
        finally { watcher.cancelAndJoin() }
    }
    suspend fun update(network:String,ieee:String,source:String,timeoutMs:Long):JsonObject {
        val device=target(network,ieee);require("zigbee_ota" in device.record.capabilities)
        requireHttpsSource(source)
        return request(network,ieee,"update",source,timeoutMs)
    }
    private suspend fun request(network:String,ieee:String,operation:String,source:String?,timeoutMs:Long):JsonObject {
        val base=network(network).baseTopic;target(network,ieee)
        val tx="vimar-"+UUID.randomUUID();val deferred=CompletableDeferred<JsonObject>()
        pending[tx]=Pending("$base/bridge/response/device/ota_update/$operation",ieee,deferred)
        try {
            val body=buildJsonObject { put("id",ieee);put("transaction",tx);source?.let { put("url",it) } }
            connection.publish("$base/bridge/request/device/ota_update/$operation",body.toString().toByteArray())
            return withTimeout(timeoutMs) { deferred.await() }
        } finally { pending.remove(tx);deferred.cancel() }
    }
    companion object {
        private fun parseContract(data:JsonObject):Contract? {
            val encoded=data.string("ota_contract") ?: return null
            if(encoded.length!=61 || !encoded.startsWith("v1:") || !encoded.substring(3).matches(Regex("[A-Za-z0-9_-]{58}")))return null
            return try {
                val text=encoded.substring(3);val bytes=java.util.Base64.getUrlDecoder().decode(text)
                require(bytes.size==43 && java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)==text)
                require(bytes[0].toInt()==1 && bytes[1].toInt()==2 && bytes[2].toInt() in 0..1)
                val ready=bytes[2].toInt()==1
                val digest=bytes.copyOfRange(11,43)
                require(ready || digest.all { it.toInt()==0 })
                val words=java.nio.ByteBuffer.wrap(bytes).order(java.nio.ByteOrder.LITTLE_ENDIAN)
                Contract(words.getInt(3).toLong() and 0xffffffffL,words.getInt(7).toLong() and 0xffffffffL,
                    ready,if(ready)digest.joinToString("") { "%02x".format(it.toInt() and 255) } else "")
            } catch(_:Exception) { null }
        }
        fun requireHttpsSource(value:String) {
            val uri=java.net.URI(value)
            require(value.length<=2048 && uri.scheme=="https" && !uri.host.isNullOrBlank() && uri.userInfo==null && uri.fragment==null && uri.port in setOf(-1,443)) { "A fetchable HTTPS OTA source without credentials is required" }
        }
        internal fun parseDevices(network:String,value:JsonElement,at:Long):List<ZigbeeLiveDevice> {
            val rows=value as? JsonArray ?: error("Inventory must be an array")
            require(rows.size<=2000)
            val devices=rows.mapNotNull { element ->
                val row=element as? JsonObject ?: error("Invalid inventory row")
                val supported=row["supported"] as? JsonPrimitive
                if(supported==null || supported.isString || supported.booleanOrNull!=true)return@mapNotNull null
                val definition=row["definition"] as? JsonObject ?: return@mapNotNull null
                val vendor=definition.string("vendor") ?: return@mapNotNull null
                val model=definition.string("model") ?: return@mapNotNull null
                if(!FleetPolicy.recognisesZigbee(vendor,model))return@mapNotNull null
                val ieee=row.string("ieee_address")?.lowercase() ?: error("Missing IEEE")
                require(ieee.matches(Regex("0x[0-9a-f]{16}")))
                val name=row.string("friendly_name") ?: ieee
                require(name.length in 1..256 && name.none { it=='\u0000' || it=='+' || it=='#' || it.isISOControl() } && !name.startsWith("bridge/"))
                val capabilities=mutableSetOf<String>()
                if((definition["supports_ota"] as? JsonPrimitive)?.takeUnless { it.isString }?.booleanOrNull==true)capabilities+="zigbee_ota"
                fun exposes(value:JsonElement?,depth:Int=0) {
                    require(depth<=12)
                    when(value) {
                        is JsonArray -> value.forEach { exposes(it,depth+1) }
                        is JsonObject -> {
                            if(value.string("property")=="enter_recovery" && ((value["access"] as? JsonPrimitive)?.takeUnless { it.isString }?.intOrNull ?: 0) and 2 != 0)capabilities+="enter_recovery"
                            value["features"]?.let { exposes(it,depth+1) }
                        }
                        else -> Unit
                    }
                }
                exposes(definition["exposes"])
                val kind=if(vendor.equals("OpenVimar",true))FirmwareKind.CUSTOM else FirmwareKind.STOCK
                val version=row.string("software_build_id")?.takeIf { it.isNotBlank() && it.length<=64 }
                val record=DeviceRecord("zigbee:$network:$ieee",name,networkId=network,ieee=ieee,installedVersion=version,
                    firmwareKind=kind,capabilities=capabilities,observedAt=at,observationSource=ZigbeeDeviceMetadata.INVENTORY)
                ZigbeeLiveDevice(record,name,row.string("model_id"),(row["disabled"] as? JsonPrimitive)?.booleanOrNull ?: false)
            }
            require(devices.map { it.record.ieee }.distinct().size==devices.size) { "Ambiguous duplicate IEEE" }
            require(devices.map { it.friendlyName }.distinct().size==devices.size) { "Ambiguous friendly name" }
            return devices
        }
    }
}
internal fun JsonObject.string(name:String)=(this[name] as? JsonPrimitive)?.takeIf { it.isString }?.content
