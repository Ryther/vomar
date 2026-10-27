package org.openvimar.updater

import kotlinx.serialization.json.*

/** Reported display metadata only. Never grants firmware/update authority. */
internal object ZigbeeDeviceMetadata {
    const val INVENTORY="zigbee2mqtt/bridge/devices"
    const val STATE="zigbee2mqtt/device state"
    private const val CACHED=" (cached)"

    private fun uid(record:DeviceRecord):List<String>? {
        if(record.uid.size!=2)return null
        val words=record.uid.map{it.lowercase().removePrefix("0x")}
        return words.takeIf{it.all{word->word.matches(Regex("[0-9a-f]{1,8}"))}}?.map{it.padStart(8,'0')}
    }

    private fun ieee(record:DeviceRecord):String? = record.ieee?.lowercase()?.takeIf{it.matches(Regex("0x[0-9a-f]{16}"))}

    // Display association only: matches firmware/src/vimar_identity.c. The IEEE
    // retains only 40 UID bits, so ambiguous full UIDs must never be coalesced.
    private fun derivedIeee(record:DeviceRecord):String? = uid(record)?.let{"0xf4ce36${it[0].takeLast(2)}${it[1]}"}
    private fun generatedName(record:DeviceRecord):Boolean = uid(record)?.let{record.name=="Dimmer · ${it[1].takeLast(4)}"} ?: false

    private fun ambiguousUnlinked(records:List<DeviceRecord>,observations:List<DeviceRecord>,address:String):Boolean =
        records.any{it.networkId==null && derivedIeee(it)==address} &&
            (records+observations).filter{ieee(it)==address}.mapNotNull{it.networkId?.takeIf(String::isNotBlank)}.distinct().size>1

    fun reconcileAll(records:List<DeviceRecord>,observations:List<DeviceRecord>,addNew:Boolean,inventoryComplete:Boolean=true):List<DeviceRecord> =
        observations.fold(records){saved,observed->
            val address=ieee(observed)
            if(address!=null && (ambiguousUnlinked(saved,observations,address) ||
                !inventoryComplete && saved.any{it.networkId==null && derivedIeee(it)==address}))saved
            else reconcile(saved,observed,addNew)
        }

    fun reconcile(records:List<DeviceRecord>,incoming:DeviceRecord,addNew:Boolean,savedSnapshot:Boolean=false):List<DeviceRecord> {
        val address=ieee(incoming) ?: return records
        if(ambiguousUnlinked(records,listOf(incoming),address))return records
        val network=incoming.networkId?.takeIf{it.isNotBlank()}
        val identities=(records.filter{derivedIeee(it)==address}+incoming).mapNotNull(::uid).distinct()
        if(identities.size>1)return records
        val matches=records.filter{saved->
            val sameRoute=(network==null || saved.networkId==null || saved.networkId==network) && ieee(saved)==address
            val unlinkedOrSameTopic=network==null || saved.networkId==null || saved.networkId==network
            sameRoute || unlinkedOrSameTopic && (saved.ieee==null || ieee(saved)==address) && derivedIeee(saved)==address
        }
        if(network==null && matches.mapNotNull{it.networkId}.distinct().size>1)return records
        if((matches+incoming).mapNotNull(::uid).distinct().size>1)return records
        val observed=incoming.copy(ieee=address,networkId=network ?: matches.firstNotNullOfOrNull{it.networkId})
        if(matches.isEmpty())return if(addNew && records.none{it.id==observed.id})records+observed else records
        val canonical=matches.firstOrNull{uid(it)!=null && it.id.startsWith("original:")}
            ?: matches.firstOrNull{uid(it)!=null} ?: matches.first()
        val labels=matches.firstOrNull{!generatedName(it) && !it.followZigbeeName} ?: canonical
        val follows=generatedName(labels) || labels.followZigbeeName
        val previous=matches.filter{it.installedVersion!=null}.maxWithOrNull(
            compareBy<DeviceRecord>{priority(it)}.thenBy{it.observedAt ?: Long.MIN_VALUE}) ?: canonical
        var reading=preserveVersion(previous.copy(networkId=observed.networkId,ieee=address),observed)
        if(savedSnapshot && (priority(previous)>priority(observed) || priority(previous)==priority(observed) &&
            (previous.observedAt ?: Long.MIN_VALUE)>(observed.observedAt ?: Long.MIN_VALUE)))
            reading=reading.copy(installedVersion=previous.installedVersion,firmwareKind=previous.firmwareKind,
                capabilities=previous.capabilities,observedAt=previous.observedAt,observationSource=previous.observationSource)
        val merged=reading.copy(
            id=canonical.id,name=if(follows)observed.name else labels.name,
            room=canonical.room.ifBlank{matches.firstOrNull{it.room.isNotBlank()}?.room.orEmpty()},
            address=canonical.address ?: matches.firstNotNullOfOrNull{it.address} ?: observed.address,
            uid=canonical.uid.ifEmpty{observed.uid},followZigbeeName=follows)
        val ids=matches.map{it.id}.toSet()
        return records.mapNotNull{if(it.id==canonical.id)merged else if(it.id in ids)null else it}
    }

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
        return preserveVersion(saved,incoming).copy(id=saved.id,name=if(saved.followZigbeeName)incoming.name else saved.name,room=saved.room,
            address=saved.address?:incoming.address,uid=saved.uid.ifEmpty{incoming.uid},followZigbeeName=saved.followZigbeeName)
    }
}
