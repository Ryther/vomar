package org.openvimar.updater

import java.io.*
import java.nio.file.Files
import java.nio.file.StandardCopyOption

/** Bounded metadata codec; no Java deserialization, firmware bytes, or credentials. */
internal class FileFleetQueuePersistence(private val file:File):FleetQueuePersistence {
    companion object {private const val MAX=4*1024*1024}
    @Synchronized override fun load():List<FleetGroup> {
        if(!file.exists())return emptyList()
        require(file.length() in 1..MAX.toLong()){"Invalid queue storage size"}
        val input=DataInputStream(ByteArrayInputStream(file.readBytes().also{require(it.size<=MAX)}))
        val format=input.readUTF();require(format in setOf("openvimar-fleet-1","openvimar-fleet-2","openvimar-fleet-3"))
        val groups=List(input.count(500)) {
            val id=input.text(128);val digest=input.text(64);val version=input.text(128);val main=input.text(64);val path=input.text(4096);val schema=input.readInt()
            require(schema in 1..3&&Regex("[0-9a-f]{64}").matches(digest)&&Regex("[0-9a-f]{64}").matches(main))
            val ota=if(input.readBoolean())ZigbeeOtaReference(input.readInt(),input.readInt(),input.readLong(),input.text(64),input.readLong(),input.text(64),input.readInt(),input.text(4096)) else null
            val target=if(format=="openvimar-fleet-3")input.optional(64) else null
            val release=FleetReleaseRef(digest,version,main,path,schema,ota,target)
            val mode=FleetMode.valueOf(input.text(32));val at=input.readLong();val paused=input.readBoolean();val cancelled=input.readBoolean()
            val jobs=List(input.count(100)) {
                val jobId=input.text(128);val device=input.device();val route=FleetRoute.valueOf(input.text(32));val state=FleetJobState.valueOf(input.text(32))
                val nearby=input.readBoolean();val progress=input.readInt().let{if(it==-1)null else it.also{require(it in 0..100)}}
                FleetJob(jobId,device,route,state,nearby,progress,input.text(1024),input.readBoolean(),if(format!="openvimar-fleet-1")input.readBoolean() else false)
            }
            require(jobs.map{it.id}.distinct().size==jobs.size)
            FleetGroup(id,release,jobs,mode,at,paused,cancelled)
        }
        require(input.available()==0&&groups.map{it.id}.distinct().size==groups.size)
        require(groups.flatMap{it.jobs}.map{it.id}.distinct().size==groups.sumOf{it.jobs.size})
        return groups
    }
    @Synchronized override fun save(groups:List<FleetGroup>) {
        require(groups.size<=500)
        val bytes=ByteArrayOutputStream().also{buffer->DataOutputStream(buffer).use{out->
            out.writeUTF("openvimar-fleet-3");out.writeInt(groups.size)
            groups.forEach{g->
                val r=g.release
                listOf(g.id,r.digest,r.version,r.mainHash,r.cachePath).forEach(out::writeUTF);out.writeInt(r.schemaVersion)
                out.writeBoolean(r.zigbeeOta!=null);r.zigbeeOta?.let{o->out.writeInt(o.manufacturerCode);out.writeInt(o.imageType);out.writeLong(o.fileVersion)
                    out.writeUTF(o.sha256);out.writeLong(o.size);out.writeUTF(o.model);out.writeInt(o.profile);out.writeUTF(o.source)}
                out.writeUTF(r.targetRecoveryHash ?: "")
                out.writeUTF(g.mode.name);out.writeLong(g.createdAt);out.writeBoolean(g.paused);out.writeBoolean(g.cancelled)
                require(g.jobs.size<=100);out.writeInt(g.jobs.size)
                g.jobs.forEach{j->out.writeUTF(j.id);out.device(j.device);out.writeUTF(j.route.name);out.writeUTF(j.state.name)
                    out.writeBoolean(j.nearbyReady);out.writeInt(j.progress ?: -1);out.writeUTF(j.message);out.writeBoolean(j.resumeRequested);out.writeBoolean(j.remoteSubmissionMayHaveStarted)}
            }
        }}.toByteArray();require(bytes.size<=MAX)
        file.parentFile?.mkdirs();val temp=File(file.parentFile,file.name+".tmp")
        try {
            FileOutputStream(temp).use{it.write(bytes);it.fd.sync()}
            // Validate exactly what will be published before replacing prior state.
            FileFleetQueuePersistence(temp).load()
            Files.move(temp.toPath(),file.toPath(),StandardCopyOption.REPLACE_EXISTING,StandardCopyOption.ATOMIC_MOVE)
        } finally {temp.delete()}
    }
    private fun DataInputStream.count(max:Int)=readInt().also{require(it in 0..max)}
    private fun DataInputStream.text(max:Int)=readUTF().also{require(it.length<=max)}
    private fun DataInputStream.optional(max:Int)=text(max).takeIf{it.isNotEmpty()}
    private fun DataInputStream.device():DeviceRecord {
        val id=text(256);val name=text(256);val room=text(256);val address=optional(64);val uid=List(count(2)){text(8)}
        val network=optional(128);val ieee=optional(64);val version=optional(128);val kind=FirmwareKind.valueOf(text(32))
        val capabilities=List(count(32)){text(64)}.toSet();val observed=readLong().let{if(it==-1L)null else it};val source=optional(256)
        return DeviceRecord(id,name,room,address,uid,network,ieee,version,kind,capabilities,observed,source)
    }
    private fun DataOutputStream.device(d:DeviceRecord) {
        listOf(d.id,d.name,d.room,d.address ?: "").forEach(::writeUTF);writeInt(d.uid.size);d.uid.forEach(::writeUTF)
        listOf(d.networkId ?: "",d.ieee ?: "",d.installedVersion ?: "",d.firmwareKind.name).forEach(::writeUTF)
        writeInt(d.capabilities.size);d.capabilities.sorted().forEach(::writeUTF);writeLong(d.observedAt ?: -1);writeUTF(d.observationSource ?: "")
    }
}
