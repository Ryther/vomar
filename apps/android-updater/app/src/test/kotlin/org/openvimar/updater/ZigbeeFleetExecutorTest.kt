package org.openvimar.updater

import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.*

class ZigbeeFleetExecutorTest {
    private val ieee="0x0011223344556677"
    private val source="https://example.test/main.ota"
    private fun pkg():ValidatedCommonPackage {
        val root=File("../test-fixtures")
        val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(File(root,"synthetic-common-ota-public.der").readBytes()))
        return File(root,"synthetic-common-ota.zip").inputStream().use { CommonPackageValidator.validate(CommonPackageReader.read(it),key,"0.4.0") }
    }
    private fun context(pkg:ValidatedCommonPackage):FleetExecutionContext {
        val m=pkg.manifest.zigbeeOta!!
        val ref=FleetReleaseRef(pkg.bundleDigest,pkg.manifest.main.version,pkg.manifest.main.signedRegionSha256,"synthetic-only.zip",zigbeeOta=ZigbeeOtaReference(m.manufacturerCode,m.imageType,m.fileVersion,m.fileSha256,m.size.toLong(),m.model,m.profile,source))
        return FleetExecutionContext("group",FleetJob("job",DeviceRecord("fixture","Desk",networkId="a",ieee=ieee,installedVersion="0.5.8",firmwareKind=FirmwareKind.CUSTOM),FleetRoute.ZIGBEE),ref)
    }
    private class FakeConnection:MqttConnection {
        val input=Channel<MqttSignal>(128);override val events=input.receiveAsFlow();override var connected=false
        var diagnosticSample=0
        var diagnosticRecovery=""
        var diagnosticBridge:ZigbeeBridge?=null
        val writes=mutableListOf<String>();var publish:suspend(String,String)->Unit={_,_->}
        override suspend fun connect(profile:BrokerProfile,credentials:BrokerCredentials?){connected=true}
        override suspend fun subscribe(filters:List<String>){}
        override suspend fun publish(topic:String,payload:ByteArray){
            writes+=topic
            if(topic.endsWith("/get")) {
                diagnosticSample++
                val binary=ByteArray(43).apply {
                    this[0]=1;this[1]=2;this[2]=1
                    java.nio.ByteBuffer.wrap(this).order(java.nio.ByteOrder.LITTLE_ENDIAN).putInt(3,diagnosticSample).putInt(7,1)
                    diagnosticRecovery.chunked(2).forEachIndexed { index,hex -> this[11+index]=hex.toInt(16).toByte() }
                }
                val contract="v1:"+java.util.Base64.getUrlEncoder().withoutPadding().encodeToString(binary)
                diagnosticBridge!!.consume(MqttMessageEnvelope("alpha/Desk",buildJsonObject { put("ota_contract",contract) }.toString().toByteArray()))
            } else publish(topic,payload.toString(Charsets.UTF_8))
        }
        override suspend fun disconnect(){connected=false};override fun close(){connected=false}
    }
    private suspend fun bridge(scope:CoroutineScope,connection:FakeConnection):ZigbeeBridge {
        val bridge=ZigbeeBridge(connection,scope,requestTimeoutMs=100,proofSampleDelayMs=0)
        bridge.connect(BrokerProfile("test","ssl://broker.example",listOf(ZigbeeNetwork("a","A","alpha"))),null)
        bridge.consume(MqttMessageEnvelope("alpha/bridge/devices","""[{"ieee_address":"$ieee","friendly_name":"Desk","supported":true,"model_id":"Vimar30805","definition":{"vendor":"OpenVimar","model":"30805-custom","supports_ota":true,"exposes":[]}}]""".toByteArray()))
        connection.diagnosticBridge=bridge;connection.diagnosticRecovery=pkg().manifest.targetRecoverySignedHash
        return bridge
    }
    private fun reply(bridge:ZigbeeBridge,body:String,operation:String,data:String) {
        val tx=Json.parseToJsonElement(body).jsonObject.getValue("transaction").jsonPrimitive.content
        bridge.consume(MqttMessageEnvelope("alpha/bridge/response/device/ota_update/$operation","""{"status":"ok","transaction":"$tx","data":{"id":"$ieee",$data}}""".toByteArray()))
    }
    @Test fun actualSignedFixtureAndHttpsBytesPrecedeUpdateAndFreshTargetReadConfirmsReturn()=runBlocking {
        val pkg=pkg();val context=context(pkg);val connection=FakeConnection();val bridge=bridge(this,connection);val events=mutableListOf<FleetExecutionEvent>();var checkedSource=false
        connection.publish={topic,body ->
            assertTrue(checkedSource)
            if(topic.endsWith("/check"))reply(bridge,body,"check","\"update_available\":true,\"source\":\"$source\"")
            else { assertTrue(events.any { it.submissionMayHaveStarted });reply(bridge,body,"update","\"to\":{\"file_version\":${pkg.manifest.zigbeeOta!!.fileVersion},\"software_build_id\":\"${context.release.version}\"}") }
        }
        val executor=ZigbeeFleetExecutor({bridge},{pkg},{url,size,sha -> assertEquals(source,url);assertEquals(pkg.zigbeeOta!!.size,size);assertEquals(pkg.manifest.zigbeeOta!!.fileSha256,sha);checkedSource=true},returnTimeoutMs=30)
        val result=executor.execute(context){events+=it}
        assertEquals(FleetJobState.VERIFIED,result.state);assertEquals(4,connection.writes.size);bridge.disconnect()
    }
    @Test fun missingCarrierOrHttpsHashFailureBlocksBeforeAnyBrokerCommand()=runBlocking {
        val pkg=pkg();val context=context(pkg);val connection=FakeConnection();val bridge=bridge(this,connection)
        val noCarrier=pkg.copy(manifest=pkg.manifest.copy(zigbeeOta=null),zigbeeOta=null)
        assertEquals(FleetJobState.BLOCKED,ZigbeeFleetExecutor({bridge},{noCarrier},{_,_,_->}).execute(context){}.state)
        assertEquals(FleetJobState.BLOCKED,ZigbeeFleetExecutor({bridge},{pkg},{_,_,_->error("Remote hash mismatch")}).execute(context){}.state)
        assertTrue(connection.writes.isEmpty());bridge.disconnect()
    }
    @Test fun deliveredTransferWithoutTargetReturnStaysUncertainAndNeverResubmits()=runBlocking {
        val pkg=pkg();val context=context(pkg);val connection=FakeConnection();val bridge=bridge(this,connection)
        connection.publish={topic,body ->
            if(topic.endsWith("/check"))reply(bridge,body,"check","\"update_available\":true,\"source\":\"$source\"")
            else reply(bridge,body,"update","\"to\":{\"file_version\":${pkg.manifest.zigbeeOta!!.fileVersion}}")
        }
        val executor=ZigbeeFleetExecutor({bridge},{pkg},{_,_,_->},returnTimeoutMs=30)
        val result=executor.execute(context){}
        assertEquals(FleetJobState.BLOCKED,executor.execute(context.copy(job=context.job.copy(id="another"))){}.state)
        assertEquals(FleetJobState.UNCERTAIN_RESET,result.state);assertEquals(4,connection.writes.size);bridge.disconnect()
    }
    @Test fun explicitReconciliationUsesOnlyCheckAndRejectsRetainedOrActiveEvidence()=runBlocking {
        val pkg=pkg();val context=context(pkg);val connection=FakeConnection();val bridge=bridge(this,connection)
        var retained=true;var installed=pkg.manifest.zigbeeOta!!.fileVersion;var state="idle"
        connection.publish={topic,body ->
            assertTrue(topic.endsWith("/check"))
            bridge.consume(MqttMessageEnvelope("alpha/Desk","""{"update":{"state":"$state","installed_version":$installed}}""".toByteArray(),retained))
            reply(bridge,body,"check","\"update_available\":false")
        }
        val executor=ZigbeeFleetExecutor({bridge},{pkg},{_,_,_->})
        assertEquals(FleetJobState.UNCERTAIN_RESET,executor.reconcile(context).state)
        retained=false;state="updating";assertEquals(FleetJobState.UNCERTAIN_RESET,executor.reconcile(context).state)
        state="idle";assertEquals(FleetJobState.VERIFIED,executor.reconcile(context).state)
        installed-=256;assertEquals(FleetJobState.PAUSED,executor.reconcile(context).state)
        assertEquals(4,connection.writes.size);bridge.disconnect()
    }
}
