package org.openvimar.installer.resume

import org.openvimar.installer.*
import java.security.MessageDigest
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

/** A fresh, nonserializable review, not an automatic continuation of the old
 * journal. The candidate's original single-bench generation remains binding. */
class ReviewedResume private constructor(internal val plan:InstallPlan,internal val original:ReopenedResumeOriginal,
    internal val journal:FileResumeJournal,internal val checkpoint:ResumeCheckpoint,val requestId:String,val generation:Long){
    private val available=AtomicBoolean(true)
    val binding get()=plan.binding
    val journalHeadSha256 get()=checkpoint.headSha256
    val frontierPage get()=checkpoint.frontierPage
    val commitPossible get()=checkpoint.commitPossible
    internal fun claim(){check(available.compareAndSet(true,false)){"Resume review is single-attempt"};plan.claim()}
    fun hardwareAuthority():ResumeHardwareAuthority=ResumeHardwareAuthority.create(this)
    companion object {
        fun review(plan:InstallPlan,original:ReopenedResumeOriginal,journal:FileResumeJournal,expectedHeadSha256:String,
            requestId:String,generation:Long):ReviewedResume{
            require(UUID.fromString(requestId).toString()==requestId&&generation>0)
            require(plan.requiredGeneration==null||plan.requiredGeneration==generation){"Candidate bench review belongs to another lease"}
            val binding=plan.binding;val material=original.material
            require(original.initialReceipt.bindingId==binding.id&&original.initialReceipt.archiveSha256==binding.archiveSha256&&material.identity==binding.target&&
                material.archiveSha256==binding.archiveSha256&&sha256(material.anchor())==binding.anchorSha256&&sha256(material.table())==binding.tableSha256){"Resume plan differs from the initially exported protected original"}
            val head=journal.inspect(binding,original.initialReceipt)
            require(head.headSha256==expectedHeadSha256){"Recovery journal changed; repeat explicit review"}
            return ReviewedResume(plan,original,journal,head,requestId,generation)
        }
    }
}

/** Only this reviewed, same-original path can authorize restoring NVMC CONFIG
 * to READONLY after READY+HALT. It grants no FLASH/UICR write or CPU release. */
class ResumeHardwareAuthority private constructor(val binding:InstallBinding,val generation:Long,val ficrSha256:String,val uicrSha256:String){
    fun requireBinding(binding:InstallBinding,generation:Long){require(this.binding==binding&&this.generation==generation){"Resume hardware authority belongs to another binding/lease"}}
    internal companion object {fun create(review:ReviewedResume)=ResumeHardwareAuthority(review.binding,review.generation,
        review.original.material.ficrSha256,review.original.material.uicrSha256)}
}
enum class ResumeMode {REBUILD,COMMIT_ONLY,VERIFY_ONLY}
data class ResumeResult(val outcome:InstallOutcome,val mode:ResumeMode?,val journalHeadSha256:String?)

/** No resume without an existing readable base journal, immutable export
 * receipt, exact reopened original, fresh signed plan, and new owner review.
 * Unissued pages must remain original. Prior mutation always retains HALT. */
