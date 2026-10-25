package org.openvimar.updater

import java.net.URI

/** Optional organisation only. These records never grant transport or update authority. */
internal data class DeviceRecord(val id: String, val name: String, val room: String = "", val address: String? = null, val uid: List<String> = emptyList(),
    val networkId:String?=null,val ieee:String?=null,val installedVersion:String?=null,val firmwareKind:FirmwareKind=FirmwareKind.UNKNOWN,
    val capabilities:Set<String> = emptySet(),val observedAt:Long?=null,val observationSource:String?=null) {
    companion object {
        fun from(pkg: PackageSummary) = DeviceRecord(pkg.uid.joinToString(":"), pkg.name, address=pkg.address, uid=pkg.uid)
    }
}
internal enum class Eligibility { CURRENT, UPDATE, BLOCKED }
internal data class DeviceStatus(val eligibility: Eligibility, val label: String, val reason: String)
internal object FleetPolicy {
    fun status(record:DeviceRecord,release:FleetReleaseRef?):DeviceStatus {
        if(release==null)return DeviceStatus(Eligibility.BLOCKED,"No release selected","Select a verified release to compare installed firmware.")
        if(record.firmwareKind==FirmwareKind.STOCK)return DeviceStatus(Eligibility.BLOCKED,"Stock firmware","A first installation is required before this update.")
        if(record.firmwareKind!=FirmwareKind.CUSTOM||record.installedVersion==null||record.observedAt==null||record.observationSource.isNullOrBlank())
            return DeviceStatus(Eligibility.BLOCKED,"Check version","Installed custom firmware has not been observed. Refresh the device before updating.")
        val current=version(record.installedVersion);val target=version(release.version)
        if(current==null||target==null)return DeviceStatus(Eligibility.BLOCKED,"Check version","An unrecognised version cannot establish update eligibility.")
        val comparison=current.zip(target).map{(a,b)->a.compareTo(b)}.firstOrNull{it!=0} ?: 0
        if(comparison==0)return DeviceStatus(Eligibility.CURRENT,"Up to date","This dimmer already uses the selected release.")
        if(comparison>0)return DeviceStatus(Eligibility.BLOCKED,"Newer firmware installed","Downgrades require a separate compatible release and explicit workflow.")
        val route=route(record,release)
        if(route==null)return DeviceStatus(Eligibility.BLOCKED,"Preparation required","No verified compatible update path is available for this device.")
        return DeviceStatus(Eligibility.UPDATE,"Update available · ${if(route==FleetRoute.BLE)"BT" else "Zigbee"}","A newer verified release is selected. Runtime compatibility is rechecked before any update.")
    }
    fun route(record:DeviceRecord,release:FleetReleaseRef):FleetRoute? = when {
        !record.networkId.isNullOrBlank()&&!record.ieee.isNullOrBlank()&&release.targetRecoveryHash!=null&&
            setOf("zigbee_ota","zigbee_ota_profile2","recovery_sha256:${release.targetRecoveryHash}").all{it in record.capabilities}&&release.zigbeeOta?.source?.startsWith("https://")==true->FleetRoute.ZIGBEE
        !record.address.isNullOrBlank()&&record.uid.size==2->FleetRoute.BLE
        else->null
    }
    private fun version(value:String):List<Long>? {
        if(!Regex("(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)(?:[+.](0|[1-9][0-9]*))?").matches(value))return null
        return value.split('.','+').map{it.toLongOrNull() ?: return null}.let{if(it.size==3)it+0L else it}
    }
    fun recognisesZigbee(vendor: String, model: String): Boolean =
        (vendor.equals("Vimar", true) && model == "30805") ||
        (vendor.equals("OpenVimar", true) && model == "30805-custom")
    fun matches(record: DeviceRecord, pkg: PackageSummary?) = pkg != null && record.uid.isNotEmpty() && record.uid == pkg.uid && record.address == pkg.address
    fun status(record: DeviceRecord, state: SessionPresentation): DeviceStatus {
        val pkg = state.packageSummary
        if (!state.loaded || !matches(record, pkg)) return DeviceStatus(Eligibility.BLOCKED, "Not updatable", "No matching verified package loaded. A saved record does not prove device identity.")
        if (state.imagesVerified || (state.bluetoothVerified && state.observedMainHash == pkg!!.mainHash))
            return DeviceStatus(Eligibility.CURRENT, "Up to date", "Target firmware verified on this device. Return online is confirmed separately.")
        if (state.bluetoothVerified && state.observedMainHash != null)
            return DeviceStatus(Eligibility.UPDATE, "Update available · BT", "A read-only Bluetooth check recognised the installed image. The updater rechecks before writing.")
        return DeviceStatus(Eligibility.BLOCKED, "Not updatable · check required", "Installed firmware has not been checked. Open the update session and choose Check Bluetooth.")
    }
}
internal object ReleaseSource {
    const val DEFAULT = "https://github.com/Ryther/vomar"
    fun parse(value: String): String? {
        val input = value.trim()
        val path = if (input.startsWith("https://")) {
            val uri = runCatching { URI(input) }.getOrNull() ?: return null
            if (uri.host != "github.com" || uri.userInfo != null || uri.port != -1 || uri.query != null || uri.fragment != null) return null
            uri.path.removePrefix("/").removeSuffix("/")
        } else input
        return path.takeIf { it.matches(Regex("[A-Za-z0-9_-]+/[A-Za-z0-9_-][A-Za-z0-9_.-]*")) && !it.endsWith(".git") }
    }
}
