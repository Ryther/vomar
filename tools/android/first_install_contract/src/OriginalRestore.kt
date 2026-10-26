package org.openvimar.installer

import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

/** One live USB generation, exact private original and explicit owner review.
 * This is FLASH-only authority; it cannot start a CPU or write UICR. */
class OriginalRestorePlan private constructor(internal val original:VerifiedOriginal,val requestId:String,val generation:Long) {
    private val available=AtomicBoolean(true)
    val binding:InstallBinding
    val ficrSha256=sha256(original.ficr())
    val uicrSha256=sha256(original.uicr())
    init {
        val digest=sha256(original.flash());val restore=sha256("original-restore-v1:$requestId".toByteArray())
        binding=InstallBinding(original.identity,original.archiveSha256,restore,restore,digest,digest,digest,digest)
    }
    internal fun claim(){check(available.compareAndSet(true,false)){"Restore approval already consumed"}}
    fun requireBinding(binding:InstallBinding,generation:Long){require(this.binding==binding&&this.generation==generation){"Original restore binding changed"}}
    companion object {
        fun review(original:VerifiedOriginal,requestId:String,generation:Long):OriginalRestorePlan {
            require(UUID.fromString(requestId).toString()==requestId&&generation>0)
            return OriginalRestorePlan(original,requestId,generation)
        }
    }
}

/** Page zero is restored last. Every erase/program has a durable intent and
 * exact readback. Failure leaves the target halted; retries need fresh review. */
class OriginalRestoreEngine {
    fun run(plan:OriginalRestorePlan,authorizer:SwdAuthorizer,journal:InstallJournalStore,
        onProgress:(Int,Int)->Unit={_,_->},checkCancelled:()->Unit={}):InstallOutcome {
        var session:AuthorizedSwdSession?=null;var sequence=0;var mutated=false;var owns=false;var journalFailed=false
        var phase=InstallPhase.PREPARED;var address:Int?=null
        fun record(next:InstallPhase,at:Int?=null){phase=next;address=at;try{journal.save(InstallJournalRecord(plan.binding,++sequence,next,at,mutated,false))}catch(e:Exception){journalFailed=true;throw e}}
        try {
            plan.claim();checkCancelled()
            require(journal.load(plan.binding.id)==null){"Restore transaction already exists"}
            owns=journal.begin(InstallJournalRecord(plan.binding,++sequence,phase,null,false,false));require(owns)
            val s=authorizer.acquire(plan.binding);session=s;plan.requireBinding(s.binding,s.generation)
            fun guard(){checkCancelled();s.check(plan.generation,plan.binding.target);require(s.readIdentity()==plan.binding.target);checkCancelled()}
            fun protected(){guard();require(sha256(s.readFicr())==plan.ficrSha256&&sha256(s.readUicr())==plan.uicrSha256){"Backup UID/FICR/UICR does not match this device"};guard()}
            protected();val flash=plan.original.flash();var done=0
            val pages=(4096 until AnchorV1.FLASH step 4096).toList()+0
            for(at in pages){
                protected();val wanted=flash.copyOfRange(at,at+4096)
                require(s.readFlash(at,4096).size==4096)
                mutated=true;record(InstallPhase.PAGE_ERASE_INTENT,at);guard();s.erasePage(at,plan.generation)
                for(offset in 0 until 4096 step 256){val data=wanted.copyOfRange(offset,offset+256);if(data.all{it==0xff.toByte()})continue
                    record(InstallPhase.PAGE_WRITE_INTENT,at+offset);guard();s.program(at+offset,data,plan.generation)}
                guard();require(s.readFlash(at,4096).contentEquals(wanted)){"Restored page differs from original"}
                done+=4096;onProgress(done,2*AnchorV1.FLASH)
            }
            record(InstallPhase.FINAL_VERIFY)
            val hash=java.security.MessageDigest.getInstance("SHA-256")
            for(at in 0 until AnchorV1.FLASH step 4096){guard();val bytes=s.readFlash(at,4096);require(bytes.contentEquals(flash.copyOfRange(at,at+4096)));hash.update(bytes);done+=4096;onProgress(done,2*AnchorV1.FLASH)}
            require(hash.digest().joinToString(""){"%02x".format(it.toInt() and 255)}==plan.binding.installedSha256)
            protected();record(InstallPhase.VERIFIED);s.close();session=null
            return InstallOutcome(true,phase,null,true,false,false,"Original FLASH verified. Disconnect the DK and power-cycle the dimmer to start it.")
        }catch(e:Exception){
            if(owns)try{journal.save(InstallJournalRecord(plan.binding,++sequence,InstallPhase.FAILED,address,mutated,false,phase,(e.message?:"Restore failed").take(1024)))}catch(_:Exception){journalFailed=true}
            return InstallOutcome(false,phase,address,mutated,false,journalFailed,e.message?:"Original restore failed")
        }finally{runCatching{session?.close()}}
    }
}
