package org.openvimar.updater

internal data class DkUsbEndpointDescriptor(val address: Int, val attributes: Int,
    val maxPacketSize: Int, val interval: Int) {
    val direction get() = address and 0x80
    val type get() = attributes and 3
    fun reportFields(index: Int): Map<String, Any> = mapOf("index" to index,
        "address" to address, "attributes" to attributes, "direction" to direction,
        "type" to type, "maxPacketSize" to maxPacketSize, "interval" to interval)
}

internal data class DkUsbInterfaceDescriptor(val index: Int, val id: Int,
    val alternateSetting: Int, val interfaceClass: Int, val subclass: Int,
    val protocol: Int, val name: String?, val endpoints: List<DkUsbEndpointDescriptor>) {
    fun reportFields(): Map<String, Any?> = mapOf("index" to index, "id" to id,
        "alternateSetting" to alternateSetting, "class" to interfaceClass,
        "subclass" to subclass, "protocol" to protocol, "name" to name,
        "endpointCount" to endpoints.size, "endpoints" to endpoints.mapIndexed { i, ep -> ep.reportFields(i) })
}

internal data class DkJlinkInterfaceSelection(val interfaces: List<DkUsbInterfaceDescriptor>,
    val port: DkUsbInterfaceDescriptor?, val error: String?) {
    val input get() = port?.endpoints?.singleOrNull { it.type == 2 && it.direction == 0x80 }
    val output get() = port?.endpoints?.singleOrNull { it.type == 2 && it.direction == 0 }
    fun reportFields(): Map<String, Any?> = mapOf("status" to if (port == null) "rejected" else "selected",
        "error" to error, "interfaceDescriptors" to interfaces.map { it.reportFields() })
}

internal object DkJlinkInterfaceSelector {
    /** libjaylink transport_usb.c initialize_handle(), commit
     * 5b9ab7b06249af69d349c3ce8b29e8769845071e, recognizes class/subclass ff/ff
     * across interfaces, rather than requiring interface number zero:
     * https://gitlab.zapb.de/libjaylink/libjaylink/-/blob/5b9ab7b06249af69d349c3ce8b29e8769845071e/libjaylink/transport_usb.c
     * This diagnostic is stricter: only the supported device, default alternate,
     * one unambiguous interface and exactly one bulk endpoint in each direction.
     * Unknown layouts are inventoried and rejected before opening the device.
     */
    fun select(vendorId: Int, productId: Int, interfaces: List<DkUsbInterfaceDescriptor>): DkJlinkInterfaceSelection {
        if (vendorId != 0x1366 || productId != 0x1060)
            return DkJlinkInterfaceSelection(interfaces, null, "Unsupported USB device. Save the diagnostic report.")
        val candidates = interfaces.filter { port ->
            port.alternateSetting == 0 && port.interfaceClass == 255 && port.subclass == 255 &&
                port.endpoints.size == 2 && port.endpoints.all { it.type == 2 } &&
                port.endpoints.count { it.direction == 0x80 } == 1 &&
                port.endpoints.count { it.direction == 0 } == 1
        }
        return when (candidates.size) {
            1 -> DkJlinkInterfaceSelection(interfaces, candidates.single(), null)
            0 -> DkJlinkInterfaceSelection(interfaces, null,
                "No supported J-Link command interface (class/subclass ff/ff with one bulk IN and OUT) was found. Save the diagnostic report.")
            else -> DkJlinkInterfaceSelection(interfaces, null,
                "Ambiguous J-Link command interfaces; no USB commands were sent. Save the diagnostic report.")
        }
    }
}
