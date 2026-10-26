package org.openvimar.updater.installer

import org.openvimar.installer.*
import org.openvimar.installer.resume.ResumeHardwareAuthority
import org.openvimar.updater.DkUsbOperationGate
import java.io.IOException

/** One already-owner-approved connection. The caller owns/retains the process
 * USB token and physical connection until finish and worker drain complete.
 * No reconnect, UICR write, recovery, or CPU start after mutation. Initial
 * capture requires inactive WDT or the exact signed paused-watchdog handoff; software reset does not stop WDT. */
internal class NrfInitialInstallLease(private val wire:JlinkInstallWire,
    private val token:DkUsbOperationGate.Lease,private val cancelled:()->Boolean={false},
    private val now:()->Long=System::nanoTime) {
    private var expected:TargetIdentity?=null
    private var originalControl=0L
    private var opened=false;private var finished=false;private var acquired=false
    private var retainHalt=false
    var haltConfirmed=false;private set
    var startMayHaveOccurred=false;private set
    var startAcknowledged=false;private set
    var mutationMayHaveStarted=false;private set
    var resetCatchUsed=false;private set
    private var resetCatchComplete=false
    private var resetCatchSetupAttempted=false
    val debugStateUncertain get()=resetCatchSetupAttempted&&!resetCatchComplete
    private var handoffAuthority:WatchdogHandoffAuthority?=null
    private var restoreAuthority:OriginalRestorePlan?=null
    private var resumeAuthority:ResumeHardwareAuthority?=null
    var watchdogProfile:ObservedWatchdogProfile?=null;private set
    val watchdogHandoff get()=handoffAuthority?.policy
    var programmingPreparation:String?=null;private set
    private var programmingPrepared=false
    val generation get()=token.generation
    val originalCpuControl get()=originalControl.toInt()
    val haltRetentionRequired get()=(mutationMayHaveStarted||retainHalt)&&!startMayHaveOccurred
    @Synchronized fun retainHaltForPriorUncertainty(){check(opened&&!finished);retainHalt=true;guard()}
    private fun stopped(){token.checkCurrent();if(cancelled())throw IOException("Initial installation cancelled")}
    private fun number(bytes:ByteArray,offset:Int=0):Long=(0..3).fold(0L){v,i->v or ((bytes[offset+i].toLong() and 255) shl(i*8))}
    private fun word(at:Long)=number(wire.readWords(at,4))
    @Synchronized fun open(target:TargetIdentity,allowResetCatch:Boolean=false,watchdogHandoff:WatchdogHandoffAuthority?=null){
        openInternal(target,allowResetCatch,watchdogHandoff,null)
    }
    @Synchronized fun openForResume(target:TargetIdentity,authority:ResumeHardwareAuthority,watchdogHandoff:WatchdogHandoffAuthority?=null){
        openInternal(target,false,watchdogHandoff,authority)
    }
    @Synchronized fun openForVerifiedStart(target:TargetIdentity,receipt:InitialInstallReceipt,watchdogHandoff:WatchdogHandoffAuthority?=null){
        openInternal(target,false,watchdogHandoff,null,receipt)
    }
    @Synchronized fun openForOriginalRestore(target:TargetIdentity,plan:OriginalRestorePlan){
        plan.requireBinding(plan.binding,token.generation);require(plan.binding.target==target)
        restoreAuthority=plan;retainHalt=true
        openInternal(target,false,null,null)
    }
    private fun openInternal(target:TargetIdentity,allowResetCatch:Boolean,watchdogHandoff:WatchdogHandoffAuthority?,resume:ResumeHardwareAuthority?,verifiedStart:InitialInstallReceipt?=null){
        check(!opened&&!finished)
        if(verifiedStart!=null){require(verifiedStart.binding.target==target);retainHalt=true}
        if(resume!=null){
            resume.requireBinding(resume.binding,token.generation);require(resume.binding.target==target)
            // Even a PREPARED base can become stale. Any resume HALT side
            // effect must retain halt on every error/cancel, before open returns.
            retainHalt=true;resumeAuthority=resume
        }
        require(!allowResetCatch){"Pre-backup reset quiescence is unsupported; hardware watchdog must already be inactive"}
        stopped();wire.initialize()
        require(identity()==target){"Live UID/geometry differs before CPU halt"}
        val cpu=word(DHCSR)
        // C_STEP/MASKINTS/SNAPSTALL have interactions this baseline cannot
        // faithfully restore. They are UNKNOWN when C_DEBUGEN is zero.
        if(cpu and 1!=0L)require(cpu and 0xfffcL==0L){"Unsupported baseline CPU debug controls"}
        originalControl=if(cpu and 1==0L)0 else if(cpu and 0x20000!=0L)3 else 1
        require(word(READY)==1L){"Target NVMC is not ready"}
        val initialMode=word(CONFIG)
        require(if(resume==null&&restoreAuthority==null)initialMode==0L else initialMode in 0..2){"Target NVMC is not an admitted read/program/erase mode"}
        watchdogHandoff?.requireTarget(target,token.generation)
        val observed=readWatchdogProfile();watchdogProfile=observed;if(restoreAuthority!=null)observed.requireAcquisitionShape() else observed.requireSupported(watchdogHandoff)
        handoffAuthority=watchdogHandoff
        stopped();expected=target;opened=true
        wire.writeDebugControl(KEY or 3)
        val start=now();var halted=false
        repeat(128){if(!halted){stopped();val status=word(DHCSR)
            require(status and 0x02000000==0L){"Target reset while halting"}
            halted=status and 0x20000!=0L
            if(!halted&&now()-start>=500_000_000)throw IOException("CPU halt timed out")}}
        require(halted){"CPU halt was not confirmed"};haltConfirmed=true;guard()
        // The running CPU could have entered NVMC work after the pre-halt
        // check. Capture/start inspection requires a second quiescence proof
        // after HALT/reset catch, not a global guard used during our writes.
        require(word(READY)==1L){"Post-HALT NVMC is not ready"}
        if(resume==null&&restoreAuthority==null)require(word(CONFIG)==0L){"Post-HALT NVMC is not idle/read-only; no original capture is admitted"}
        else {
            require(word(CONFIG) in 0..2){"Unknown prior NVMC mode; explicit repair is blocked"}
            fun hash(data:ByteArray)=java.security.MessageDigest.getInstance("SHA-256").digest(data).joinToString(""){"%02x".format(it.toInt() and 255)}
            require(hash(readRegion(0x10000000,4096))==(resume?.ficrSha256?:restoreAuthority!!.ficrSha256)&&hash(readRegion(0x10001000,4096))==(resume?.uicrSha256?:restoreAuthority!!.uicrSha256)){"Protected original FICR/UICR differs before resume quiescence"}
            guard();ready()
            if(word(CONFIG)!=0L){wire.setNvmcMode(0);ready()}
            require(word(CONFIG)==0L){"Resume could not confirm NVMC read-only mode"}
        }
        guard()
    }
    private fun identity():TargetIdentity {
        val part=word(0x10000100);val variant=word(0x10000104)
        val uid=wire.readWords(0x10000060,8)
        require(word(0x10000010)==4096L&&word(0x10000014)==256L&&word(0x1000010c)==256L&&word(0x10000110)==1024L){"Unsupported FICR geometry"}
        require(part==0x52840L&&variant in 1..0xfffffffeL){"Unsupported silicon identity"}
        return TargetIdentity(number(uid),number(uid,4),variant,part)
    }
    private fun readWatchdogProfile():ObservedWatchdogProfile {
        val run=word(WDT_STATUS);val fields=wire.readWords(0x40010504L,12)
        return ObservedWatchdogProfile(run,number(fields,8),number(fields),number(fields,4))
    }
    private fun transportAndUid(){
        token.checkCurrent();val target=checkNotNull(expected);val uid=wire.readWords(0x10000060,8)
        require(number(uid)==target.uid0&&number(uid,4)==target.uid1){"Target UID changed; reconnect is prohibited"}
    }
    private fun guard(){
        check(opened&&!finished);stopped();transportAndUid();val cpu=word(DHCSR)
        require(cpu and 0x20003L==0x20003L&&cpu and 0x02000000L==0L){"CPU halt lost or target reset; installation stopped"};stopped()
        val observed=readWatchdogProfile();if(restoreAuthority!=null)observed.requireAcquisitionShape() else observed.requireSupported(handoffAuthority)
        require(observed==watchdogProfile){"Observed watchdog profile changed; no further installation mutation is allowed"};stopped()
    }
    /** The exclusive, non-reconnectable lease forbids cable/target replacement.
     * Full fresh UID/HALT checks surround each bounded batch/page; each word
     * and READY poll still checks cancellation and the live owner generation. */
    private fun transportGuard(){check(opened&&!finished);stopped()}
    private fun readRegion(at:Long,size:Int,onBytes:(Int)->Unit={}):ByteArray {
        require(size>0&&size%4==0);val out=ByteArray(size);var offset=0
        while(offset<size){guard();val n=minOf(512,size-offset,(1024-(at+offset)%1024).toInt());val bytes=wire.readWords(at+offset,n)
            val first=wire.readWords(at+offset,4);val last=if(n==4)first else wire.readWords(at+offset+n-4,4)
            require(first.contentEquals(bytes.copyOfRange(0,4))&&last.contentEquals(bytes.copyOfRange(n-4,n))){"Independent acquisition sentinel mismatch"}
            guard();bytes.copyInto(out,offset);offset+=n;onBytes(offset)}
        return out
    }
    @Synchronized fun currentIdentity():TargetIdentity {guard();return identity().also{require(it==expected)}}
    @Synchronized fun readOriginalRegion(file:String,onBytes:(Int)->Unit={}):ByteArray=when(file){
        "flash.bin"->readRegion(0,0x100000,onBytes)
        "ficr.bin"->readRegion(0x10000000,4096,onBytes)
        "uicr.bin"->readRegion(0x10001000,4096,onBytes)
        else->throw IllegalArgumentException("Unknown original region")
    }
    @Synchronized fun authorizer(binding:InstallBinding):SwdAuthorizer {
        guard();require(binding.target==expected);handoffAuthority?.requireBinding(binding,token.generation);resumeAuthority?.requireBinding(binding,token.generation);restoreAuthority?.requireBinding(binding,token.generation)
        return object:SwdAuthorizer {
            override fun acquire(request:InstallBinding):AuthorizedSwdSession=synchronized(this@NrfInitialInstallLease){
                guard();require(request==binding);check(!acquired);acquired=true
                object:AuthorizedSwdSession {
                    override val binding=request
                    override val generation=token.generation
                    private var closed=false
                    private fun active(epoch:Long=generation){check(!closed&&epoch==generation);guard()}
                    private fun wordActive(epoch:Long=generation){check(!closed&&epoch==generation);transportGuard()}
                    override fun check(expectedGeneration:Long,expectedIdentity:TargetIdentity)=synchronized(this@NrfInitialInstallLease){active(expectedGeneration);require(expectedIdentity==expected)}
                    override fun readIdentity():TargetIdentity=synchronized(this@NrfInitialInstallLease){active();identity().also{require(it==expected)}}
                    override fun readFicr():ByteArray=synchronized(this@NrfInitialInstallLease){active();readRegion(0x10000000,4096)}
                    override fun readUicr():ByteArray=synchronized(this@NrfInitialInstallLease){active();readRegion(0x10001000,4096)}
                    override fun readFlash(address:Int,size:Int):ByteArray=synchronized(this@NrfInitialInstallLease){require(address>=0&&address%4==0&&size in 4..4096&&size%4==0&&address<=0x100000-size);active();readRegion(address.toLong(),size)}
                    override fun erasePage(address:Int,expectedGeneration:Long)=synchronized(this@NrfInitialInstallLease){
                        require(address in 0..0xff000&&address%4096==0);active(expectedGeneration)
                        mutationMayHaveStarted=true;prepareProgramming();ready();active();wire.setNvmcMode(2);ready();active();wire.eraseFlashPage(address);ready();active();wire.setNvmcMode(0);ready()
                        require(readRegion(address.toLong(),4096).all{it==0xff.toByte()}){"Page erase readback failed"}
                    }
                    override fun program(address:Int,data:ByteArray,expectedGeneration:Long)=synchronized(this@NrfInitialInstallLease){
                        val frozen=data.copyOf();require(address>=0&&address%4==0&&frozen.size in 4..256&&frozen.size%4==0&&address<=0x100000-frozen.size&&address/4096==(address+frozen.size-1)/4096&&address%1024+frozen.size<=1024)
                        active(expectedGeneration);mutationMayHaveStarted=true;prepareProgramming();ready();wordActive();wire.setNvmcMode(1);ready()
                        for(i in frozen.indices step 4){
                            wordActive();val word=frozen.copyOfRange(i,i+4)
                            // All-FF is already erased, not an NVMC program
                            // operation. In particular the commit word gets no
                            // early all-FF pulse before its final four bytes.
                            if(word.all{it==0xff.toByte()})continue
                            wire.programFlashWords(address+i,word);ready()
                        }
                        active();wire.setNvmcMode(0);ready();require(readRegion(address.toLong(),frozen.size).contentEquals(frozen)){"Program batch readback failed"}
                    }
                    override fun close(){synchronized(this@NrfInitialInstallLease){closed=true}} // Caller still owns physical connection.
                }
            }
        }
    }
    private fun ready(){val start=now();repeat(128){transportGuard();if(word(READY)==1L)return;if(now()-start>=500_000_000)throw IOException("NVMC READY timed out; CPU remains halted")};throw IOException("NVMC READY polling limit")}
    private fun flashWriteProtections():List<Int> = (0 until 8).filter{index->
        val fields=wire.readWords(0x4001e800L+index*16,12)
        val address=number(fields);val size=number(fields,4);val permission=number(fields,8)
        // Nordic ACL enforces only valid page ranges with nonzero SIZE/PERM.
        val valid=address<0x100000L&&address%4096==0L&&size>0&&size%4096==0L
        require(!valid||permission and 1L==0L){"FLASH ACL region $index blocks original readback; no preparation reset or FLASH mutation is allowed"}
        valid&&permission and 2L!=0L
    }
    /** Called only by an owner-reviewed FLASH mutation, never by acquisition,
     * inspection or verify-only repair. Stock boot leaves volatile ACLs active
     * while HALT alone does not clear them. A caught reset clears volatile
     * state without issuing instructions or changing UICR/ACL registers. */
    private fun prepareProgramming(){
        if(programmingPrepared)return
        guard();ready()
        programmingPreparation="Inspecting FLASH ACL registers before reviewed programming"
        val protections=flashWriteProtections()
        if(protections.isEmpty()){
            programmingPreparation="FLASH ACL clear; no preparation reset required"
            programmingPrepared=true;return
        }
        programmingPreparation="FLASH write protection in ACL regions ${protections.joinToString()}; preparing caught reset"
        val ficr=readRegion(0x10000000L,4096);val uicr=readRegion(0x10001000L,4096)
        retainHalt=true;guard();resetCatchSetupAttempted=true;resetCatchComplete=false
        wire.enableResetVectorCatch();resetCatchUsed=true
        wire.requestCaughtSystemReset()
        val start=now();var seenReset=false;var caught=false
        repeat(128){if(!caught){stopped();val cpu=word(DHCSR);seenReset=seenReset||cpu and 0x02000000L!=0L
            caught=seenReset&&cpu and 0x20003L==0x20003L
            if(!caught&&now()-start>=500_000_000)throw IOException("Programming preparation reset catch timed out; CPU state requires review")}}
        require(caught){"Programming preparation reset did not confirm halted CPU"}
        guard();ready();require(word(CONFIG)==0L){"NVMC did not return to read-only after preparation reset"}
        require(readRegion(0x10000000L,4096).contentEquals(ficr)&&readRegion(0x10001000L,4096).contentEquals(uicr)){"FICR/UICR changed during programming preparation"}
        require(flashWriteProtections().isEmpty()){"FLASH ACL remains write-protected after preparation reset; no FLASH mutation attempted"}
        verifyResetRegisters(requirePlausibleVectors=false)
        wire.restoreResetVectorCatch();guard();resetCatchComplete=true
        programmingPreparation="FLASH ACL regions ${protections.joinToString()} cleared by confirmed reset catch; UID/FICR/UICR/watchdog unchanged; CPU halted"
        programmingPrepared=true
    }
    private fun verifyResetRegisters(requirePlausibleVectors:Boolean=true){
        guard();val vectors=wire.readWords(0,8);val stack=number(vectors);val reset=number(vectors,4)
        if(requirePlausibleVectors)require(stack>0x20000000L&&stack<=0x20040000L&&stack%8==0L&&reset and 1L==1L&&(reset and 0xfffffffeL) in 8L until 0x100000L){"Reset vectors are not plausible"}
        val pc=wire.readCoreRegister(0x0f);stopped();val msp=wire.readCoreRegister(0x11);stopped();val xpsr=wire.readCoreRegister(0x10)
        // Armv7-M TakeReset masks SP[1:0] and loads EPSR.T from vector bit0.
        // A repair can start with an erased vector page, unlike normal start.
        val expectedMsp=stack and 0xfffffffcL;val expectedThumb=(reset and 1L) shl 24
        require(pc==(reset and 0xfffffffeL)&&msp==expectedMsp&&xpsr and 0x01000000L==expectedThumb&&xpsr and 0x1ffL==0L){"Caught reset PC/MSP/Thumb state differs from live vectors; CPU stays halted"}
        guard()
    }
    /** Only the controller's fresh verified receipt path calls this. Never
     * clears C_HALT over the old PC: a caught reset and HALT are mandatory. */
    @Synchronized fun startVerifiedReset(){
        retainHaltForPriorUncertainty();guard();resetCatchSetupAttempted=true;resetCatchComplete=false;wire.enableResetVectorCatch();resetCatchUsed=true
        wire.requestCaughtSystemReset();val start=now();var seenReset=false;var caught=false
        repeat(128){if(!caught){stopped();val cpu=word(DHCSR);seenReset=seenReset||cpu and 0x02000000!=0L
            caught=seenReset&&cpu and 0x20003L==0x20003L
            if(!caught&&now()-start>=500_000_000)throw IOException("Verified start reset catch timed out")}}
        require(caught){"Verified reset did not confirm halted CPU"};guard() // SYSRESETREQ preserves WDT; signed loader owns any paused handoff.
        verifyResetRegisters();wire.finishResetVectorCatchForNormalStart();guard();resetCatchComplete=true
        startMayHaveOccurred=true // A lost acknowledgement must not restore/release an earlier PC.
        haltConfirmed=false // Release acknowledgement may be lost.
        wire.writeDebugControl(KEY) // Explicit normal start ends halting debug, not the pre-capture debugger state.
        wire.endNormalDebugSession() // No AP access, including UID reads, after dropping power requests.
        startAcknowledged=true
    }
    /** Pre-write cancellation restores only supported original CPU control.
     * Any possible NVMC mutation permanently disables this cleanup path. */
    @Synchronized fun finish(){
        if(finished)return
        if(opened&&(retainHalt||mutationMayHaveStarted||((resetCatchSetupAttempted||resetCatchUsed)&&!resetCatchComplete))&&!startMayHaveOccurred){
            // Includes cancellation immediately after a HALT write, before its
            // first observation. Cleanup confirms/reasserts HALT; it never
            // restores an earlier PC for resume or any possible FLASH change.
            retainHalt=true;transportAndUid();wire.writeDebugControl(KEY or 3)
            var halted=false;repeat(128){if(!halted)halted=word(DHCSR) and 0x20003L==0x20003L};require(halted){"Failed catch could not retain CPU halt"};haltConfirmed=true
        }
        if(opened&&!mutationMayHaveStarted&&!retainHalt&&!startMayHaveOccurred){transportAndUid();val cpu=word(DHCSR);require(cpu and 0x02000000==0L){"CPU reset; original execution state cannot be restored"};wire.writeDebugControl(KEY or originalControl);haltConfirmed=originalControl==3L}
        finished=true
    }
    companion object {
        const val DHCSR=0xe000edf0L;const val KEY=0xa05f0000L
        const val READY=0x4001e400L;const val CONFIG=0x4001e504L
        const val WDT_STATUS=0x40010400L;const val WDT_CONFIG=0x4001050cL
    }
}
