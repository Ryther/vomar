package org.openvimar.updater.core

import org.openvimar.installer.StrictJson

/** Download identity only. Existing signed common-package admission is still mandatory. */
object DistributionAssets {
    data class Asset(val role:String,val filename:String,val size:Int,val sha256:String,val componentVersion:String)
    data class Selection(val tag:String,val firmware:Asset,val ota:Asset,val assets:List<Asset>,val experimentalFirmware:Boolean=false) {
        fun requireAutomaticFirmware():Selection {
            require(!experimentalFirmware){"Firmware is experimental; import ZIP through Bluetooth trial"}
            return this
        }
    }
    private val required=setOf("firmware-common","zigbee-ota","android-apk","desktop-linux-x64","desktop-windows-x64","desktop-windows-setup","desktop-macos-arm64","zigbee2mqtt-converter","licenses","offline-guide")
    fun parse(raw:ByteArray,tag:String):Selection {
        require(raw.size in 1..65536)
        val m=StrictJson.parse(raw) as? Map<*,*> ?: error("Distribution object required")
        require(m.keys==setOf("schemaVersion","distributionVersion","tag","commit","components","artifacts")&&m["schemaVersion"]==1L)
        val v=m["distributionVersion"] as? String ?: error("Distribution version required")
        require(Regex("(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)").matches(v)&&tag=="v$v"&&m["tag"]==tag)
        require((m["commit"] as? String)?.matches(Regex("[0-9a-f]{40}"))==true)
        val semver=Regex("(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)\\.(0|[1-9][0-9]*)")
        val components=m["components"] as? Map<*,*> ?: error("Component versions required")
        require(components.keys==setOf("firmware","android","desktop","zigbee2mqtt")){"Missing or unknown component owner"}
        require(components.all{(key,value)->key is String&&Regex("[a-z][a-z0-9-]*").matches(key)&&value is String&&semver.matches(value)})
        val rows=m["artifacts"] as? List<*> ?: error("Distribution artifacts required");require(rows.size in required.size..32)
        val roles=mutableSetOf<String>();val names=mutableSetOf<String>();val assets=rows.map{entry->
            val a=entry as? Map<*,*> ?: error("Asset object required")
            require(a.keys.containsAll(setOf("role","filename","size","sha256","componentVersion"))&&(a.keys-setOf("role","filename","size","sha256","componentVersion")).all{it in setOf("platform","architecture","androidVersionCode")})
            val role=a["role"] as? String ?: error("Asset role required");val name=a["filename"] as? String ?: error("Asset name required")
            val size=a["size"] as? Long ?: error("Exact asset size required");val sha=a["sha256"] as? String ?: error("Asset hash required")
            require(role in required+setOf("desktop-windows-setup","source-sbom","release-acceptance")&&roles.add(role)&&names.add(name)&&Regex("[A-Za-z0-9][A-Za-z0-9._-]{0,159}").matches(name)&&size in 1..Int.MAX_VALUE.toLong()&&Regex("[0-9a-f]{64}").matches(sha))
            require((a["componentVersion"] as? String)?.let{semver.matches(it)}==true)
            val expectedVersion=when {
                role=="firmware-common"||role=="zigbee-ota"->components["firmware"]
                role=="android-apk"->components["android"]
                role.startsWith("desktop-")->components["desktop"]
                role=="zigbee2mqtt-converter"->components["zigbee2mqtt"]
                else->v
            }
            require(a["componentVersion"]==expectedVersion){"Artifact component version mismatch: $role"}
            if(role=="android-apk")require((a["androidVersionCode"] as? Long) in 1L..Int.MAX_VALUE.toLong()) else require("androidVersionCode" !in a)
            if(role.startsWith("desktop-")) {
                val parts=role.split('-');require(a["platform"]==parts[1]&&a["architecture"]==if(parts[2]=="setup")"x64" else parts[2])
            } else require("platform" !in a&&"architecture" !in a)
            Asset(role,name,size.toInt(),sha,a["componentVersion"] as String)
        }
        require(roles.containsAll(required))
        val firmware=assets.single{it.role=="firmware-common"};val ota=assets.single{it.role=="zigbee-ota"}
        val experimental=roles.contains("release-acceptance")
        require(firmware.size<=PackageReader.MAX_ZIP)
        if(experimental) {
            require(firmware.filename=="vomar-firmware-$v-qualification-candidate.zip"&&ota.filename=="vomar-firmware-$v-qualification-candidate.ota")
            require(assets.single{it.role=="release-acceptance"}.filename=="vomar-release-acceptance-$v.json")
        } else require(firmware.filename=="vomar-firmware-$v.zip")
        return Selection(tag,firmware,ota,assets,experimental)
    }
}
