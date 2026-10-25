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
    init {
        runCatching {
            val rows = JSONArray(preferences.getString("devices", "[]"))
            for (i in 0 until rows.length()) {
                val r=rows.getJSONObject(i);val uid=r.optJSONArray("uid") ?: JSONArray()
                val caps=r.optJSONArray("capabilities") ?: JSONArray()
                devices.add(DeviceRecord(r.getString("id"),r.getString("name"),r.optString("room"),r.optString("address").takeIf{it.isNotBlank()},List(uid.length()){uid.getString(it)},
                    r.optString("networkId").takeIf{it.isNotBlank()},r.optString("ieee").takeIf{it.isNotBlank()},r.optString("installedVersion").takeIf{it.isNotBlank()},
                    runCatching{FirmwareKind.valueOf(r.optString("firmwareKind","UNKNOWN"))}.getOrDefault(FirmwareKind.UNKNOWN),
                    List(caps.length()){caps.getString(it)}.toSet(),if(r.has("observedAt")&&!r.isNull("observedAt"))r.getLong("observedAt") else null,
                    r.optString("observationSource").takeIf{it.isNotBlank()}))
            }
        }
        runCatching {
            val rows=JSONArray(preferences.getString("batches","[]"))
            for(i in 0 until rows.length()) {
                val r=rows.getJSONObject(i)
                val prior=r.getString("status")
                batches.add(ActivityBatch(r.getString("id"),r.getString("digest"),r.getString("name"),r.getString("version"),r.getLong("at"),
                    if(prior=="In progress") "Interrupted · explicit resume required" else prior,r.optBoolean("expanded",true)))
            }
        }
    }
    fun save() {
        val rows=JSONArray();devices.forEach{r->rows.put(JSONObject().put("id",r.id).put("name",r.name).put("room",r.room).put("address",r.address ?: "").put("uid",JSONArray(r.uid))
            .put("networkId",r.networkId ?: "").put("ieee",r.ieee ?: "").put("installedVersion",r.installedVersion ?: "").put("firmwareKind",r.firmwareKind.name)
            .put("capabilities",JSONArray(r.capabilities.sorted())).put("observedAt",r.observedAt ?: JSONObject.NULL).put("observationSource",r.observationSource ?: ""))}
        val groups=JSONArray();batches.forEach{b->groups.put(JSONObject().put("id",b.id).put("digest",b.digest).put("name",b.deviceName).put("version",b.version).put("at",b.startedAt).put("status",b.status).put("expanded",b.expanded))}
        preferences.edit().putString("devices",rows.toString()).putString("batches",groups.toString()).apply()
    }
    fun upsert(record: DeviceRecord) { val i=devices.indexOfFirst{it.id==record.id};if(i<0)devices.add(record) else devices[i]=record;save() }
}
