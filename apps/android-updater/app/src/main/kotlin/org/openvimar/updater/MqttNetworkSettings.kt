package org.openvimar.updater

import android.content.Context
import java.net.URI
import java.net.URISyntaxException
import java.util.Locale
import kotlinx.serialization.json.*

/** Address validation only; callers must separately require consent for unencrypted transports. */
internal fun normalizeBrokerUri(raw:String):String {
    val address=raw.trim()
    require(address.isNotEmpty()) { "Enter a broker host or IP address" }
    val separator=address.indexOf("://")
    val scheme=if(separator>=0)address.substring(0,separator).lowercase(Locale.ROOT) else "tcp"
    require(scheme in setOf("tcp","ssl","ws","wss")) { "Unsupported broker scheme; use tcp, ssl, ws or wss" }
    val canonical=if(separator>=0)scheme+address.substring(separator) else "tcp://$address"
    val authority=canonical.substringAfter("://").substringBefore('/').substringBefore('?').substringBefore('#')
    require('@' !in authority) { "Remove embedded credentials; use the separate username and password fields" }
    require('?' !in canonical) { "Broker address cannot contain a query" }
    require('#' !in canonical) { "Broker address cannot contain a fragment" }

    val port:String?
    if(authority.startsWith('[')) {
        val closing=authority.indexOf(']')
        require(closing>1) { "Enter a valid broker host; put IPv6 addresses in brackets" }
        val suffix=authority.substring(closing+1)
        require(suffix.isEmpty() || (suffix.startsWith(':') && suffix.count { it==':' }==1)) { "Enter a valid broker host and port" }
        port=if(suffix.isEmpty())null else suffix.substring(1)
    } else {
        require(authority.count { it==':' }<=1) { "Enter a valid broker host; put IPv6 addresses in brackets" }
        port=if(':' in authority)authority.substringAfter(':') else null
    }
    require(port==null || (port.isNotEmpty() && port.all { it in '0'..'9' } && port.toIntOrNull() in 1..65535)) { "Broker port must be a number from 1 to 65535" }
    val uri=try { URI(canonical) } catch(_:URISyntaxException) {
        // URI exceptions include the supplied address, which can contain secrets.
        throw IllegalArgumentException("Invalid broker address syntax; check the host and path")
    }
    require(!uri.host.isNullOrBlank()) { "Enter a valid broker host or IP address; put IPv6 addresses in brackets" }
    require(scheme in setOf("ws","wss") || uri.rawPath.isNullOrEmpty()) { "TCP and SSL broker addresses cannot have a path" }
    return canonical
}

internal data class ZigbeeNetwork(val id:String,val label:String,val baseTopic:String)
internal enum class BrokerValidationField { BROKER, NETWORK_NAME, BASE_TOPIC, CONSENT, NETWORKS }
internal data class BrokerValidationIssue(val field:BrokerValidationField,val message:String,val networkId:String?=null)

