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

class ZigbeeDeviceLinkingTest {
    private val original=DeviceRecord("original:12345678:11223344","Dimmer · 3344",address="C0:00:00:00:00:01",uid=listOf("12345678","11223344"))
    private val reported=DeviceRecord("zigbee:topic:0xf4ce367811223344","Hall light",networkId="topic",ieee="0xf4ce367811223344",installedVersion="1.0.0",firmwareKind=FirmwareKind.CUSTOM,observedAt=2,observationSource=ZigbeeDeviceMetadata.INVENTORY)
    @Test fun liveZigbeeReportLinksAnExistingOriginalWithoutAddingAnotherDevice() {
        val rows=ZigbeeDeviceMetadata.reconcile(listOf(original),reported,addNew=false)
        assertEquals(1,rows.size)
        val linked=rows.single()
        assertEquals(original.id,linked.id);assertEquals(original.uid,linked.uid);assertEquals(original.address,linked.address)
        assertEquals("Hall light",linked.name);assertEquals(reported.ieee,linked.ieee);assertEquals("topic",linked.networkId)
        assertEquals("1.0.0",linked.installedVersion)
    }
    @Test fun importingZigbeeCollapsesAnExistingDuplicateAndPreservesLocalLabels() {
        val named=original.copy(name="My hallway",room="Upstairs")
        val rows=ZigbeeDeviceMetadata.reconcile(listOf(named,reported),reported.copy(installedVersion="1.0.1",observedAt=3),addNew=true)
        assertEquals(1,rows.size);assertEquals(named.id,rows.single().id);assertEquals("My hallway",rows.single().name)
        assertEquals("Upstairs",rows.single().room);assertEquals("1.0.1",rows.single().installedVersion)
    }
    @Test fun reportsDoNotImportUnrelatedDevicesOrMatchByName() {
        assertEquals(listOf(original),ZigbeeDeviceMetadata.reconcile(listOf(original),reported.copy(ieee="0xf4ce367811223345",name=original.name),addNew=false))
    }
    @Test fun anotherZigbeeTopicDoesNotReassignAnAlreadyLinkedDevice() {
        val linked=original.copy(networkId="other",ieee=reported.ieee)
        assertEquals(listOf(linked),ZigbeeDeviceMetadata.reconcile(listOf(linked),reported,addNew=false))
    }
    @Test fun ambiguousTruncatedIeeeNeverChoosesBetweenTwoFullUids() {
        val collision=original.copy(id="other-original",uid=listOf("87654378","11223344"))
        val originals=listOf(original,collision)
        assertEquals(originals,ZigbeeDeviceMetadata.reconcile(originals,reported,addNew=false))
    }
    @Test fun normalizationAndRepeatedReportsKeepTheSameCanonicalRecord() {
        val normalized=original.copy(uid=listOf("0x12345678","0x11223344"))
        val first=ZigbeeDeviceMetadata.reconcile(listOf(normalized),reported.copy(ieee=reported.ieee!!.uppercase()),addNew=true)
        assertEquals(1,first.size);assertEquals(original.id,first.single().id)
        assertEquals(reported.ieee,first.single().ieee);assertEquals("topic",first.single().networkId)
        assertEquals(first,ZigbeeDeviceMetadata.reconcile(first,reported,addNew=true))
    }
    @Test fun defaultNameFollowsZigbeeUntilTheUserChoosesTheirOwnName() {
        val first=ZigbeeDeviceMetadata.reconcile(listOf(original),reported,addNew=false)
        assertTrue(first.single().followZigbeeName)
        val renamed=ZigbeeDeviceMetadata.reconcile(first,reported.copy(name="New hall name"),addNew=false)
        assertEquals("New hall name",renamed.single().name)
        val custom=renamed.single().copy(name="My light",followZigbeeName=false)
        assertEquals("My light",ZigbeeDeviceMetadata.reconcile(listOf(custom),reported,addNew=false).single().name)
    }
    @Test fun explicitImportAddsOneNewZigbeeRecordWithoutInventingItsUid() {
        val result=ZigbeeDeviceMetadata.reconcile(emptyList(),reported,addNew=true)
        assertEquals(listOf(reported),result);assertTrue(result.single().uid.isEmpty())
    }
    @Test fun malformedIdentityCannotAttachAReportByItsName() {
        val malformed=original.copy(uid=listOf("not-hex","11223344"),name=reported.name)
        assertEquals(listOf(malformed),ZigbeeDeviceMetadata.reconcile(listOf(malformed),reported,addNew=false))
    }
    @Test fun exportedInventoryLinksTheOriginalBeforeTheLiveTopicIsKnown() {
        val exported=reported.copy(id="zigbee:${reported.ieee}",networkId=null)
        val saved=ZigbeeDeviceMetadata.reconcile(listOf(original),exported,addNew=true)
        assertEquals(1,saved.size);assertEquals(original.id,saved.single().id)
        assertEquals(reported.ieee,saved.single().ieee);assertNull(saved.single().networkId)
        val live=ZigbeeDeviceMetadata.reconcile(saved,reported,addNew=false)
        assertEquals(1,live.size);assertEquals("topic",live.single().networkId)
    }
    @Test fun anUnscopedExportCannotCoalesceTheSameIeeeAcrossDifferentTopics() {
        val records=listOf(reported,reported.copy(id="other",networkId="other"))
        assertEquals(records,ZigbeeDeviceMetadata.reconcile(records,reported.copy(networkId=null),addNew=true))
    }
    @Test fun knownUidCollisionsRemainAmbiguousAcrossTopics() {
        val other=original.copy(id="other",uid=listOf("87654378","11223344"),networkId="other",ieee=reported.ieee)
        val records=listOf(original,other)
        assertEquals(records,ZigbeeDeviceMetadata.reconcile(records,reported,addNew=false))
    }
    @Test fun scopedReportCannotChooseBetweenTwoKnownTopicsForAnUnlinkedOriginal() {
        val records=listOf(original,reported,reported.copy(id="other-topic",networkId="other"))
        assertEquals(records,ZigbeeDeviceMetadata.reconcile(records,reported,addNew=false))
    }
    @Test fun batchInventoryCannotChooseTheFirstOfTwoTopicsForAnUnlinkedOriginal() {
        val observations=listOf(reported,reported.copy(id="other-topic",networkId="other"))
        for(order in listOf(observations,observations.reversed()))
            assertEquals(listOf(original),ZigbeeDeviceMetadata.reconcileAll(listOf(original),order,addNew=false))
    }
    @Test fun sequentialTopicSnapshotsWaitBeforeAttachingAnUnlinkedOriginal() {
        val partial=ZigbeeDeviceMetadata.reconcileAll(listOf(original),listOf(reported),addNew=false,inventoryComplete=false)
        assertEquals(listOf(original),partial)
        val conflicting=listOf(reported,reported.copy(id="other-topic",networkId="other"))
        assertEquals(listOf(original),ZigbeeDeviceMetadata.reconcileAll(partial,conflicting,addNew=false,inventoryComplete=true))
        val completed=ZigbeeDeviceMetadata.reconcileAll(partial,listOf(reported),addNew=false,inventoryComplete=true)
        assertEquals("topic",completed.single().networkId)
    }
    @Test fun duplicateTopicInventoryStillUpdatesAnExplicitlyLinkedRecord() {
        val linked=original.copy(networkId=reported.networkId,ieee=reported.ieee)
        val observations=listOf(reported,reported.copy(id="other-topic",networkId="other"))
        val updated=ZigbeeDeviceMetadata.reconcileAll(listOf(linked),observations,addNew=false,inventoryComplete=false).single()
        assertEquals(linked.id,updated.id);assertEquals("topic",updated.networkId);assertEquals("1.0.0",updated.installedVersion)
    }
    @Test fun savedDuplicateMigrationKeepsTheNewestEqualPriorityObservation() {
        val newer=original.copy(installedVersion="1.2.0",firmwareKind=FirmwareKind.CUSTOM,observedAt=200,observationSource="Authenticated Bluetooth observation")
        val older=reported.copy(installedVersion="1.1.0",observedAt=100,observationSource=ZigbeeDeviceMetadata.STATE)
        val merged=ZigbeeDeviceMetadata.reconcile(listOf(newer,older),older,addNew=false,savedSnapshot=true).single()
        assertEquals("1.2.0",merged.installedVersion);assertEquals(200L,merged.observedAt)
    }
    @Test fun savedStockInventoryCannotOverwriteAnAuthenticatedCustomObservation() {
        val newer=original.copy(installedVersion="1.2.0",firmwareKind=FirmwareKind.CUSTOM,observedAt=200,observationSource="Authenticated Bluetooth observation")
        val older=reported.copy(installedVersion="1.2.1_z",firmwareKind=FirmwareKind.STOCK,observedAt=100)
        val merged=ZigbeeDeviceMetadata.reconcile(listOf(newer,older),older,addNew=false,savedSnapshot=true).single()
        assertEquals(FirmwareKind.CUSTOM,merged.firmwareKind);assertEquals("1.2.0",merged.installedVersion);assertEquals(200L,merged.observedAt)
    }
}
