package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test

class BrokerProfileValidationTest {
    private val network=ZigbeeNetwork("home","Home","zigbee2mqtt")
    private val profile=BrokerProfile("default","ssl://broker.example",listOf(network))

    @Test fun malformedBrokerIsNonthrowingAndDoesNotEchoTheInput() {
        val issues=profile.copy(serverUri="ssl://fixture-user:fixture-password@private-broker.example").validationIssues()
        assertEquals(listOf(BrokerValidationField.BROKER),issues.map { it.field })
        listOf("fixture-user","fixture-password","private-broker.example").forEach {
            assertFalse(issues.joinToString { issue -> issue.message }.contains(it))
        }
    }

    @Test fun networkNameAndTopicHaveSeparateRequiredAndRangeErrors() {
        val issues=profile.copy(networks=listOf(network.copy(label=" ",baseTopic=""))).validationIssues()
        assertEquals(setOf(BrokerValidationField.NETWORK_NAME,BrokerValidationField.BASE_TOPIC),issues.map { it.field }.toSet())
        assertTrue(issues.all { it.networkId=="home" && it.message.isNotBlank() })
        val longName=profile.copy(networks=listOf(network.copy(label="a".repeat(129)))).validationIssues()
        assertEquals(BrokerValidationField.NETWORK_NAME,longName.single().field)
        assertTrue(longName.single().message.contains("128"))
        val error=assertThrows(IllegalArgumentException::class.java) { profile.copy(networks=listOf(network.copy(label=""))).validated() }
        assertTrue(error.message.orEmpty().contains("name",true))
    }

    @Test fun invalidExactTopicsIdentifyTheirNetworkRow() {
        listOf("a/+","a/#","/a","a/","a//b","a/\u0000","a/\n","a".repeat(257)).forEach { topic ->
            val issue=profile.copy(networks=listOf(network.copy(baseTopic=topic))).validationIssues().single()
            assertEquals(BrokerValidationField.BASE_TOPIC,issue.field)
            assertEquals("home",issue.networkId)
        }
    }

    @Test fun overlappingTopicsMarkBothAffectedRowsAndAllowSiblingPrefixes() {
        listOf("zigbee2mqtt","zigbee2mqtt/nested").forEach { topic ->
            val issues=profile.copy(networks=listOf(network,network.copy(id="garage",label="Garage",baseTopic=topic))).validationIssues()
            assertEquals(setOf("home","garage"),issues.map { it.networkId }.toSet())
            assertTrue(issues.all { it.field==BrokerValidationField.BASE_TOPIC && it.message.contains("overlap",true) })
        }
        assertTrue(profile.copy(networks=listOf(network,network.copy(id="garage",label="Garage",baseTopic="zigbee2mqtt-garage"))).validationIssues().isEmpty())
    }

    @Test fun bareHostStillRequiresIndependentPlaintextConsent() {
        val bare=profile.copy(serverUri="broker.example:1833")
        assertEquals(BrokerValidationField.CONSENT,bare.validationIssues().single().field)
        val consented=bare.copy(allowInsecureLocal=true)
        assertTrue(consented.validationIssues().isEmpty())
        assertEquals("tcp://broker.example:1833",consented.validated().serverUri)
    }

    @Test fun networkCountAndDuplicateIdsHaveSafeProfileLevelErrors() {
        listOf(emptyList(),List(4) { network.copy(id="n$it",baseTopic="topic$it") },listOf(network,network.copy(baseTopic="other"))).forEach {
            val issues=profile.copy(networks=it).validationIssues()
            assertTrue(issues.any { issue -> issue.field==BrokerValidationField.NETWORKS && issue.message.isNotBlank() })
        }
    }

    @Test fun validThreeNetworkProfileHasNoIssuesAndRetainsCanonicalNormalization() {
        val source=profile.copy(serverUri=" Broker.Example:1833 ",allowInsecureLocal=true,
            networks=List(3) { network.copy(id="n$it",label="Network $it",baseTopic="network$it") })
        assertTrue(source.validationIssues().isEmpty())
        assertEquals("tcp://Broker.Example:1833",source.validated().serverUri)
    }
}
