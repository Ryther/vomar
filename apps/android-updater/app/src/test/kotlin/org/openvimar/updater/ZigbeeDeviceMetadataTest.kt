package org.openvimar.updater

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class ZigbeeDeviceMetadataTest {
    private val saved=DeviceRecord("saved-id","My lamp","My room",address="fixture-address",uid=listOf("a","b"),networkId="topic",ieee="0x0011223344556677",installedVersion="0.5.5",firmwareKind=FirmwareKind.CUSTOM,observedAt=1,observationSource=ZigbeeDeviceMetadata.INVENTORY)
    private fun state(json:String,retained:Boolean=false,record:DeviceRecord=saved)=ZigbeeDeviceMetadata.fromState(ZigbeeLiveDevice(record,"MQTT lamp","Vimar30805"),Json.parseToJsonElement(json).jsonObject,2,retained)
    @Test fun mergeKeepsLocalIdentityAndNamesWhileUpdatingReportedFirmware() {
        val incoming=state("""{"software_build_id":"1.0.0"}""").copy(id="incoming",name="MQTT lamp",room="",address=null,uid=emptyList())
        val merged=ZigbeeDeviceMetadata.mergeSaved(saved,incoming)
        assertEquals("1.0.0",merged.installedVersion);assertEquals(2L,merged.observedAt)
        assertEquals(saved.id,merged.id);assertEquals(saved.name,merged.name);assertEquals(saved.room,merged.room)
        assertEquals(saved.uid,merged.uid);assertEquals(saved.address,merged.address)
        assertThrows(IllegalArgumentException::class.java){ZigbeeDeviceMetadata.mergeSaved(saved,incoming.copy(networkId="different"))}
    }
    @Test fun noVersionAndMalformedWireVersionsDoNotInventOrEraseAReading() {
        listOf("""{"brightness":123}""","""{"update":{"latest_version":16777216}}""","""{"update":{"installed_version":"16777216"}}""","""{"update":{"installed_version":-1}}""","""{"update":{"installed_version":4294967296}}""","""{"update":{"installed_version":1.5}}""").forEach{assertEquals(saved,state(it))}
        assertEquals("0.5.5",ZigbeeDeviceMetadata.preserveVersion(saved,saved.copy(installedVersion=null)).installedVersion)
    }
    @Test fun wireTweakIsPreservedAndOnlyTheKnownCustomFormatIsDecoded() {
        assertEquals("1.0.0.3",state("""{"update":{"installed_version":16777219}}""").installedVersion)
        val stock=saved.copy(firmwareKind=FirmwareKind.STOCK)
        assertEquals(stock,state("""{"update":{"installed_version":16777216}}""",record=stock))
        assertEquals("1.0.0",state("""{"software_build_id":"1.0.0","update":{"installed_version":328960}}""").installedVersion)
    }
    @Test fun cachedReadingDoesNotOverwriteLiveButFreshVersionMayDecrease() {
        val fresh=state("""{"software_build_id":"1.0.0"}""")
        assertFalse(ZigbeeDeviceMetadata.cached(fresh))
        assertEquals(fresh,state("""{"software_build_id":"0.5.5"}""",true,fresh))
        assertEquals("0.5.5",state("""{"software_build_id":"0.5.5"}""",false,fresh).installedVersion)
        assertTrue(ZigbeeDeviceMetadata.cached(state("""{"software_build_id":"1.0.0"}""",true)))
    }
    @Test fun aNewConnectionMustNotMakeAnOlderSavedReadingLookFresh() {
        val fresh=state("""{"software_build_id":"1.0.0"}""")
        assertFalse(ZigbeeDeviceMetadata.savedReading(fresh,true,fresh))
        assertTrue(ZigbeeDeviceMetadata.savedReading(fresh,false,fresh))
        assertTrue(ZigbeeDeviceMetadata.savedReading(fresh,true,null))
        assertTrue(ZigbeeDeviceMetadata.savedReading(fresh,true,state("""{"software_build_id":"1.0.0"}""",true)))
        assertTrue(ZigbeeDeviceMetadata.savedReading(fresh,true,saved))
    }
}
