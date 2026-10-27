package org.openvimar.updater

import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ZigbeeBridgeTest {
    @Test fun lossDuringInitialSubscriptionsCannotBeOverwrittenByConnected()=runBlocking {
        val input=Channel<MqttSignal>(Channel.UNLIMITED)
        val connection=object:MqttConnection {
            override val events=input.receiveAsFlow()
            override val connected=true // Even if the adapter property lags, Lost is authoritative.
            override suspend fun connect(profile:BrokerProfile,credentials:BrokerCredentials?) {}
            override suspend fun subscribe(filters:List<String>) {input.send(MqttSignal.Lost());yield()}
            override suspend fun publish(topic:String,payload:ByteArray) {error("No commands")}
            override suspend fun disconnect() {input.close()}
            override fun close(){input.close()}
        }
        val bridge=ZigbeeBridge(connection,this)
        var lost=false
        try {bridge.connect(BrokerProfile("test","ssl://broker.invalid",listOf(ZigbeeNetwork("a","A","alpha"))),null)}
        catch(_:NetworkLostException){lost=true}
        finally {bridge.disconnect()}
        assertTrue("Connection loss during subscribe must fail establishment",lost)
        assertFalse(bridge.state.value.connected)
    }
    private fun contract(sample:Int,boot:Int,ready:Boolean,digest:String):String {
        val bytes=ByteArray(43).apply {
            this[0]=1;this[1]=2;this[2]=if(ready)1 else 0
            java.nio.ByteBuffer.wrap(this).order(java.nio.ByteOrder.LITTLE_ENDIAN).putInt(3,sample).putInt(7,boot)
            if(ready)digest.chunked(2).forEachIndexed { index,hex -> this[11+index]=hex.toInt(16).toByte() }
        }
        return "v1:"+java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
    }
    private val ieee="0x0011223344556677"
    private val other="0x8899aabbccddeeff"
    private fun inventory(ieee:String=this.ieee,vendor:String="OpenVimar",model:String="30805-custom")="""[{"ieee_address":"$ieee","friendly_name":"Desk","supported":true,"model_id":"Vimar30805","software_build_id":"0.5.8","definition":{"vendor":"$vendor","model":"$model","supports_ota":true,"exposes":[{"property":"enter_recovery","access":2}]}}]"""
    private class FakeConnection:MqttConnection {
        val input=Channel<MqttSignal>(128);override val events=input.receiveAsFlow()
        var online=false;override val connected get()=online
        val writes=mutableListOf<Pair<String,String>>()
        var onPublish:suspend(String,String)->Unit={_,_->}
        override suspend fun connect(profile:BrokerProfile,credentials:BrokerCredentials?){online=true}
        override suspend fun subscribe(filters:List<String>){}
        override suspend fun publish(topic:String,payload:ByteArray){check(online);writes+=topic to payload.toString(Charsets.UTF_8);onPublish(topic,payload.toString(Charsets.UTF_8))}
        override suspend fun disconnect(){online=false};override fun close(){online=false}
    }
    private suspend fun bridge(scope:CoroutineScope,conn:FakeConnection):ZigbeeBridge {
        val bridge=ZigbeeBridge(conn,scope,requestTimeoutMs=100,proofSampleDelayMs=0)
        bridge.connect(BrokerProfile("test","ssl://broker.example",listOf(ZigbeeNetwork("a","A","alpha"),ZigbeeNetwork("b","B","beta"))),null)
        bridge.consume(MqttMessageEnvelope("alpha/bridge/devices",inventory().toByteArray(),true));return bridge
    }
    @Test fun inventoryIsCompleteOnlyAfterEveryConfiguredTopicHasReported()=runBlocking {
        val conn=FakeConnection();val bridge=bridge(this,conn)
        assertFalse(bridge.state.value.inventoryReceived)
        bridge.consume(MqttMessageEnvelope("beta/bridge/devices","[]".toByteArray(),true))
        assertTrue(bridge.state.value.inventoryReceived)
        bridge.consume(MqttMessageEnvelope("alpha/bridge/devices","bad JSON".toByteArray(),true))
        assertFalse(bridge.state.value.inventoryReceived)
        bridge.disconnect()
    }
    @Test fun onlySupportedInventoryIsImportedAndStockCannotUseCustomBluetoothRoute()=runBlocking {
        val conn=FakeConnection();val bridge=bridge(this,conn)
        assertEquals(1,bridge.state.value.devices.size);assertEquals(FirmwareKind.CUSTOM,bridge.state.value.devices.single().firmwareKind)
        bridge.prepareBluetooth("a",ieee)
        assertEquals(listOf("alpha/$ieee/set" to "{\"enter_recovery\":true}"),conn.writes)
        bridge.consume(MqttMessageEnvelope("alpha/bridge/devices",inventory(vendor="Vimar",model="30805").toByteArray()))
        assertEquals(FirmwareKind.STOCK,bridge.state.value.devices.single().firmwareKind)
        var blocked=false;try{bridge.prepareBluetooth("a",ieee)}catch(_:IllegalArgumentException){blocked=true}
        assertTrue(blocked);assertEquals(1,conn.writes.size)
        bridge.consume(MqttMessageEnvelope("alpha/bridge/devices","bad JSON".toByteArray()))
        assertTrue(bridge.state.value.devices.isEmpty());bridge.disconnect()
    }
    @Test fun responsesRequireExactNetworkTransactionDeviceAndNonRetainedTopic()=runBlocking {
        val conn=FakeConnection();val bridge=bridge(this,conn)
        conn.onPublish={_,body ->
            val tx=Json.parseToJsonElement(body).jsonObject.getValue("transaction").jsonPrimitive.content
            fun reply(base:String,id:String,transaction:String,retained:Boolean=false) {
                bridge.consume(MqttMessageEnvelope("$base/bridge/response/device/ota_update/check","""{"status":"ok","transaction":"$transaction","data":{"id":"$id","update_available":true,"source":"https://example.test/main.ota"}}""".toByteArray(),retained))
            }
            reply("beta",ieee,tx);reply("alpha",other,tx);reply("alpha",ieee,"stale");reply("alpha",ieee,tx,true)
            reply("alpha",ieee,tx)
        }
        val result=bridge.check("a",ieee,"https://example.test/main.ota")
        assertTrue(result.available);assertEquals("https://example.test/main.ota",result.source)
        val request=Json.parseToJsonElement(conn.writes.single().second).jsonObject
        assertEquals("https://example.test/main.ota",request.getValue("url").jsonPrimitive.content)
        bridge.disconnect()
    }
    @Test fun malformedWrongTransactionsAndLossNeverBecomeSuccessOrRetry()=runBlocking {
        val conn=FakeConnection();val bridge=bridge(this,conn)
        conn.onPublish={_,_ -> bridge.consume(MqttMessageEnvelope("alpha/bridge/response/device/ota_update/check","{broken".toByteArray())) }
        var timedOut=false;try{bridge.check("a",ieee)}catch(_:TimeoutCancellationException){timedOut=true}
        assertTrue(timedOut);assertEquals(1,conn.writes.size)
        conn.onPublish={_,_ -> conn.input.send(MqttSignal.Lost()) }
        var lost=false;try{bridge.check("a",ieee)}catch(_:NetworkLostException){lost=true}
        assertTrue(lost);assertFalse(bridge.state.value.connected);assertEquals(2,conn.writes.size)
        bridge.disconnect()
    }
    @Test fun duplicateInventoryAndUnknownModelsNeverAuthorizeAnyCommand()=runBlocking {
        val conn=FakeConnection();val bridge=bridge(this,conn)
        val duplicate="["+inventory().removeSurrounding("[","]")+","+inventory().removeSurrounding("[","]")+"]"
        bridge.consume(MqttMessageEnvelope("alpha/bridge/devices",duplicate.toByteArray()))
        assertTrue(bridge.state.value.devices.isEmpty())
        var blocked=false;try{bridge.check("a",ieee)}catch(_:IllegalArgumentException){blocked=true}
        assertTrue(blocked);assertTrue(conn.writes.isEmpty())
        bridge.consume(MqttMessageEnvelope("alpha/bridge/devices",inventory(vendor="Other").toByteArray()))
        assertTrue(bridge.state.value.devices.isEmpty());bridge.disconnect()
    }

    @Test fun anOfflineBridgeBlocksNewCommandsWithoutPublishing()=runBlocking {
        val conn=FakeConnection();val bridge=bridge(this,conn)
        bridge.consume(MqttMessageEnvelope("alpha/bridge/state","{\"state\":\"offline\"}".toByteArray()))
        var blocked=false;try{bridge.prepareBluetooth("a",ieee)}catch(_:IllegalArgumentException){blocked=true}
        assertTrue(blocked);assertTrue(conn.writes.isEmpty());bridge.disconnect()
    }

    @Test fun profile2ProofRejectsCachedAggregateAndRequiresAdvancedAtomicSample()=runBlocking {
        val conn=FakeConnection();val bridge=bridge(this,conn);val expected="a".repeat(64)
        var sample=1;var boot=10;var retained=true;var ready=true;var digest=expected;var advance=false
        fun observation(retain:Boolean=retained) {
            val contract=contract(sample,boot,ready,digest)
            bridge.consume(MqttMessageEnvelope("alpha/Desk",buildJsonObject { put("ota_contract",contract);put("brightness",123) }.toString().toByteArray(),retain))
        }
        observation() // Retained aggregate is a baseline, never positive freshness evidence.
        conn.onPublish={topic,body ->
            assertEquals("alpha/$ieee/get",topic);assertEquals("{\"ota_contract\":\"\"}",body)
            if(advance)sample++;observation()
        }
        var refused=false;try{bridge.verifyRecoveryPair("a",ieee,expected)}catch(_:Exception){refused=true};assertTrue(refused)
        retained=false // An unrelated live payload containing the same cached aggregate cannot pass.
        refused=false;try{bridge.verifyRecoveryPair("a",ieee,expected)}catch(_:Exception){refused=true};assertTrue(refused)
        sample=0;refused=false;try{bridge.verifyRecoveryPair("a",ieee,expected)}catch(_:Exception){refused=true};assertTrue(refused)
        sample=1;refused=false;try{bridge.verifyRecoveryPair("a",ieee,expected)}catch(_:Exception){refused=true};assertTrue(refused) // A rejected stale sample must not regress the next baseline.
        advance=true;ready=false;refused=false;try{bridge.verifyRecoveryPair("a",ieee,expected)}catch(_:IllegalArgumentException){refused=true};assertTrue(refused)
        ready=true;digest="b".repeat(64);refused=false;try{bridge.verifyRecoveryPair("a",ieee,expected)}catch(_:IllegalArgumentException){refused=true};assertTrue(refused)
        digest=expected;bridge.verifyRecoveryPair("a",ieee,expected)
        assertTrue("zigbee_ota_profile2" in bridge.state.value.devices.single().capabilities)
        boot=11;sample=0;advance=false;bridge.verifyRecoveryPair("a",ieee,expected) // Different boot token permits reset sample, without diagnosing reset cause.
        bridge.disconnect()
    }

    @Test fun malformedAtomicContractsNeverGrantProfileCapability()=runBlocking {
        val conn=FakeConnection();val bridge=bridge(this,conn);val expected="a".repeat(64)
        val valid=ByteArray(43).apply { this[0]=1;this[1]=2;this[2]=1;java.nio.ByteBuffer.wrap(this).order(java.nio.ByteOrder.LITTLE_ENDIAN).putInt(3,2).putInt(7,10);fill(0xaa.toByte(),11,43) }
        val malformed=listOf(
            valid.copyOf().apply { this[0]=2 },valid.copyOf().apply { this[1]=1 },valid.copyOf().apply { this[2]=2 },
            valid.copyOf().apply { this[2]=0 },valid.copyOfRange(0,42))
            .map { "v1:"+java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(it) }+
            listOf("{\"v\":1,\"sample\":2}",contract(2,10,true,expected)+"=",contract(2,10,true,expected).dropLast(1)+"B")
        for(invalid in malformed) {
            conn.onPublish={_,_ -> bridge.consume(MqttMessageEnvelope("alpha/Desk",buildJsonObject { put("ota_contract",invalid) }.toString().toByteArray())) }
            var refused=false;try{bridge.verifyRecoveryPair("a",ieee,expected)}catch(_:Exception){refused=true};assertTrue(refused)
            assertFalse("zigbee_ota_profile2" in bridge.state.value.devices.single().capabilities)
        }
        bridge.disconnect()
    }
    @Test fun deviceStateUpdatesVersionWithoutReimportingOrSendingCommands()=runBlocking {
        val conn=FakeConnection();val bridge=bridge(this,conn)
        bridge.consume(MqttMessageEnvelope("alpha/bridge/devices",inventory().replace("0.5.8","0.5.5").toByteArray(),true))
        assertEquals("0.5.5",bridge.state.value.devices.single().installedVersion)
        bridge.consume(MqttMessageEnvelope("alpha/Desk","""{"update":{"installed_version":16777216,"latest_version":33554432}}""".toByteArray()))
        assertEquals("1.0.0",bridge.state.value.devices.single().installedVersion)
        assertTrue(conn.writes.isEmpty());bridge.disconnect()
    }
    @Test fun oldInventoryAndRetainedStateCannotReplaceANewerLiveVersion()=runBlocking {
        val conn=FakeConnection();val bridge=bridge(this,conn)
        bridge.consume(MqttMessageEnvelope("alpha/Desk","""{"software_build_id":"1.0.0"}""".toByteArray()))
        bridge.consume(MqttMessageEnvelope("alpha/bridge/devices",inventory().toByteArray(),true))
        bridge.consume(MqttMessageEnvelope("alpha/Desk","""{"software_build_id":"0.5.5"}""".toByteArray(),true))
        assertEquals("1.0.0",bridge.state.value.devices.single().installedVersion)
        // A genuine new report may go down in version; never just take max(version).
        bridge.consume(MqttMessageEnvelope("alpha/Desk","""{"software_build_id":"0.5.5"}""".toByteArray()))
        assertEquals("0.5.5",bridge.state.value.devices.single().installedVersion)
        bridge.disconnect()
    }
    @Test fun retainedInstalledVersionCanRefreshTheInventoryButLatestVersionCannot()=runBlocking {
        val conn=FakeConnection();val bridge=bridge(this,conn)
        bridge.consume(MqttMessageEnvelope("alpha/Desk","""{"update":{"latest_version":16777216}}""".toByteArray(),true))
        assertEquals("0.5.8",bridge.state.value.devices.single().installedVersion)
        bridge.consume(MqttMessageEnvelope("alpha/Desk","""{"update":{"installed_version":16777216}}""".toByteArray(),true))
        assertEquals("1.0.0",bridge.state.value.devices.single().installedVersion)
        assertTrue(bridge.state.value.devices.single().observationSource!!.contains("cached"))
        bridge.disconnect()
    }
    @Test fun versionUpdatesAreScopedToTheExactKnownTopicAndNeverDecodeStockWireVersions()=runBlocking {
        val conn=FakeConnection();val bridge=bridge(this,conn)
        bridge.consume(MqttMessageEnvelope("beta/bridge/devices",inventory().toByteArray(),true))
        bridge.consume(MqttMessageEnvelope("alpha/$ieee","""{"software_build":"1.0.0"}""".toByteArray()))
        assertEquals("1.0.0",bridge.state.value.devices.single{it.networkId=="a"}.installedVersion)
        assertEquals("0.5.8",bridge.state.value.devices.single{it.networkId=="b"}.installedVersion)
        bridge.consume(MqttMessageEnvelope("beta/bridge/devices",inventory(vendor="Vimar",model="30805").toByteArray(),true))
        bridge.consume(MqttMessageEnvelope("beta/Desk","""{"update":{"installed_version":16777216}}""".toByteArray()))
        assertEquals("0.5.8",bridge.state.value.devices.single{it.networkId=="b"}.installedVersion)
        assertTrue(conn.writes.isEmpty());bridge.disconnect()
    }
}
