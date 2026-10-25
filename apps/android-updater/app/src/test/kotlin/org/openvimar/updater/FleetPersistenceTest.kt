package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test
import java.nio.file.Files

class FleetPersistenceTest {
    @org.junit.Test fun persistsSchema3ReleaseReferencesWithoutChangingTheirAuthority() {
        val file=java.nio.file.Files.createTempDirectory("fleet-v3").resolve("queue").toFile()
        val ref=FleetReleaseRef("a".repeat(64),"0.9.0","b".repeat(64),"/private/release.zip",schemaVersion=3,targetRecoveryHash="c".repeat(64))
        val rows=listOf(FleetGroup("group",ref,emptyList(),FleetMode.SEQUENTIAL,123L,true,false))
        FileFleetQueuePersistence(file).save(rows)
        assertEquals(rows,FileFleetQueuePersistence(file).load())
    }
    @Test fun persistentGroupsKeepIndependentDeviceSnapshotsReleaseAndUncertainState() {
        val file=Files.createTempDirectory("fleet-test").resolve("queue").toFile()
        val device=DeviceRecord("id","A long lamp name","Room",uid=listOf("11111111","22222222"),networkId="network-a",ieee="0x123",
            installedVersion="0.7.0",firmwareKind=FirmwareKind.CUSTOM,capabilities=setOf("zigbee-ota"),observedAt=1234,observationSource="bridge/devices")
        val release=FleetReleaseRef("a".repeat(64),"0.8.0","b".repeat(64),"/private/release.zip")
        val rows=listOf(FleetGroup("group",release,listOf(FleetJob("job",device,FleetRoute.ZIGBEE,FleetJobState.UNCERTAIN_RESET,message="Acknowledgement missing")),FleetMode.NETWORK_PARALLEL,9876))
        val store=FileFleetQueuePersistence(file);store.save(rows)
        assertEquals(rows,FileFleetQueuePersistence(file).load())
        file.writeBytes(file.readBytes().dropLast(3).toByteArray())
        try{store.load();fail("Truncated durable state accepted")}catch(_:Exception){}
        file.parentFile!!.deleteRecursively()
    }
    @Test fun oversizedOrDuplicateDurableStateFailsClosed() {
        val file=Files.createTempDirectory("fleet-test").resolve("queue").toFile();val store=FileFleetQueuePersistence(file)
        assertTrue(store.load().isEmpty())
        file.writeBytes(ByteArray(4*1024*1024+1))
        try{store.load();fail("Unbounded state accepted")}catch(_:Exception){}
        file.parentFile!!.deleteRecursively()
    }
}
