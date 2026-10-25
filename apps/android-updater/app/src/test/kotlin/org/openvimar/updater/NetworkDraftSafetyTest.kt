package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test

class NetworkDraftSafetyTest {
    @Test fun validBareAndSecureAddressesKeepTheirOriginalText(){
        listOf("broker.example:1833","ssl://broker.example:8883","wss://broker.example/mqtt").forEach{assertEquals(it,safeNetworkAddressDraft(it))}
    }
    @Test fun malformedOrCredentialBearingAddressesCannotEnterSavedState(){
        listOf("tcp://private-user:private-password@broker.example","private-user:private-password@broker.example","tcp://broker.example?password=private-password","broker.example:").forEach{
            val saved=safeNetworkAddressDraft(it)
            assertEquals("",saved);assertFalse(saved.contains("private"))
        }
    }
    @Test fun networkIdsAreUniqueWhenSavedProfilesContainGaps(){
        assertEquals("network-1",nextNetworkDraftId(emptyList()))
        assertEquals("network-3",nextNetworkDraftId(listOf("network-1","network-2")))
        assertEquals("network-2",nextNetworkDraftId(listOf("network-1","network-3")))
        assertEquals("network-1",nextNetworkDraftId(listOf("ground","upstairs")))
    }
}
