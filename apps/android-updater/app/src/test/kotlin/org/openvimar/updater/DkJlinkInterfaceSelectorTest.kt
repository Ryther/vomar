package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test

class DkJlinkInterfaceSelectorTest {
    private fun endpoint(address: Int, attributes: Int = 2) =
        DkUsbEndpointDescriptor(address, attributes, 64, 0)

    private fun port(index: Int = 0, id: Int = index, klass: Int = 255,
        subclass: Int = 255, alternate: Int = 0,
        endpoints: List<DkUsbEndpointDescriptor> = listOf(endpoint(0x81), endpoint(0x01))) =
        DkUsbInterfaceDescriptor(index, id, alternate, klass, subclass, 255, "J-Link", endpoints)

    // Composite layout model, not a captured descriptor dump from the phone.
    private fun composite() = listOf(
        port(0, klass = 8, subclass = 6, endpoints = listOf(endpoint(0x82), endpoint(2))),
        port(1, klass = 2, subclass = 2, endpoints = listOf(endpoint(0x83, 3))),
        port(2, klass = 10, subclass = 0, endpoints = listOf(endpoint(0x84), endpoint(4))),
        port(3, klass = 255, subclass = 0, endpoints = listOf(endpoint(0x85), endpoint(5))),
        port(4, endpoints = listOf(endpoint(0x86), endpoint(6))))

    private fun select(interfaces: List<DkUsbInterfaceDescriptor>, vendor: Int = 0x1366,
        product: Int = 0x1060) = DkJlinkInterfaceSelector.select(vendor, product, interfaces)

    @Test fun selectsJlinkCommandInterfaceAfterMsdCdcAndOtherVendorInterfaces() {
        val selected = select(composite())
        assertNull(selected.error)
        assertEquals(4, selected.port?.index)
        assertEquals(0x86, selected.input?.address)
        assertEquals(6, selected.output?.address)
    }

    @Test fun keepsValidOriginalInterfaceZeroAndUsesDescriptorIndexSeparatelyFromId() {
        assertEquals(0, select(listOf(port())).port?.id)
        assertEquals(9, select(listOf(port(index = 0, id = 9))).port?.id)
        assertEquals(0, select(listOf(port(index = 0, id = 9))).port?.index)
    }

    @Test fun rejectsMsdCdcAndVendorSubclassWithoutJlinkSignature() {
        for (candidate in listOf(port(klass = 8, subclass = 6), port(klass = 10, subclass = 0),
            port(klass = 255, subclass = 0))) {
            assertNull(select(listOf(candidate)).port)
            assertNotNull(select(listOf(candidate)).error)
        }
    }

    @Test fun rejectsNonBulkMissingDuplicateAndExtraEndpoints() {
        val badEndpoints = listOf(
            listOf(endpoint(0x81, 3), endpoint(1)), listOf(endpoint(0x81)),
            listOf(endpoint(0x81), endpoint(0x82)), listOf(endpoint(1), endpoint(2)),
            listOf(endpoint(0x81), endpoint(1), endpoint(0x82)),
            listOf(endpoint(0x81), endpoint(1), endpoint(0x83, 3)))
        for (endpoints in badEndpoints) assertNull(select(listOf(port(endpoints = endpoints))).port)
    }

    @Test fun rejectsAmbiguityWithoutChoosingTheFirstChannel() {
        val selected = select(listOf(port(), port(1)))
        assertNull(selected.port)
        assertNull(selected.input)
        assertNull(selected.output)
        assertTrue(selected.error.orEmpty().contains("Ambiguous"))
    }

    @Test fun rejectsUnknownDeviceAndNonDefaultAlternateWithoutOpeningAnything() {
        assertNull(select(listOf(port()), vendor = 0x1234).port)
        assertNull(select(listOf(port()), product = 0x1234).port)
        assertNull(select(listOf(port(alternate = 1))).port)
    }

    @Test fun failureRetainsEveryDescriptorAndActionableReason() {
        val inventory = composite().dropLast(1)
        val selected = select(inventory)
        assertNotNull(selected.error)
        val fields = selected.reportFields()
        assertEquals("rejected", fields["status"])
        assertEquals(selected.error, fields["error"])
        val descriptors = fields["interfaceDescriptors"] as List<*>
        assertEquals(4, descriptors.size)
        val first = descriptors[0] as Map<*, *>
        assertEquals(0, first["index"])
        assertEquals(0, first["id"])
        assertEquals(0, first["alternateSetting"])
        assertEquals(8, first["class"])
        assertEquals(6, first["subclass"])
        assertEquals(255, first["protocol"])
        assertEquals("J-Link", first["name"])
        assertEquals(2, first["endpointCount"])
        assertEquals(mapOf("index" to 0, "address" to 130, "attributes" to 2,
            "direction" to 128, "type" to 2, "maxPacketSize" to 64, "interval" to 0),
            (first["endpoints"] as List<*>)[0])
        assertTrue(selected.error.orEmpty().contains("Save"))
    }
}
