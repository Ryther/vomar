package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test
import javax.crypto.AEADBadTagException
import javax.crypto.KeyGenerator

class MqttNetworkPolicyTest {
    private val network = ZigbeeNetwork("home", "Home", "zigbee2mqtt")
    @Test fun secureSchemesAndThreeDistinctNetworksAreAccepted() {
        listOf("ssl://broker.example:8883", "wss://broker.example/mqtt").forEach {
            BrokerProfile("default", it, listOf(network)).validated()
        }
        BrokerProfile("local", "tcp://127.0.0.1:1883", listOf(network), true).validated()
        listOf("ssl://name:secret@broker.example", "http://broker.example", "ssl://broker.example/#", "tcp://broker.example").forEach {
            assertThrows(IllegalArgumentException::class.java) { BrokerProfile("default", it, listOf(network)).validated() }
        }
        assertThrows(IllegalArgumentException::class.java) { BrokerProfile("default", "ssl://broker.example", listOf(network, network.copy(id="other", baseTopic="zigbee2mqtt/nested"))).validated() }
        assertThrows(IllegalArgumentException::class.java) { BrokerProfile("default", "ssl://broker.example", listOf(network.copy(baseTopic="house/+"))).validated() }
    }
    @Test fun aesGcmEnvelopeBindsBothCredentialsToProfileAndEndpoint() {
        val key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val profile = BrokerProfile("default", "ssl://broker.example", listOf(network))
        val secret = BrokerCredentials("fixture-user", "fixture-password".toCharArray())
        val a = BrokerSecretEnvelope.seal(key, profile, secret)
        val b = BrokerSecretEnvelope.seal(key, profile, secret)
        assertFalse(a.contentEquals(b))
        assertFalse(String(a, Charsets.ISO_8859_1).contains("fixture-password"))
        BrokerSecretEnvelope.open(key, profile, a).use {
            assertEquals("fixture-user", it.username); assertArrayEquals("fixture-password".toCharArray(), it.password)
        }
        assertThrows(Exception::class.java) { BrokerSecretEnvelope.open(key, profile.copy(serverUri="ssl://other.example"), a) }
        assertThrows(Exception::class.java) { BrokerSecretEnvelope.open(key, profile.copy(id="other"), a) }
        a[a.lastIndex] = (a.last().toInt() xor 1).toByte()
        assertThrows(Exception::class.java) { BrokerSecretEnvelope.open(key, profile, a) }
        assertThrows(Exception::class.java) { BrokerSecretEnvelope.open(key, profile, byteArrayOf(1,2)) }
        assertFalse(secret.toString().contains("fixture")); secret.close(); assertTrue(secret.password.all { it=='\u0000' })
    }
    @Test fun credentialEnvelopeTreatsBareAndCanonicalUriAsTheSameEndpoint() {
        val key=KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
        val bare=BrokerProfile("default","broker.example:1833",listOf(network),true)
        val canonical=bare.copy(serverUri="tcp://broker.example:1833")
        BrokerCredentials("fixture-user","fixture-password".toCharArray()).use { secret ->
            val fromBare=BrokerSecretEnvelope.seal(key,bare,secret)
            BrokerSecretEnvelope.open(key,canonical,fromBare).use {
                assertEquals("fixture-user",it.username)
                assertArrayEquals("fixture-password".toCharArray(),it.password)
            }
            val fromCanonical=BrokerSecretEnvelope.seal(key,canonical,secret)
            BrokerSecretEnvelope.open(key,bare,fromCanonical).use {
                assertEquals("fixture-user",it.username)
                assertArrayEquals("fixture-password".toCharArray(),it.password)
            }
            assertThrows(AEADBadTagException::class.java) {
                BrokerSecretEnvelope.open(key,bare.copy(serverUri="broker.example:1883"),fromCanonical)
            }
        }
    }
}