/** Nonthrowing field feedback; messages never echo supplied addresses, names or topics. */
internal fun BrokerProfile.validationIssues():List<BrokerValidationIssue> {
    val issues=mutableListOf<BrokerValidationIssue>()
    if(!id.matches(Regex("[A-Za-z0-9_-]{1,64}")))issues+=BrokerValidationIssue(BrokerValidationField.BROKER,"Invalid broker profile ID")
    if(label.isBlank() || label.length>128)issues+=BrokerValidationIssue(BrokerValidationField.BROKER,"Enter a connection name of 1 to 128 characters")
    val canonical=try { normalizeBrokerUri(serverUri) } catch(e:IllegalArgumentException) {
        // normalizeBrokerUri creates only fixed, sanitized messages with no raw URI cause.
        issues+=BrokerValidationIssue(BrokerValidationField.BROKER,e.message ?: "Enter a valid broker host or IP address")
        null
    }
    if(canonical!=null && URI(canonical).scheme !in setOf("ssl","wss") && !allowInsecureLocal) {
        issues+=BrokerValidationIssue(BrokerValidationField.CONSENT,"Unencrypted broker connections require explicit local-network consent")
    }
    // Reject excess rows and inspect only the supported maximum, even for malformed stored profiles.
    val rows=networks.take(3)
    if(networks.size !in 1..3 || rows.map { it.id }.distinct().size!=rows.size) {
        issues+=BrokerValidationIssue(BrokerValidationField.NETWORKS,"Configure one to three distinct topics")
    }
    rows.forEach { network ->
        if(!network.id.matches(Regex("[A-Za-z0-9_-]{1,64}")))issues+=BrokerValidationIssue(BrokerValidationField.NETWORKS,"Each topic needs a valid, distinct ID",network.id)
        if(network.label.isBlank())issues+=BrokerValidationIssue(BrokerValidationField.NETWORK_NAME,"Enter a topic name",network.id)
        else if(network.label.length>128)issues+=BrokerValidationIssue(BrokerValidationField.NETWORK_NAME,"Topic name must be 128 characters or fewer",network.id)
        val topic=network.baseTopic
        val topicMessage=when {
            topic.isBlank() -> "Enter an MQTT base topic"
            topic.length>256 -> "MQTT base topic must be 256 characters or fewer"
            topic.split('/').any { it.isBlank() } -> "Use a base topic without empty path segments"
            topic.any { it=='+' || it=='#' || it=='\u0000' || it.isISOControl() } -> "Use an exact MQTT base topic without wildcards or control characters"
            else -> null
        }
        if(topicMessage!=null)issues+=BrokerValidationIssue(BrokerValidationField.BASE_TOPIC,topicMessage,network.id)
    }
    for(i in rows.indices)for(j in i+1 until rows.size) {
        val a=rows[i];val b=rows[j]
        if(a.id!=b.id && (a.baseTopic==b.baseTopic || a.baseTopic.startsWith(b.baseTopic+"/") || b.baseTopic.startsWith(a.baseTopic+"/"))) {
            listOf(a,b).forEach { issues+=BrokerValidationIssue(BrokerValidationField.BASE_TOPIC,"Topic base topics cannot overlap",it.id) }
        }
    }
    if(rows.map { it.label.trim().lowercase(Locale.ROOT) }.distinct().size!=rows.size)
        issues+=BrokerValidationIssue(BrokerValidationField.NETWORK_NAME,"Choose a different topic name")
    return issues.distinct()
}

internal data class BrokerProfile(val id:String,val serverUri:String,val networks:List<ZigbeeNetwork>,val allowInsecureLocal:Boolean=false,val label:String=id.replaceFirstChar { it.uppercase() }) {
    fun validated():BrokerProfile {
        val issues=validationIssues()
        require(issues.isEmpty()) { issues.first().message }
        return copy(serverUri=normalizeBrokerUri(serverUri))
    }
}

/** Metadata and encrypted credentials share one atomic preferences transaction.
 * The legacy single-profile entry is read without rewriting IDs or secrets. */
