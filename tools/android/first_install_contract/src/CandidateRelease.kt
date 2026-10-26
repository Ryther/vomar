package org.openvimar.installer

import java.security.PublicKey
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

/** A signed unqualified candidate is deliberately not a VerifiedCommonSet and
 * cannot be bound to fleet OTA. It exposes inspection metadata, not executables. */
class InspectedCommonCandidate internal constructor(private val images:VerifiedCommonSet,qualification:ByteArray) {
    private val pendingReport=qualification.copyOf()
    val releaseSha256 get()=images.releaseSha256
    val familySha256 get()=images.familySha256
    val watchdogHandoff get()=images.watchdogHandoff
    fun authorizeWatchdogHandoff(target:TargetIdentity,generation:Long)=images.authorizeWatchdogHandoff(target,generation)
    fun descriptor()=images.descriptor()
    fun qualification()=pendingReport.copyOf()
    /** Read-only review fingerprint; never returns an executable plan. */
    fun previewBinding(original:OriginalMaterial):InstallBinding=InstallPlan.prepare(original,images).binding
    /** Call only as the result of fresh explicit owner review for ONE live
     * bench target. Never persist/serialize/recreate this grant on restoration. */
    fun reviewOneBench(target:TargetIdentity,requestId:String,generation:Long,reviewedReleaseSha256:String):SingleBenchPermit {
        require(reviewedReleaseSha256==releaseSha256&&generation>0&&UUID.fromString(requestId).toString()==requestId)
        require(target.part==0x52840L&&target.variant in 1..0xfffffffeL&&target.uid0 in 0..0xffffffffL&&target.uid1 in 0..0xffffffffL&&
            target.flashSize==0x100000&&target.pageSize==4096&&target.ramSize==0x40000&&target.uicrSize==4096)
        return SingleBenchPermit.create(releaseSha256,target,requestId,generation)
    }
    fun preparePlan(original:OriginalMaterial,permit:SingleBenchPermit,requestId:String,generation:Long):InstallPlan {
        permit.consume(releaseSha256,original.identity,requestId,generation)
        return InstallPlan.prepareBench(original,images,generation)
    }
}

class SingleBenchPermit private constructor(private val candidate:String,private val target:TargetIdentity,
    private val request:String,private val generation:Long):AutoCloseable {
    private val available=AtomicBoolean(true)
    internal fun consume(candidate:String,target:TargetIdentity,request:String,generation:Long){
        require(this.candidate==candidate&&this.target==target&&this.request==request&&this.generation==generation){"Single-bench approval binding changed"}
        check(available.compareAndSet(true,false)){"Single-bench approval consumed or revoked"}
    }
    override fun close(){available.set(false)}
    internal companion object {
        fun create(candidate:String,target:TargetIdentity,request:String,generation:Long)=SingleBenchPermit(candidate,target,request,generation)
    }
}

object CandidateRelease {
    /** Manual single-device admission; never returns qualified fleet authority. */
    fun inspectLocal(raw:ByteArray,publicKey:PublicKey,appVersion:String):InspectedCommonCandidate {
        val result=CommonRelease.inspectLocal(raw,publicKey,appVersion)
        return InspectedCommonCandidate(result.first,result.second)
    }
    fun inspect(raw:ByteArray,publicKey:PublicKey,appVersion:String):InspectedCommonCandidate {
        val verified=CommonRelease.inspectCandidate(raw,publicKey,appVersion)
        return InspectedCommonCandidate(verified.first,verified.second)
    }
}
