package org.openvimar.installer

import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean

data class InstallBinding(val target:TargetIdentity,val archiveSha256:String,val releaseSha256:String,
    val familySha256:String,val anchorSha256:String,val tableSha256:String,val bodySha256:String,val installedSha256:String) {
    val id=sha256(("VIMAR30805-FIRST-INSTALL-V1\n"+listOf(target.uid0,target.uid1,target.variant,target.part,target.flashSize,target.pageSize,target.ramSize,target.uicrSize).joinToString(":")+
        "\n"+listOf(archiveSha256,releaseSha256,familySha256,anchorSha256,tableSha256,bodySha256,installedSha256).joinToString("\n")+"\n").toByteArray())
}
class InstallPlan private constructor(internal val original:OriginalMaterial,private val body:ByteArray,
    private val installed:ByteArray,val binding:InstallBinding,internal val requiredGeneration:Long?=null) {
    private val claimed=AtomicBoolean(false)
    internal fun claim(){check(claimed.compareAndSet(false,true)){"An install plan is single-attempt; automatic resume is unsupported"}}
    internal fun page(address:Int,committed:Boolean):ByteArray {
        require(address>=0&&address%4096==0&&address<=AnchorV1.FLASH-4096)
        return (if(committed)installed else body).copyOfRange(address,address+4096)
    }
    fun finalImage()=installed.copyOf()
    companion object {
        fun prepare(original:OriginalMaterial,release:VerifiedCommonSet):InstallPlan=prepare(original,release,null)
        internal fun prepareBench(original:OriginalMaterial,release:VerifiedCommonSet,generation:Long):InstallPlan=prepare(original,release,generation)
        private fun prepare(original:OriginalMaterial,release:VerifiedCommonSet,generation:Long?):InstallPlan {
            val template=release.loader();require(template.size==AnchorV1.LOADER)
            val final=ByteArray(AnchorV1.FLASH){0xff.toByte()}
            template.copyInto(final);original.anchor().copyInto(final,AnchorV1.ANCHOR)
            release.main().copyInto(final,0xc000);release.recovery().copyInto(final,0xb0000)
            val body=final.copyOf();repeat(4){body[AnchorV1.ANCHOR+AnchorV1.COMMIT_OFFSET+it]=0xff.toByte()}
            val binding=InstallBinding(original.identity,original.archiveSha256,release.releaseSha256,release.familySha256,
                sha256(original.anchor()),sha256(original.table()),sha256(body),sha256(final))
            return InstallPlan(original,body,final,binding,generation)
        }
    }
}

/** A future physical implementation must already hold explicit owner approval
 * for this exact binding and CPU-halted/quiescent exclusive ownership. It must
 * never reconnect or switch targets under the same lease. No implementation
 * capable of physical IO is supplied by this module. */
interface SwdAuthorizer {fun acquire(binding:InstallBinding):AuthorizedSwdSession}
interface AuthorizedSwdSession:AutoCloseable {
    val binding:InstallBinding
    val generation:Long
    /** Check cancellation/revocation, transport generation and fresh target UID
     * under the same driver lock as the next mutation. Only8-byte UID checking
     * is needed per batch; full UICR is checked at page boundaries by the engine. */
    fun check(expectedGeneration:Long,expectedIdentity:TargetIdentity)
    fun readIdentity():TargetIdentity
    fun readFicr():ByteArray
    fun readUicr():ByteArray
    fun readFlash(address:Int,size:Int):ByteArray
    /** Synchronous completion or exception (which may mean a partial write).
     * Implementations must enforce their generation guard again under driver
     * lock; only aligned FLASH page erases /4..256-byte word batches are legal. */
    fun erasePage(address:Int,expectedGeneration:Long)
    fun program(address:Int,data:ByteArray,expectedGeneration:Long)
    /** Release host resources only; never resume/reset/halt or mutate target. */
    override fun close()
}
enum class InstallPhase {PREPARED,ORIGINAL_VERIFY,ORIGINAL_VERIFIED,PAGE_ERASE_INTENT,PAGE_WRITE_INTENT,BODY_VERIFY,BODY_VERIFIED,COMMIT_INTENT,COMMIT_WRITTEN,FINAL_VERIFY,VERIFIED,FAILED}
data class InstallJournalRecord(val binding:InstallBinding,val sequence:Int,val phase:InstallPhase,val address:Int?,
    val mutationMayHaveStarted:Boolean,val commitMayHaveBeenWritten:Boolean,val failurePhase:InstallPhase?=null,val message:String="")
