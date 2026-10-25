package org.openvimar.updater

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.IOException

internal enum class DkBackupPhase { PREPARING, USB_OPEN, USB_PROBE, SWD_INITIALIZATION, TARGET_IDENTITY, ACQUIRING, VERIFYING, PUBLISHING, COMPLETE }

/** Metadata only. This object never receives acquired region bytes or archive contents. */
internal data class DkBackupDiagnostic(val requestId: String,val phase: DkBackupPhase=DkBackupPhase.PREPARING,
    val message: String="Preparing a read-only double backup",val progress: DkBackupProgress?=null,
    val observations: Map<String,Any> = emptyMap(),val running: Boolean=true,
    val outcome: String="RUNNING",val error: String?=null,val errorType: String?=null) {
    /** Explicit bounded metadata codec, without Java object deserialization. */
    fun encode(): ByteArray=ByteArrayOutputStream().also {bytes->DataOutputStream(bytes).use {out->
        out.writeUTF("dk-backup-diagnostic-1")
        for(value in listOf(requestId,phase.name,message,outcome,error ?: "",errorType ?: ""))out.writeUTF(value)
        out.writeBoolean(running);out.writeBoolean(progress!=null)
        progress?.let {out.writeInt(it.pass);out.writeUTF(it.region.name);out.writeLong(it.completedBytes);out.writeLong(it.totalBytes)}
        require(observations.size<=64);out.writeInt(observations.size)
        for((key,value) in observations) {
            out.writeUTF(key)
            when(value) {
                is String->{out.writeByte(1);out.writeUTF(value)}
                is Long->{out.writeByte(2);out.writeLong(value)}
                is Int->{out.writeByte(3);out.writeInt(value)}
                is Boolean->{out.writeByte(4);out.writeBoolean(value)}
                is List<*>->{require(value.size<=16&&value.all {it is String});out.writeByte(5);out.writeInt(value.size);value.forEach {out.writeUTF(it as String)}}
                else->throw IOException("Unsupported diagnostic metadata")
            }
        }
    }}.toByteArray().also {require(it.size<=65536)}
    companion object {
        fun restore(bytes: ByteArray): DkBackupDiagnostic {
            require(bytes.size in 1..65536)
            val input=DataInputStream(ByteArrayInputStream(bytes))
            require(input.readUTF()=="dk-backup-diagnostic-1")
            val request=input.readUTF();require(request.isNotBlank()&&request.length<=128)
            val phase=DkBackupPhase.valueOf(input.readUTF());val message=input.readUTF();val outcome=input.readUTF()
            val error=input.readUTF().takeIf {it.isNotEmpty()};val errorType=input.readUTF().takeIf {it.isNotEmpty()}
            val running=input.readBoolean()
            val progress=if(input.readBoolean())DkBackupProgress(input.readInt(),DkBackupRegion.valueOf(input.readUTF()),input.readLong(),input.readLong()) else null
            val count=input.readInt();require(count in 0..64)
            val observations=linkedMapOf<String,Any>()
            repeat(count) {
                val key=input.readUTF();require(key !in observations)
                observations[key]=when(input.readUnsignedByte()) {
                    1->input.readUTF();2->input.readLong();3->input.readInt();4->input.readBoolean()
                    5->{val length=input.readInt();require(length in 0..16);List(length){input.readUTF()}}
                    else->throw IOException("Invalid diagnostic metadata")
                }
            }
            require(input.available()==0)
            val snapshot=DkBackupDiagnostic(request,phase,message,progress,observations,running,outcome,error,errorType)
            return if(running)snapshot.failed(IOException("Backup interrupted before completion; acquisition is not resumed"),false).copy(outcome="INTERRUPTED") else snapshot
        }
    }
    fun at(phase: DkBackupPhase,message: String)=copy(phase=phase,message=message)
    fun observed(key: String,value: Any)=copy(observations=observations+(key to value))
    fun advanced(progress: DkBackupProgress)=copy(phase=DkBackupPhase.ACQUIRING,progress=progress,
        message="Reading pass ${progress.pass}/2: ${progress.region.name}")
    fun failed(error: Exception,cancelled: Boolean):DkBackupDiagnostic {
        val evidence=if(error is DkBackupChangedException) mapOf(
            "changedRegion" to error.region.name,
            "changedBlockAddress" to DkBackupChangedException.address(error.blockAddress),
            "firstChangedAddress" to DkBackupChangedException.address(error.firstChangedAddress),
            "changedBytesInBlock" to error.changedBytesInBlock,
            "firstPassBlockSha256" to error.firstPassBlockSha256,
            "secondPassBlockSha256" to error.secondPassBlockSha256) else emptyMap()
        return copy(running=false,observations=observations+evidence,
            outcome=if(cancelled) "CANCELLED" else "FAILED",
            message=if(cancelled) "Backup stopped; no partial archive is available" else error.message ?: "Backup could not complete",
            error=error.message ?: error.javaClass.simpleName,errorType=error.javaClass.name)
    }
    fun completed()=copy(phase=DkBackupPhase.COMPLETE,running=false,outcome="VERIFIED",message="Verified backup ready to save")
    fun fieldsFor(expectedRequest: String?): Map<String,Any>? {
        if(expectedRequest!=requestId)return null
        val backup=linkedMapOf<String,Any>("requestId" to requestId,"phase" to phase.name,"outcome" to outcome,
            "message" to message,"running" to running,"observations" to observations)
        progress?.let {backup["progress"]=mapOf("pass" to it.pass,"region" to it.region.name,
            "completedBytes" to it.completedBytes,"totalBytes" to it.totalBytes)}
        errorType?.let {backup["errorType"]=it}
        val fields=linkedMapOf<String,Any>("backup" to backup,
            "swdAttempted" to (observations["swdLineSynchronizationAttempted"]==true),
            "memoryReadAttempted" to (observations["ficrReadAttempted"]==true || progress!=null),
            "memoryRead" to (observations.containsKey("part") || (progress?.completedBytes ?: 0)>0))
        if(!running)fields["success"]=outcome=="VERIFIED"
        error?.let {fields["error"]=it}
        return fields
    }
}
