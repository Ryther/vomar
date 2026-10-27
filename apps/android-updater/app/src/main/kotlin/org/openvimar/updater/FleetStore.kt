package org.openvimar.updater

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

internal data class ActivityBatch(val id: String, val digest: String, val deviceName: String, val version: String, val startedAt: Long, var status: String, var expanded: Boolean = true)

/** App-private organisational metadata, separate from authoritative engine checkpoints. */
internal class FleetStore(context: Context) {
    val preferences = context.getSharedPreferences("fleet-ui", Context.MODE_PRIVATE)
    val devices = mutableListOf<DeviceRecord>()
    val batches = mutableListOf<ActivityBatch>()
    private var metadataReadable=true
    init {
        val devicesLoaded=runCatching {
            val rows = JSONArray(preferences.getString("devices", "[]"))
            for (i in 0 until rows.length()) {
                val r=rows.getJSONObject(i);val uid=r.optJSONArray("uid") ?: JSONArray()
                val caps=r.optJSONArray("capabilities") ?: JSONArray()
                val legacyIeee=r.getString("id").takeIf{it.matches(Regex("zigbee:0x[0-9a-fA-F]{16}"))}?.removePrefix("zigbee:")?.lowercase()
                devices.add(DeviceRecord(r.getString("id"),r.getString("name"),r.optString("room"),r.optString("address").takeIf{it.isNotBlank()},List(uid.length()){uid.getString(it)},
                    r.optString("networkId").takeIf{it.isNotBlank()},r.optString("ieee").takeIf{it.isNotBlank()} ?: legacyIeee,r.optString("installedVersion").takeIf{it.isNotBlank()},
                    runCatching{FirmwareKind.valueOf(r.optString("firmwareKind","UNKNOWN"))}.getOrDefault(FirmwareKind.UNKNOWN),
                    List(caps.length()){caps.getString(it)}.toSet(),if(r.has("observedAt")&&!r.isNull("observedAt"))r.getLong("observedAt") else null,
                    r.optString("observationSource").takeIf{it.isNotBlank()},r.optBoolean("followZigbeeName",false)))
            }
        }.isSuccess
        val batchesLoaded=runCatching {
            val rows=JSONArray(preferences.getString("batches","[]"))
            for(i in 0 until rows.length()) {
                val r=rows.getJSONObject(i)
                val prior=r.getString("status")
                batches.add(ActivityBatch(r.getString("id"),r.getString("digest"),r.getString("name"),r.getString("version"),r.getLong("at"),
                    if(prior=="In progress") "Interrupted · explicit resume required" else prior,r.optBoolean("expanded",true)))
            }
        }.isSuccess
        metadataReadable=devicesLoaded&&batchesLoaded
        if(metadataReadable&&reconcileSaved())save()
    }
    fun save() {
        check(metadataReadable){"Saved device/activity data could not be read completely; existing records have been preserved"}
        val rows=JSONArray();devices.forEach{r->rows.put(JSONObject().put("id",r.id).put("name",r.name).put("room",r.room).put("address",r.address ?: "").put("uid",JSONArray(r.uid))
            .put("networkId",r.networkId ?: "").put("ieee",r.ieee ?: "").put("installedVersion",r.installedVersion ?: "").put("firmwareKind",r.firmwareKind.name)
            .put("capabilities",JSONArray(r.capabilities.sorted())).put("observedAt",r.observedAt ?: JSONObject.NULL).put("observationSource",r.observationSource ?: "").put("followZigbeeName",r.followZigbeeName))}
        val groups=JSONArray();batches.forEach{b->groups.put(JSONObject().put("id",b.id).put("digest",b.digest).put("name",b.deviceName).put("version",b.version).put("at",b.startedAt).put("status",b.status).put("expanded",b.expanded))}
        preferences.edit().putString("devices",rows.toString()).putString("batches",groups.toString()).apply()
    }
    fun archivedActivities():Set<String> = preferences.getStringSet("archivedActivities",emptySet()).orEmpty().toSet()
    fun setActivityArchived(id:String,value:Boolean){
        require(id.isNotBlank()&&id.length<=256)
        val ids=archivedActivities().toMutableSet();if(value)ids.add(id)else ids.remove(id)
        check(preferences.edit().putStringSet("archivedActivities",ids).commit()){"Could not save activity archive"}
    }
    private fun reconcileSaved():Boolean {
        var linked=devices.toList()
        for(record in devices.toList())if(record.ieee!=null)
            linked=ZigbeeDeviceMetadata.reconcile(linked,record,addNew=false,savedSnapshot=true)
        if(linked==devices)return false
        devices.clear();devices.addAll(linked);return true
    }
    fun mergeZigbee(record:DeviceRecord,addNew:Boolean=false):Boolean = mergeZigbee(listOf(record),addNew)
    fun mergeZigbee(observations:List<DeviceRecord>,addNew:Boolean=false,inventoryComplete:Boolean=true):Boolean {
        if(!metadataReadable)return false
        val linked=ZigbeeDeviceMetadata.reconcileAll(devices,observations,addNew,inventoryComplete)
        if(linked==devices)return false
        devices.clear();devices.addAll(linked);save();return true
    }
    fun upsert(record: DeviceRecord) { val i=devices.indexOfFirst{it.id==record.id};if(i<0)devices.add(record) else devices[i]=record;reconcileSaved();save() }
}