interface InstallJournalStore {
    fun load(bindingId:String):InstallJournalRecord?
    /** Atomic durable first-intent reservation. False means another/existing
     * attempt owns this binding. Never overwrite that evidence, even on error. */
    fun begin(record:InstallJournalRecord):Boolean
    /** Must durably publish exact intent before returning; failure propagates.
     * Contains hashes/identity/status only, never original memory bytes. */
    fun save(record:InstallJournalRecord)
}
data class InstallOutcome(val verified:Boolean,val stoppedAt:InstallPhase,val address:Int?,
    val mutationMayHaveStarted:Boolean,val commitMayHaveBeenWritten:Boolean,val journalFailure:Boolean,val message:String)

/** One explicitly initiated source-candidate transaction; no retry, recovery,
 * reset or UICR-writing API. All addresses below are fixed, not archive inputs. */
class FirstInstallEngine {
    private val busy=AtomicBoolean(false)
    fun run(plan:InstallPlan,authorizer:SwdAuthorizer,journal:InstallJournalStore,checkCancelled:()->Unit={}):InstallOutcome {
        check(busy.compareAndSet(false,true)){"An installation is already active"}
        var lease:AuthorizedSwdSession?=null
        var phase=InstallPhase.PREPARED;var address:Int?=null;var sequence=0
        var mutated=false;var commitAttempted=false;var journalFailure=false
        var ownsJournal=false
        fun record(next:InstallPhase,at:Int?=null) {
            checkCancelled();phase=next;address=at
            try{journal.save(InstallJournalRecord(plan.binding,++sequence,next,at,mutated,commitAttempted))}
            catch(e:Exception){journalFailure=true;throw e}
        }
        try {
            plan.claim();checkCancelled()
            val previous=try{journal.load(plan.binding.id)}catch(e:Exception){journalFailure=true;throw e}
            if(previous!=null){
                // Refusal must preserve the prior attempt's uncertainty both
                // on disk and in the result displayed by a future caller.
                phase=previous.failurePhase?:previous.phase;address=previous.address
                mutated=previous.mutationMayHaveStarted;commitAttempted=previous.commitMayHaveBeenWritten
                error("Existing transaction requires review; resume is unsupported")
            }
            val reserved=try{journal.begin(InstallJournalRecord(plan.binding,++sequence,InstallPhase.PREPARED,null,false,false))}
                catch(e:Exception){journalFailure=true;throw e}
            require(reserved){"Transaction binding already reserved; resume is unsupported"}
            ownsJournal=true
            val s=authorizer.acquire(plan.binding);lease=s
            require(s.binding==plan.binding){"Physical authorization does not match this original/release/UID"}
            val generation=s.generation;require(generation>0)
            require(plan.requiredGeneration==null||generation==plan.requiredGeneration){"Single-bench approval belongs to a different live lease"}
            val expected=plan.binding.target
            val original=plan.original.original
            val originalFlash=original.flash();val originalFicr=original.ficr();val originalUicr=original.uicr()
            fun active(){checkCancelled();s.check(generation,expected);checkCancelled()}
            fun identity(){active();require(s.readIdentity()==expected){"Live identity or geometry changed"};active()}
            fun protectedPageGuard(){identity();require(s.readUicr().contentEquals(originalUicr)){"UICR changed; no recovery/unlock permitted"};active()}
            fun readPage(at:Int):ByteArray {
                require(at>=0&&at%4096==0&&at<=AnchorV1.FLASH-4096);active()
                val data=s.readFlash(at,4096).copyOf();require(data.size==4096){"Incomplete FLASH read"};active();return data
            }
            record(InstallPhase.ORIGINAL_VERIFY)
            protectedPageGuard();require(s.readFicr().contentEquals(originalFicr)){"Live FICR differs from exported original"};active()
            for(at in 0 until AnchorV1.FLASH step 4096)require(readPage(at).contentEquals(originalFlash.copyOfRange(at,at+4096))){"Live original FLASH differs from exported backup"}
            protectedPageGuard();record(InstallPhase.ORIGINAL_VERIFIED)
            for(at in 0 until AnchorV1.FLASH step 4096) {
                // One page transaction. No4KiB UICR rereads per word/batch.
                protectedPageGuard();val wanted=plan.page(at,false)
                mutated=true;record(InstallPhase.PAGE_ERASE_INTENT,at);active()
                s.erasePage(at,generation)
                for(offset in 0 until 4096 step 256) {
                    val batch=wanted.copyOfRange(offset,offset+256)
                    if(batch.all{it==0xff.toByte()})continue
                    val destination=at+offset
                    require(destination%4==0&&destination<=AnchorV1.FLASH-batch.size&&destination/4096==(destination+batch.size-1)/4096)
                    record(InstallPhase.PAGE_WRITE_INTENT,destination);active()
                    s.program(destination,batch,generation)
                }
                require(readPage(at).contentEquals(wanted)){"FLASH page readback mismatch"};identity()
            }
            fun verifyImage(committed:Boolean,wanted:String) {
                val hash=MessageDigest.getInstance("SHA-256")
                for(at in 0 until AnchorV1.FLASH step 4096){val actual=readPage(at);require(actual.contentEquals(plan.page(at,committed))){"Complete FLASH readback mismatch"};hash.update(actual)}
                require(hash.digest().joinToString(""){"%02x".format(it.toInt() and 255)}==wanted)
            }
            record(InstallPhase.BODY_VERIFY);verifyImage(false,plan.binding.bodySha256);record(InstallPhase.BODY_VERIFIED)
            protectedPageGuard();commitAttempted=true;record(InstallPhase.COMMIT_INTENT,AnchorV1.ANCHOR+AnchorV1.COMMIT_OFFSET);active()
            val commit=ByteArray(4);putWord(commit,0,AnchorV1.COMMIT)
            s.program(AnchorV1.ANCHOR+AnchorV1.COMMIT_OFFSET,commit,generation)
            record(InstallPhase.COMMIT_WRITTEN,AnchorV1.ANCHOR+AnchorV1.COMMIT_OFFSET)
            protectedPageGuard();record(InstallPhase.FINAL_VERIFY);verifyImage(true,plan.binding.installedSha256);protectedPageGuard()
            s.close();lease=null
            record(InstallPhase.VERIFIED)
            return InstallOutcome(true,phase,null,true,true,false,"Complete FLASH/anchor and unchanged UICR verified; hardware installation remains unqualified")
        } catch(e:Exception) {
            val failedAt=phase;val message=(e.message?:e.javaClass.simpleName).take(1024)
            if(ownsJournal){
                try{
                    val durable=requireNotNull(journal.load(plan.binding.id));require(durable.binding==plan.binding)
                    sequence=durable.sequence+1
                    journal.save(InstallJournalRecord(plan.binding,sequence,InstallPhase.FAILED,address,mutated,commitAttempted,failedAt,message))
                }
                catch(_:Exception){journalFailure=true}
            }
            return InstallOutcome(false,failedAt,address,mutated,commitAttempted,journalFailure,message)
        } finally {
            try{lease?.close()}catch(_:Exception){/* Never hide the original failure or submit another target operation. */}
            busy.set(false)
        }
    }
}
