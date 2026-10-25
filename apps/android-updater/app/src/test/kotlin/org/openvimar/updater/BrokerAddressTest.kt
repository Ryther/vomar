package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test

class BrokerAddressTest {
    private val network=ZigbeeNetwork("home","Home","zigbee2mqtt")
    private fun profile(address:String,consent:Boolean=true)=BrokerProfile("home",address,listOf(network),consent)

    @Test fun bareHostnamePreservesEnteredNonDefaultPort() {
        val source=profile("broker.example:1833")
        val validated=source.validated()
        assertEquals("tcp://broker.example:1833",validated.serverUri)
        assertEquals("broker.example:1833",source.serverUri)
        assertTrue(validated.allowInsecureLocal)
    }

    @Test fun hostnameIpv4AndBracketedIpv6NormalizeWithoutChangingPorts() {
        mapOf(
            "broker" to "tcp://broker",
            " broker.example:1 " to "tcp://broker.example:1",
            "broker-name.example:65535" to "tcp://broker-name.example:65535",
            "192.168.1.8:1833" to "tcp://192.168.1.8:1833",
            "[::1]:1833" to "tcp://[::1]:1833",
            "[2001:db8::8]" to "tcp://[2001:db8::8]"
        ).forEach { (input,expected) -> assertEquals(input,expected,profile(input).validated().serverUri) }
    }

    @Test fun explicitTransportsPreserveEndpointAndWebSocketPath() {
        listOf("tcp://Broker.Example:1833","ssl://Broker.Example:8883","ws://broker.example:8080/mqtt", "wss://Broker.Example/mqtt/%61").forEach {
            assertEquals(it,profile(it).validated().serverUri)
        }
    }

    @Test fun insecureConsentIsNeverInferredFromAddress() {
        listOf("broker.example:1833","192.168.1.8:1833","[::1]:1833","tcp://broker.example:1833","ws://broker.example/mqtt").forEach {
            assertError(it,"consent",false)
        }
        listOf("ssl://broker.example:8883","wss://broker.example/mqtt").forEach {
            assertFalse(profile(it,false).validated().allowInsecureLocal)
        }
    }

    @Test fun invalidPortsReceivePortGuidance() {
        listOf("broker.example:0","broker.example:65536","broker.example:-1","broker.example:","broker.example:abc","broker.example:999999999999999999999999", "ssl://broker.example:+1833","tcp://[::1]:0","wss://broker.example:abc/mqtt").forEach { assertError(it,"port") }
    }

    @Test fun invalidHostsAndSchemesReceiveSpecificGuidance() {
        listOf("","tcp://","tcp:///mqtt","tcp://bad host:1833","tcp://bad_host:1833","tcp://999.1.1.1:1833","tcp://[not-ipv6]:1833","2001:db8::1").forEach { assertError(it,"host") }
        listOf("http://broker.example:1833","mqtt://broker.example","https://broker.example").forEach { assertError(it,"scheme") }
    }

    @Test fun embeddedCredentialsQueryFragmentAndTcpPathAreRejectedSeparately() {
        listOf("tcp://fixture-user:fixture-secret@broker.example:1833","fixture-user:fixture-secret@broker.example:1833", "ssl://fixture-user@broker.example").forEach { assertError(it,"credentials") }
        listOf("ssl://broker.example?token=fixture-secret","wss://broker.example/mqtt?token=fixture-secret").forEach { assertError(it,"query") }
        assertError("ssl://broker.example#fixture-secret","fragment")
        listOf("tcp://broker.example/", "ssl://broker.example/mqtt").forEach { assertError(it,"path") }
    }

    @Test fun malformedUriErrorsNeverExposeRawAddressOrSecret() {
        listOf("wss://broker.example/mqtt/%xx", "tcp://[broken", "tcp://fixture-user:fixture-secret@bad host", "wss://broker.example/mqtt\nfixture-secret").forEach { input ->
            val error=assertThrows(IllegalArgumentException::class.java) { profile(input).validated() }
            assertFalse(error.message.orEmpty().contains("broker.example"))
            assertFalse(error.message.orEmpty().contains("fixture-secret"))
            assertNull(error.cause)
        }
    }

    @Test fun profileJsonStoresCanonicalAddressAndDecodeCanonicalizesLegacyBareAddress() {
        val source=profile("broker.example:1833")
        val encoded=BrokerProfileStore.encode(source)
        assertTrue(encoded.contains("tcp://broker.example:1833"))
        assertEquals("tcp://broker.example:1833",BrokerProfileStore.decode(encoded).serverUri)
        assertEquals("tcp://broker.example:1833",BrokerProfileStore.decode(encoded.replace("tcp://","")).serverUri)
    }

    private fun assertError(input:String,category:String,consent:Boolean=true) {
        val error=assertThrows("Address should fail validation",IllegalArgumentException::class.java) { profile(input,consent).validated() }
        assertTrue("Expected $category guidance, got ${error.message}",error.message.orEmpty().contains(category,true))
        assertFalse(error.message.orEmpty().contains("fixture-secret"))
        assertFalse(error.message.orEmpty().contains("broker.example"))
    }
}
