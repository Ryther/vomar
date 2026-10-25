package org.openvimar.updater

import kotlinx.serialization.json.*

/** Reported display metadata only. Never grants firmware/update authority. */
internal object ZigbeeDeviceMetadata {
    const val INVENTORY="zigbee2mqtt/bridge/devices"
    const val STATE="zigbee2mqtt/device state"
    private const val CACHED=" (cached)"

    fun cached(record:DeviceRecord):Boolean = record.observationSource?.let {
        it.contains("bridge/devices") || it.endsWith(CACHED)
    } ?: true

    fun savedReading(record:DeviceRecord,connectionActive:Boolean,currentReport:DeviceRecord?):Boolean =
        !connectionActive || currentReport==null || cached(currentReport) ||
            currentReport.networkId!=record.networkId || currentReport.ieee!=record.ieee ||
            currentReport.installedVersion!=record.installedVersion

    private fun priority(record:DeviceRecord):Int {
        val source=record.observationSource ?: return 0
        return when {
            source.contains("bridge/devices") -> 1 // Device database, even when republished.
            source.endsWith(CACHED) -> 2
            else -> 3 // New state report or an explicit Bluetooth observation.
        }
    }

    /** A broker inventory must not roll back a version already reported on the
     * device topic. Fresh reports can decrease: this is not max(version). */
    fun preserveVersion(previous:DeviceRecord?,incoming:DeviceRecord):DeviceRecord {
        if(previous==null || previous.networkId!=incoming.networkId || previous.ieee!=incoming.ieee ||
            previous.firmwareKind!=incoming.firmwareKind || previous.installedVersion==null)return incoming
        if(incoming.installedVersion!=null && priority(incoming)>=priority(previous))return incoming
        return incoming.copy(installedVersion=previous.installedVersion,observedAt=previous.observedAt,
            observationSource=previous.observationSource)
    }

    fun fromState(device:ZigbeeLiveDevice,data:JsonObject,at:Long,retained:Boolean):DeviceRecord {
        fun text(name:String)=data.string(name)?.takeIf { it.isNotBlank() && it.length<=64 && it.none(Char::isISOControl) }
        val wire=if(device.record.firmwareKind==FirmwareKind.CUSTOM && device.modelId=="Vimar30805")
            (data["update"] as? JsonObject)?.get("installed_version")?.let { it as? JsonPrimitive }
                ?.takeUnless { it.isString }?.longOrNull?.takeIf { it in 0..0xffffffffL }
        else null
        // This packing is specific to our OpenVimar firmware (zigbee_ota.c).
        // Other manufacturers' OTA integers must never be decoded this way.
        val packed=wire?.let {
            val base="${it ushr 24}.${(it ushr 16) and 255}.${(it ushr 8) and 255}"
            if(it and 255L==0L)base else "$base.${it and 255}"
        }
        val version=text("software_build_id") ?: text("software_build") ?: packed ?: return device.record
        val source=STATE+if(retained)CACHED else ""
        if(device.record.installedVersion==version && device.record.observationSource==source)return device.record
        return preserveVersion(device.record,device.record.copy(installedVersion=version,observedAt=at,observationSource=source))
    }

    fun mergeSaved(saved:DeviceRecord,incoming:DeviceRecord):DeviceRecord {
        require(saved.networkId==incoming.networkId && saved.ieee==incoming.ieee) { "Different Zigbee source or device" }
        return preserveVersion(saved,incoming).copy(id=saved.id,name=saved.name,room=saved.room,
            address=saved.address?:incoming.address,uid=saved.uid.ifEmpty{incoming.uid})
    }
}