internal class BrokerProfileStore(context:Context) {
    private val preferences=context.applicationContext.getSharedPreferences("mqtt-secrets-v1",Context.MODE_PRIVATE)
    private val legacy=context.applicationContext.getSharedPreferences("mqtt-profile-v1",Context.MODE_PRIVATE)
    @Synchronized fun loadAll():List<BrokerProfile> = preferences.getString("catalog.v2",null)?.let(::decodeCatalog)
        ?: legacy.getString("profile",null)?.let { listOf(decode(it)) }.orEmpty()
    fun load():BrokerProfile?=loadAll().firstOrNull()
    @Synchronized fun save(profile:BrokerProfile)=save(profile,null,false)
    @Synchronized fun save(profile:BrokerProfile,encryptedCredentials:String?,replaceCredentials:Boolean) {
        val current=loadAll();val all=replaceInCatalog(current,profile)
        val edit=preferences.edit().putString("catalog.v2",encodeCatalog(all))
        if(replaceCredentials) {if(encryptedCredentials==null)edit.remove(profile.id) else edit.putString(profile.id,encryptedCredentials)}
        check(edit.commit()) { "Unable to save connection. Check the saved settings before retrying." }
        legacy.edit().remove("profile").commit()
    }
    @Synchronized fun remove(id:String) {
        val all=loadAll().filterNot { it.id==id }
        check(preferences.edit().putString("catalog.v2",encodeCatalog(all)).remove(id).commit()) { "Unable to remove connection" }
        legacy.edit().remove("profile").commit()
    }
    companion object {
        fun replaceInCatalog(current:List<BrokerProfile>,profile:BrokerProfile):List<BrokerProfile> {
            val canonical=profile.validated()
            val previous=current.firstOrNull { it.id==canonical.id }
            previous?.networks?.forEach { old ->
                canonical.networks.firstOrNull { it.id==old.id }?.let { next ->
                    require(previous.validated().serverUri==canonical.serverUri && old.baseTopic==next.baseTopic) { "Changed broker or base topic requires a new topic identity" }
                }
            }
            val all=current.filterNot { it.id==canonical.id }+canonical
            require(all.map { it.label.lowercase(Locale.ROOT) }.distinct().size==all.size) { "Choose a different connection name" }
            val ids=all.flatMap { it.networks }.map { it.id }
            require(ids.distinct().size==ids.size) { "Topics must have distinct saved identities across connections" }
            return current.map { if(it.id==canonical.id)canonical else it }+listOfNotNull(canonical.takeIf { p->current.none { it.id==p.id } })
        }
        fun encodeCatalog(profiles:List<BrokerProfile>):String = buildJsonArray { profiles.forEach { add(Json.parseToJsonElement(encode(it))) } }.toString().also { require(it.length<=1024*1024) { "Saved connections exceed storage limit" } }
        fun decodeCatalog(value:String):List<BrokerProfile> {
            require(value.length<=1024*1024) { "Saved connections exceed storage limit" }
            val all=Json.parseToJsonElement(value).jsonArray.map { decode(it.toString()) }
            require(all.map { it.id }.distinct().size==all.size) { "Duplicate saved connection" }
            var checked=emptyList<BrokerProfile>();all.forEach { checked=replaceInCatalog(checked,it) };return checked
        }
        fun encode(profile:BrokerProfile):String {
            val canonical=profile.validated()
            return buildJsonObject {
                put("id",canonical.id);put("label",canonical.label);put("serverUri",canonical.serverUri);put("allowInsecureLocal",canonical.allowInsecureLocal)
                put("networks",buildJsonArray { canonical.networks.forEach { n -> add(buildJsonObject { put("id",n.id);put("label",n.label);put("baseTopic",n.baseTopic) }) } })
            }.toString()
        }
        fun decode(value:String):BrokerProfile {
            require(value.length<=16384)
            val root=Json.parseToJsonElement(value).jsonObject
            val id=root.getValue("id").jsonPrimitive.content
            val used=mutableSetOf<String>()
            val networks=root.getValue("networks").jsonArray.map { it.jsonObject.let { n ->
                var name=n.getValue("label").jsonPrimitive.content
                if(root["label"]==null){val original=name;var suffix=2;while(name.lowercase(Locale.ROOT) in used){val ending=" (${suffix++})";name=original.take(128-ending.length)+ending}}
                used.add(name.lowercase(Locale.ROOT))
                ZigbeeNetwork(n.getValue("id").jsonPrimitive.content,name,n.getValue("baseTopic").jsonPrimitive.content)
            } }
            return BrokerProfile(id,root.getValue("serverUri").jsonPrimitive.content,networks,
                root["allowInsecureLocal"]?.jsonPrimitive?.boolean ?: false,
                root["label"]?.jsonPrimitive?.content ?: id.replaceFirstChar { it.uppercase() }).validated()
        }
    }
}

internal fun connectionTransportChanged(old:BrokerProfile?,new:BrokerProfile):Boolean = old==null ||
    old.validated().serverUri!=new.validated().serverUri || old.allowInsecureLocal!=new.allowInsecureLocal ||
    old.networks.map { it.id to it.baseTopic }!=new.networks.map { it.id to it.baseTopic }

internal fun connectionHasPendingUpdates(profile:BrokerProfile?,groups:List<FleetGroup>):Boolean {
    val ids=profile?.networks?.map { it.id }?.toSet() ?: return false
    return groups.any { group->group.jobs.any { job->job.route==FleetRoute.ZIGBEE && job.device.networkId in ids &&
        (job.state in setOf(FleetJobState.RUNNING,FleetJobState.UNCERTAIN_RESET,FleetJobState.AWAITING_RETURN) ||
            job.state==FleetJobState.QUEUED && !group.paused && !group.cancelled) } }
}
