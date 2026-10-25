package org.openvimar.updater

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class SavedConnectionsTest {
    private val original=BrokerProfile("home","ssl://broker.example",listOf(ZigbeeNetwork("legacy-topic","Ground floor","zigbee2mqtt")))
    @Test fun legacyProfileGetsAReadableConnectionNameWithoutChangingTopicIdentity() {
        val encoded=BrokerProfileStore.encode(original)
        assertEquals("Home",Json.parseToJsonElement(encoded).jsonObject["label"]?.jsonPrimitive?.content)
        val restored=BrokerProfileStore.decode(encoded)
        assertEquals("legacy-topic",restored.networks.single().id)
    }
    @Test fun duplicateTopicNamesAreRejectedSoDiscoveryLabelsAreUnambiguous() {
        val invalid=original.copy(networks=listOf(original.networks.single(),ZigbeeNetwork("another","Ground floor","other")))
        assertTrue(invalid.validationIssues().any{it.field==BrokerValidationField.NETWORK_NAME})
    }
    @Test fun catalogKeepsProfilesAndRejectsCrossBrokerTopicAliases() {
        val other=original.copy(id="workshop",label="Workshop",serverUri="ssl://workshop.example",networks=listOf(ZigbeeNetwork("workshop-topic","Garden","zigbee2mqtt")))
        val all=BrokerProfileStore.replaceInCatalog(listOf(original),other)
        assertEquals(listOf(original,other),BrokerProfileStore.decodeCatalog(BrokerProfileStore.encodeCatalog(all)))
        assertThrows(IllegalArgumentException::class.java){BrokerProfileStore.replaceInCatalog(listOf(original),other.copy(networks=original.networks))}
        assertThrows(IllegalArgumentException::class.java){BrokerProfileStore.replaceInCatalog(listOf(original),other.copy(label="HOME"))}
        val renamed=original.copy(label="My home",networks=original.networks.map{it.copy(label="Downstairs")})
        assertFalse(connectionTransportChanged(original,renamed))
        assertTrue(connectionTransportChanged(original,original.copy(serverUri="ssl://elsewhere.example")))
        assertEquals(original.id,BrokerProfileStore.replaceInCatalog(all,renamed).first().id)
    }
    @Test fun unresolvedAndRunningUpdatesKeepTheirConnectionReserved() {
        val r=DeviceRecord("device","Lamp",networkId="legacy-topic",ieee="fixture")
        val release=FleetReleaseRef("a","1","b","unused")
        fun held(state:FleetJobState,paused:Boolean=true)=connectionHasPendingUpdates(original,listOf(FleetGroup("group",release,listOf(FleetJob("job",r,FleetRoute.ZIGBEE,state=state)),FleetMode.SEQUENTIAL,0,paused)))
        assertTrue(held(FleetJobState.RUNNING));assertTrue(held(FleetJobState.UNCERTAIN_RESET));assertTrue(held(FleetJobState.AWAITING_RETURN))
        assertFalse(held(FleetJobState.VERIFIED));assertFalse(held(FleetJobState.PAUSED));assertFalse(held(FleetJobState.QUEUED))
        assertTrue(held(FleetJobState.QUEUED,false))
        assertFalse(connectionHasPendingUpdates(null,emptyList()))
    }
    @Test fun legacyDuplicateNamesGetReadableSuffixesWithoutLosingBindings() {
        val legacy="""{"id":"home","serverUri":"ssl://broker.example","networks":[{"id":"old-a","label":"Home","baseTopic":"alpha"},{"id":"old-b","label":"Home","baseTopic":"beta"}]}"""
        val restored=BrokerProfileStore.decode(legacy)
        assertEquals(listOf("old-a","old-b"),restored.networks.map{it.id})
        assertEquals(listOf("Home","Home (2)"),restored.networks.map{it.label})
    }
    @Test fun endpointAndBaseTopicChangesCannotReuseExistingDeviceBindings() {
        assertThrows(IllegalArgumentException::class.java){BrokerProfileStore.replaceInCatalog(listOf(original),original.copy(serverUri="ssl://other.example"))}
        assertThrows(IllegalArgumentException::class.java){BrokerProfileStore.replaceInCatalog(listOf(original),original.copy(networks=listOf(original.networks.single().copy(baseTopic="new-source"))))}
        val changed=original.copy(networks=listOf(original.networks.single().copy(id="new-binding",baseTopic="new-source")))
        assertEquals(changed,BrokerProfileStore.replaceInCatalog(listOf(original),changed).single())
    }
}