class ExplicitResumeEngine {
    private val busy=AtomicBoolean(false)
    fun run(review:ReviewedResume,authorizer:SwdAuthorizer,checkCancelled:()->Unit={}):ResumeResult {
        check(busy.compareAndSet(false,true)){"A resume is already active"}
        val plan=review.plan;val binding=plan.binding;val material=review.original.material
        var session:FileResumeJournal.Session?=null;var lease:AuthorizedSwdSession?=null
        var mode:ResumeMode?=null;var phase=InstallPhase.PREPARED;var address:Int?=null
        var frontier=review.frontierPage;var commit=review.commitPossible;var journalFailure=false
        val inheritedMutation=frontier>=0;var mutated=inheritedMutation
        fun intent(next:ResumePhase,at:Int?=null,high:Int=frontier,committed:Boolean=commit,message:String=""){
            try{checkNotNull(session).append(next,at,high,committed,message);frontier=high;commit=committed}
            catch(error:Exception){journalFailure=true;throw error}
        }
        try{
            try{review.claim();session=review.journal.acquire(binding,review.original.initialReceipt,review.journalHeadSha256,review.requestId,review.generation,review.original.selectedDocument)}
            catch(error:Exception){
                // The reviewed head may now be stale or unreadable after a
                // newer attempt. Never report the old no-write flags as safe.
                mutated=true;commit=true;journalFailure=true;throw error
            }
            intent(ResumePhase.REVIEWED);checkCancelled()
            val s=authorizer.acquire(binding);lease=s
            require(s.binding==binding&&s.generation==review.generation){"Resume authorization or live generation changed"}
            val generation=s.generation;val expected=binding.target
            fun active(){checkCancelled();s.check(generation,expected);checkCancelled()}
            fun identity(){active();require(s.readIdentity()==expected){"Resume target identity/geometry changed"};active()}
            fun protected(){identity();require(s.readUicr().contentEquals(material.original.uicr())){"UICR differs from protected original"};active()}
            fun page(at:Int):ByteArray{active();val bytes=s.readFlash(at,4096).copyOf();require(bytes.size==4096);active();return bytes}
            phase=InstallPhase.ORIGINAL_VERIFY;intent(ResumePhase.VALIDATING);protected()
            require(s.readFicr().contentEquals(material.original.ficr())){"FICR differs from protected original"};active()
            val old=material.original.flash();var bodyMatches=true;var finalMatches=true
            for(at in 0 until AnchorV1.FLASH step 4096){
                val bytes=page(at)
                if(at>frontier)require(bytes.contentEquals(old.copyOfRange(at,at+4096))){"Unissued FLASH page differs from the protected original; automatic repair denied"}
                bodyMatches=bodyMatches&&bytes.contentEquals(plan.page(at,false))
                finalMatches=finalMatches&&bytes.contentEquals(plan.page(at,true))
            }
            protected();mode=if(finalMatches)ResumeMode.VERIFY_ONLY else if(bodyMatches)ResumeMode.COMMIT_ONLY else ResumeMode.REBUILD
            if(mode==ResumeMode.REBUILD){
                for(at in 0 until AnchorV1.FLASH step 4096){
                    protected();val wanted=plan.page(at,false);phase=InstallPhase.PAGE_ERASE_INTENT;address=at;mutated=true
                    intent(ResumePhase.ERASE_INTENT,at,maxOf(frontier,at));active();s.erasePage(at,generation)
                    for(offset in 0 until 4096 step 256){val batch=wanted.copyOfRange(offset,offset+256);if(batch.all{it==0xff.toByte()})continue
                        phase=InstallPhase.PAGE_WRITE_INTENT;address=at+offset;intent(ResumePhase.WRITE_INTENT,address);active();s.program(at+offset,batch,generation)}
                    require(page(at).contentEquals(wanted)){"Rebuilt page readback mismatch"};identity()
                }
            }
            fun verify(committed:Boolean,hash:String){val digest=MessageDigest.getInstance("SHA-256")
                for(at in 0 until AnchorV1.FLASH step 4096){val bytes=page(at);require(bytes.contentEquals(plan.page(at,committed))){"Complete resumed FLASH readback mismatch"};digest.update(bytes)}
                require(digest.digest().joinToString(""){"%02x".format(it.toInt() and 255)}==hash)}
            if(mode!=ResumeMode.VERIFY_ONLY){
                phase=InstallPhase.BODY_VERIFY;address=null;verify(false,binding.bodySha256);protected();intent(ResumePhase.BODY_VERIFIED)
                protected();phase=InstallPhase.COMMIT_INTENT;address=0xb0fc;mutated=true
                intent(ResumePhase.COMMIT_INTENT,0xb0fc,frontier,true);active()
                val word=ByteArray(4);putWord(word,0,AnchorV1.COMMIT);s.program(0xb0fc,word,generation)
            }else {
                verify(true,binding.installedSha256);protected()
                intent(ResumePhase.COMPLETE_IMAGE_VERIFIED,committed=true)
            }
            protected();phase=InstallPhase.FINAL_VERIFY;address=null;intent(ResumePhase.FINAL_VERIFY)
            verify(true,binding.installedSha256);protected();s.close();lease=null
            intent(ResumePhase.VERIFIED);phase=InstallPhase.VERIFIED
            val head=session?.checkpoint?.headSha256;session?.close();session=null
            return ResumeResult(InstallOutcome(true,phase,null,true,true,false,"Complete known FLASH verified; target remains halted for a separate explicit start; hardware unqualified"),mode,head)
        }catch(error:Exception){
            val message=(error.message?:error.javaClass.simpleName).take(1024)
            try{session?.append(ResumePhase.FAILED,null,frontier,commit,message)}catch(_:Exception){journalFailure=true}
            return ResumeResult(InstallOutcome(false,phase,address,mutated,commit,journalFailure,message),mode,session?.checkpoint?.headSha256)
        }finally{
            try{lease?.close()}catch(_:Exception){};try{session?.close()}catch(_:Exception){};busy.set(false)
        }
    }
}
