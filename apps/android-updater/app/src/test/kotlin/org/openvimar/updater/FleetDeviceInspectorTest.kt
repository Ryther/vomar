package org.openvimar.updater

import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.core.*

class FleetDeviceInspectorTest {
    @Test fun readOnlyInspectionRecordsRealVersionAndRejectsWrongPlannedUidWithoutWrites()=runBlocking {
        var closes=0;val identity=RuntimeIdentity(1,"VIMAR30805",2,listOf("11111111","22222222"),"a".repeat(64))
        val transport=object:BleTransport {
            override suspend fun connect(address:String){}
            override suspend fun identity()=identity
            override suspend fun identityV2():RuntimeIdentity=throw IdentityCommandUnavailable()
            override suspend fun images()=RemoteImages(RemoteImage("b".repeat(64),false,true,"0.5.7.9"),RemoteImage("c".repeat(64),true,true,"0.7.3"))
            override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit)=error("Inspection cannot upload")
            override suspend fun reset():ResetAck=error("Inspection cannot reset")
            override suspend fun close(){closes++}
        }
        val inspector=FleetDeviceInspector({transport},{123L})
        val record=DeviceRecord("id","Desk",address="AA:BB:CC:DD:EE:FF")
        val result=inspector.inspect(record)
        assertEquals("0.5.7.9",result.installedVersion);assertEquals(identity.uid,result.uid);assertEquals(123L,result.observedAt)
        assertEquals(FirmwareKind.CUSTOM,result.firmwareKind);assertFalse("zigbee_ota_profile2" in result.capabilities)
        try{inspector.inspect(record.copy(uid=listOf("99999999","88888888")));fail("Wrong target accepted")}catch(_:IllegalArgumentException){}
        assertEquals(2,closes)
    }
}
