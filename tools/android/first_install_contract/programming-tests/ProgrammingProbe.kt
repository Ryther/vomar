package org.openvimar.updater

import java.util.concurrent.CountDownLatch
import java.util.concurrent.atomic.AtomicInteger
import org.openvimar.updater.installer.*
import org.openvimar.installer.*
import org.openvimar.installer.resume.*
import java.nio.file.Files
import java.nio.file.Path
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec

fun main(args:Array<String>) {
    when(args[0]) {
        "prepare-acl-lower","prepare-acl-upper","prepare-no-acl","prepare-acl-empty","prepare-acl-capture","prepare-acl-watchdog","prepare-acl-persistent","prepare-acl-uncaught","prepare-acl-cancel","prepare-acl-empty-vectors","prepare-acl-read-denied","prepare-acl-wrong-pc","prepare-acl-wrong-msp","prepare-acl-even-vector","prepare-acl-fault" -> {
            val candidate=if(args[0]=="prepare-acl-watchdog") {
                val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Files.readAllBytes(Path.of(args[2]))))
                CandidateRelease.inspect(Files.readAllBytes(Path.of(args[1])),key,"9.0.0")
            } else null
            programmingPreparationProbe(args[0],candidate)
        }
        "restore-mode1","restore-paused-watchdog","restore-running-watchdog","restore-bad-uicr","restore-wrong-uid","restore-acl","restore-acl-watchdog" -> originalRestoreLeaseProbe(args[0])
        "resume-mode1","resume-mode2","resume-cancel","resume-bad-uicr","resume-mode-ack-loss","resume-unconfirmed" -> resumeLeaseProbe(args)
        "lease-erase-ready-deadline" -> {
            val target=ProgrammingWireTarget();val token=checkNotNull(DkUsbOperationGate.acquire("synthetic erase deadline"));var tick=0L
            val lease=NrfInitialInstallLease(JlinkInstallWire(target),token,now={tick.also{tick+=250_000}})
            try{
                val id=TargetIdentity(0x12345678,0xabcdef01,0x41414430);lease.open(id)
                val hash="00".repeat(32);val binding=InstallBinding(id,hash,hash,hash,hash,hash,hash,hash)
                val port=lease.authorizer(binding).acquire(binding)
                target.onMemoryWrite={at,_->if(at==0x4001e508L)target.readyAfterPolls=200}
                port.erasePage(8192,token.generation)
                check(target.readyAfterPolls<=0&&target.halted)
                port.close()
            }finally{lease.finish();token.close()}
        }
        "wire-flash-wait","wire-flash-fault","wire-flash-parity","wire-flash-ready" -> {
            val target=ProgrammingWireTarget();val token=checkNotNull(DkUsbOperationGate.acquire("synthetic word fault"))
            val lease=NrfInitialInstallLease(JlinkInstallWire(target),token)
            try{
                val id=TargetIdentity(0x12345678,0xabcdef01,0x41414430);lease.open(id)
                val hash="00".repeat(32);val binding=InstallBinding(id,hash,hash,hash,hash,hash,hash,hash)
                val port=lease.authorizer(binding).acquire(binding);port.erasePage(8192,token.generation)
                if(args[0] in setOf("wire-flash-wait","wire-flash-fault"))target.inject(true,false,12,if(args[0].endsWith("wait"))2 else 4,skip=1)
                target.onMemoryWrite={at,_->if(at==8192L){if(args[0].endsWith("parity"))target.corruptReadParityCount=1;if(args[0].endsWith("ready"))target.neverReady=true}}
                check(runCatching{port.program(8192,ByteArray(256){1},token.generation)}.isFailure)
                val words=target.memoryWrites.filter{it.first in 8192L..8447L}
                check(words.size==if(args[0].endsWith("wait")||args[0].endsWith("fault"))0 else 1){"Next word was issued after uncertainty: $words"}
                port.close()
            }finally{runCatching{lease.finish()};token.close()}
        }
        "wire-performance" -> {
            val target=ProgrammingWireTarget();target.logLimit=0
            var writes=0;var reads=0
            val channel=object:InstallBulkChannel{override fun write(bytes:ByteArray):Int{writes++;return target.write(bytes)};override fun read(maxBytes:Int):ByteArray{reads++;return target.read(maxBytes)}}
            val token=checkNotNull(DkUsbOperationGate.acquire("synthetic performance"));val wire=JlinkInstallWire(channel);val lease=NrfInitialInstallLease(wire,token)
            try{
                val targetId=TargetIdentity(0x12345678,0xabcdef01,0x41414430);lease.open(targetId)
                val hash="00".repeat(32);val binding=InstallBinding(targetId,hash,hash,hash,hash,hash,hash,hash)
                val port=lease.authorizer(binding).acquire(binding);port.erasePage(8192,token.generation)
                writes=0;reads=0;port.program(8192,ByteArray(256){1},token.generation)
                check(writes<=100&&reads<=100){"256-byte program uses $writes commands and $reads replies; budget100"}
                check(target.flash.copyOfRange(8192,8448).all{it==1.toByte()})
                writes=0;reads=0;port.readFlash(8192,4096)
                check(writes<=65&&reads<=65){"4KiB read uses $writes commands and $reads replies; budget65"}
                port.close()
            }finally{lease.finish();token.close()}
        }
        "wire-cache" -> {
            val target=ProgrammingWireTarget();val wire=JlinkInstallWire(target);wire.initialize()
            val csw=target.events.count{it.startsWith("write:AP:0:")};val select=target.events.count{it.startsWith("write:DP:8:")}
            wire.readWords(0,4);wire.readWords(0x10000060L,8)
            check(target.events.count{it.startsWith("write:AP:0:")}==csw)
            check(target.events.count{it.startsWith("write:DP:8:")}==select)
            target.inject(true,true,12,2,skip=3)
            wire.readWords(0,512)
            check(target.events.count{it.startsWith("write:AP:0:")}>csw) // Reset retry restores rather than trusts old CSW.
        }
        "wire-core-registers" -> {
            val target=ProgrammingWireTarget();val wire=JlinkInstallWire(target);wire.initialize();wire.writeDebugControl(0xa05f0003)
            check(wire.readCoreRegister(0x0f)==0x1000L);check(wire.readCoreRegister(0x10)==0x01000000L);check(wire.readCoreRegister(0x11)==0x20020000L)
            val before=target.events.size
            for(selector in listOf(0x12,0x1000f))check(runCatching{wire.readCoreRegister(selector)}.isFailure)
            check(target.events.size==before)
            check(target.memoryWrites.filter{it.first==0xe000edf4L}.map{it.second}==listOf(15L,16L,17L))
            target.registerNeverReady=true;check(runCatching{wire.readCoreRegister(15)}.isFailure)
        }
        "host-policy" -> {
            val id="ef1faf4b-cd24-42c7-8508-8d51b4f10ad5"
            val host=FirstInstallHostPolicy();check(host.current()==null)
            val first=checkNotNull(host.admit(id));check(host.admit(id)==null)
            host.cancel();check(first.cancelled);check(runCatching{first.checkActive()}.isFailure)
            host.finished(first);val second=checkNotNull(host.admit(id))
            host.finished(first);check(host.current()===second)
            host.destroy();check(second.cancelled&&host.admit(id)==null)
            check(FirstInstallHostPolicy().current()==null) // Process recreation has no execution grant.
        }
        "selected-document" -> {
            val bytes=ByteArray(32001){it.toByte()};var written=byteArrayOf();var opens=0
            val port=SelectedDocumentExport("explicit-content-document",{
                object:java.io.ByteArrayOutputStream(){override fun close(){written=toByteArray();super.close()}}
            },{opens++;java.io.ByteArrayInputStream(written)})
            check(port.create(bytes)=="explicit-content-document"&&written.contentEquals(bytes))
            check(port.reopen("explicit-content-document").contentEquals(bytes))
            check(runCatching{port.reopen("different-document")}.isFailure&&opens==1)
            val failed=SelectedDocumentExport("explicit-content-document",{object:java.io.ByteArrayOutputStream(){override fun close(){error("Close failed")}}},{error("No read on failed export")})
            check(runCatching{failed.create(bytes)}.isFailure)
            val oversized=SelectedDocumentExport("explicit-content-document",{java.io.ByteArrayOutputStream()},{java.io.ByteArrayInputStream(ByteArray(2*1024*1024+1))})
            check(runCatching{oversized.reopen("explicit-content-document")}.isFailure)
        }
        "resume-capture-fence" -> {
            val root=Path.of(args[1]);val directory=root.resolve("transactions");val store=FileInstallJournal(directory)
            val target=TargetIdentity(1,2,0x41414430);val hash="00".repeat(32);val binding=InstallBinding(target,hash,hash,hash,hash,hash,hash,hash)
            check(store.begin(InstallJournalRecord(binding,1,InstallPhase.PREPARED,null,false,false)))
            val exports=root.resolve("exports");Files.createDirectories(exports)
            val receipt=OriginalExportReceipt.parse(("{\"archiveSha256\":\"$hash\",\"bindingId\":\"${binding.id}\",\"document\":\"content://initial/original\",\"schemaVersion\":1}\n").toByteArray())
            Files.write(exports.resolve("${binding.id}.json"),receipt.encode())
            val journal=FileResumeJournal(directory,root.resolve("resume"));val head=journal.inspect(binding,receipt)
            journal.acquire(binding,receipt,head.headSha256,"ef1faf4b-cd24-42c7-8508-8d51b4f10ad5",77,"content://cloud/copy").use{session->
                session.append(ResumePhase.REVIEWED,null,-1,false);session.append(ResumePhase.ERASE_INTENT,0,0,false)
            }
            check(store.load(binding.id)?.mutationMayHaveStarted==false) // immutable baseline cannot carry later resume intent
            val fence=FileInstallRecoveryFence(directory)
            check(runCatching{fence.assertCanCapture(target)}.isFailure){"A progressed resume must block relabeling mixed FLASH as original"}
            fence.assertCanCapture(target.copy(uid0=3))
        }
        "recovery-fence" -> {
            val directory=Path.of(args[1],"journal");val store=FileInstallJournal(directory)
            val target=TargetIdentity(0x12345678,0xabcdef01,0x41414430);val hash="00".repeat(32)
            val binding=InstallBinding(target,hash,hash,hash,hash,hash,hash,hash)
            val fence=FileInstallRecoveryFence(directory);fence.assertCanCapture(target)
            check(store.begin(InstallJournalRecord(binding,1,InstallPhase.PREPARED,null,false,false)))
            fence.assertCanCapture(target)
            store.save(InstallJournalRecord(binding,2,InstallPhase.PAGE_ERASE_INTENT,0,true,false))
            check(runCatching{fence.assertCanCapture(target)}.isFailure)
            fence.assertCanCapture(target.copy(uid0=target.uid0 xor 1))
            store.save(InstallJournalRecord(binding,3,InstallPhase.VERIFIED,null,true,true))
            check(runCatching{fence.assertCanCapture(target)}.isFailure)
            fence.assertCanCapture(target.copy(uid0=target.uid0 xor 1))
            Files.write(directory.resolve("00".repeat(32)+".json"),byteArrayOf(123))
            check(runCatching{fence.assertCanCapture(target)}.isFailure)
        }
        "controller-prewrite","controller-full","controller-partial-cancel","controller-persist-fail","controller-close-fail","controller-export-change","controller-begin-persist-fail","controller-start","controller-start-changed","controller-keep-halted","controller-already-custom","controller-anchor-present","controller-start-clean-debug","controller-start-wrong-pc","controller-start-wrong-msp","controller-start-ignored-catch","controller-start-enable-fail","controller-paused-watchdog","controller-watchdog-no-cap","controller-watchdog-running","controller-watchdog-empty-rre","controller-watchdog-long","controller-resume","controller-resume-cancel","controller-resume-verified","controller-start-open-fail" -> {
            val target=ProgrammingWireTarget();target.logLimit=5000
            byteArrayOf(0,0,2,0x20,1,0x10,0,0).copyInto(target.flash)
            if(args[0]=="controller-already-custom")target.flash[0xb0000]=0
            if(args[0]=="controller-anchor-present")"VAR1".toByteArray().copyInto(target.flash,0xb000)
            if(args[0]=="controller-start-clean-debug"){target.debugControl=1;target.demcr=0x01000001}
            if(args[0].startsWith("controller-watchdog")||args[0]=="controller-paused-watchdog"){
                target.wdtRunning=true;target.wdtConfig=1;target.wdtCrv=0x50000;target.wdtRren=1
                if(args[0]=="controller-watchdog-running")target.wdtConfig=9
                if(args[0]=="controller-watchdog-empty-rre")target.wdtRren=0
                if(args[0]=="controller-watchdog-long")target.wdtCrv=60L*32768
            }
            val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Files.readAllBytes(Path.of(args[2]))))
            val candidate=CandidateRelease.inspect(Files.readAllBytes(Path.of(args[1])),key,"9.0.0")
            val request=InstallCaptureRequest("ef1faf4b-cd24-42c7-8508-8d51b4f10ad5","synthetic-model",TargetIdentity(0x12345678,0xabcdef01,0x41414430),candidate.releaseSha256)
            var stored:ByteArray?=null;val evidence=InitialInstallRetainedEvidence(Path.of(args[3]),{stored?.let(OriginalArchive::verify)});val snapshots=mutableListOf<InitialInstallSnapshot>();var persistenceFailed=false
            val persistence=object:InitialInstallPersistence {
                override fun assertCanCapture(target:TargetIdentity){FileInstallRecoveryFence(Path.of(args[3],"transactions")).assertCanCapture(target)}
                override fun saveOriginal(requestId:String,archive:ByteArray){OriginalArchive.verify(archive);stored=archive.copyOf()}
                override fun saveExportReceipt(original:OriginalMaterial,binding:InstallBinding)=evidence.saveExport(original,binding)
                override fun recordStart(binding:InstallBinding,requestId:String,acknowledged:Boolean)=evidence.recordStart(binding,requestId,acknowledged)
                override fun saveState(snapshot:InitialInstallSnapshot){snapshots+=snapshot
                    if(!persistenceFailed&&(args[0]=="controller-persist-fail"&&snapshot.phase==InitialInstallPhase.INSTALLING||args[0]=="controller-begin-persist-fail"&&snapshot.phase==InitialInstallPhase.CONNECTING)){
                        persistenceFailed=true;error("Injected durable status acknowledgement failure")}}
            }
            val observed=mutableListOf<InitialInstallSnapshot>()
            val controller=InitialInstallController({r,cancelled,proof->
                val token=checkNotNull(DkUsbOperationGate.acquire("synthetic installer"))
                val lease=NrfInitialInstallLease(JlinkInstallWire(target,{token.checkCurrent()}),token,cancelled)
                try{val authority=candidate.authorizeWatchdogHandoff(r.target,token.generation)
                    if(proof==null)lease.open(r.target,r.allowResetCatch,watchdogHandoff=authority)else lease.openForVerifiedStart(r.target,proof,authority)}
                catch(error:Exception){try{lease.finish()}finally{token.close()};throw error}
                object:InitialInstallConnection {
                    override val lease=lease
                    override val provenance=QuiescentProvenance("synthetic test","synthetic probe",3300,0x1366,0x1060,4,0x85,3)
                    override fun close(){token.close();if(args[0]=="controller-close-fail")error("Injected USB close failure")}
                }
            },persistence,FileInstallJournal(Path.of(args[3],"transactions")),observed={observed+=it})
            if(args[0] in setOf("controller-partial-cancel","controller-resume","controller-resume-cancel"))target.onMemoryWrite={address,_->if(address==0x4001e508L)controller.cancel()}
            controller.beginCandidate(request,candidate)
            if(args[0] in setOf("controller-already-custom","controller-anchor-present")){
                check(controller.snapshot.phase==InitialInstallPhase.FAILED&&controller.snapshot.archiveSha256==null&&stored==null&&!target.halted)
                check(snapshots.none{it.phase==InitialInstallPhase.AWAITING_EXPORT});return
            }
            if(args[0].startsWith("controller-watchdog")){
                check(controller.snapshot.phase==InitialInstallPhase.FAILED&&target.memoryWrites.isEmpty()&&stored==null&&target.resetCount==0);return
            }
            if(args[0]=="controller-begin-persist-fail"){
                check(controller.snapshot.phase==InitialInstallPhase.FAILED&&controller.snapshot.request==request&&controller.snapshot.journalFailure)
                check(target.memoryWrites.isEmpty());return
            }
            check(controller.snapshot.phase==InitialInstallPhase.AWAITING_EXPORT&&target.halted&&stored!=null)
            val captureProgress=observed.filter{it.phase==InitialInstallPhase.CAPTURING&&it.progressTotal>0}
            check(captureProgress.last().progressDone==2*(0x100000+8192))
            check(captureProgress.zipWithNext().all{(a,b)->a.progressDone<b.progressDone})
            var exported=byteArrayOf()
            controller.export(object:ArchiveExport {
                override fun create(bytes:ByteArray):String {check(target.halted&&DkUsbOperationGate.acquire("watch")==null);exported=bytes.copyOf();return "same-explicit-document"}
                override fun reopen(document:String):ByteArray {check(document=="same-explicit-document"&&target.halted);return exported.copyOf().also{if(args[0]=="controller-export-change")it[10]=(it[10].toInt() xor 1).toByte()}}
            })
            if(args[0]=="controller-export-change"){
                check(controller.snapshot.phase==InitialInstallPhase.FAILED&&!target.halted&&controller.receipt==null&&stored!=null)
                check(target.memoryWrites.none{it.first==0x4001e504L});return
            }
            check(controller.snapshot.phase==InitialInstallPhase.AWAITING_REVIEW&&target.memoryWrites.none{it.first==0x4001e504L})
            val binding=checkNotNull(controller.snapshot.binding)
            if(args[0]=="controller-prewrite"){
                check(runCatching{controller.install(InstallOwnerReview(request.requestId,"00".repeat(32),candidate.releaseSha256))}.isFailure)
                check(controller.snapshot.phase==InitialInstallPhase.AWAITING_REVIEW)
                controller.cancel();controller.cancelAndClose();check(!target.halted&&controller.snapshot.phase==InitialInstallPhase.CANCELLED)
            }else{
                controller.install(InstallOwnerReview(request.requestId,binding.id,candidate.releaseSha256))
                if(args[0] in setOf("controller-full","controller-start","controller-start-changed","controller-keep-halted","controller-start-clean-debug","controller-start-wrong-pc","controller-start-wrong-msp","controller-start-ignored-catch","controller-start-enable-fail","controller-paused-watchdog","controller-resume-verified","controller-start-open-fail")){
                    check(controller.snapshot.phase==InitialInstallPhase.VERIFIED_HALTED&&controller.receipt!=null)
                    check(java.security.MessageDigest.getInstance("SHA-256").digest(target.flash).joinToString(""){"%02x".format(it.toInt() and 255)}==binding.installedSha256)
                    check(target.memoryWrites.filter{it.first in 0..0xfffffL}.last().first==0xb0fcL)
                    check(target.memoryWrites.count{it.first==0xb0fcL}==1) // No earlier all-FF NVMC pulse at the commit word.
                    if(args[0] in setOf("controller-start","controller-start-clean-debug","controller-paused-watchdog")){
                        controller.startVerified(InstallOwnerReview(request.requestId,binding.id,candidate.releaseSha256))
                        check(controller.snapshot.phase==InitialInstallPhase.STARTED&&!target.halted&&target.resetCount==1)
                        check(target.requestedPowerBits==0L)
                        val startProgress=observed.filter{it.phase==InitialInstallPhase.STARTING&&it.progressTotal==0x100000}
                        check(startProgress.last().progressDone==0x100000&&startProgress.zipWithNext().all{(a,b)->a.progressDone<b.progressDone})
                        if(args[0]=="controller-paused-watchdog"){
                            check(target.wdtRunning) // SYSRESETREQ does not clear inherited WDT.
                            check(controller.snapshot.message.contains("watchdog"))
                            target.firmwareReset(watchdog=true);check(!target.wdtRunning&&target.debugControl==0L&&!target.halted)
                        }
                        if(args[0]=="controller-start-clean-debug"){
                            check(target.debugControl==0L&&target.demcr==0x01000000L)
                            target.firmwareReset();check(!target.halted)
                        }
                        check(runCatching{controller.startVerified(InstallOwnerReview(request.requestId,binding.id,candidate.releaseSha256))}.isFailure)
                    }
                    if(args[0] in setOf("controller-start-wrong-pc","controller-start-wrong-msp","controller-start-ignored-catch","controller-start-enable-fail")){
                        target.wrongResetPc=args[0]=="controller-start-wrong-pc";target.wrongResetMsp=args[0]=="controller-start-wrong-msp"
                        target.ignoreVectorCatch=args[0]=="controller-start-ignored-catch"
                        if(args[0]=="controller-start-enable-fail")target.onMemoryWrite={address,value->if(address==0xe000edfcL&&value and 1!=0L)target.corruptReadParityCount=1}
                        val before=target.memoryWrites.size
                        controller.startVerified(InstallOwnerReview(request.requestId,binding.id,candidate.releaseSha256))
                        check(controller.snapshot.phase==InitialInstallPhase.FAILED&&target.halted&&controller.receipt==null&&controller.snapshot.debugStateUncertain)
                        check(target.memoryWrites.drop(before).none{it.first==0xe000edf0L&&it.second and 2==0L})
                    }
                    if(args[0]=="controller-start-open-fail"){
                        target.halted=false;target.debugControl=0
                        target.onMemoryWrite={address,value->if(address==0xe000edf0L&&value and 3==3L)target.mode=1}
                        controller.startVerified(InstallOwnerReview(request.requestId,binding.id,candidate.releaseSha256))
                        check(controller.snapshot.phase==InitialInstallPhase.FAILED&&target.halted&&controller.receipt==null)
                    }
                    if(args[0]=="controller-start-changed"){
                        target.flash[0x1000]=(target.flash[0x1000].toInt() xor 1).toByte()
                        controller.startVerified(InstallOwnerReview(request.requestId,binding.id,candidate.releaseSha256))
                        check(controller.snapshot.phase==InitialInstallPhase.FAILED&&target.halted&&target.resetCount==0&&controller.receipt==null)
                    }
                    if(args[0]=="controller-keep-halted"){
                        controller.cancel();controller.cancelAndClose();check(controller.snapshot.phase==InitialInstallPhase.CANCELLED&&target.halted&&controller.receipt==null)
                    }
                }else if(args[0]=="controller-persist-fail")check(controller.snapshot.phase==InitialInstallPhase.FAILED&&controller.snapshot.journalFailure&&!target.halted&&target.memoryWrites.none{it.first==0x4001e504L})
                else {
                    check(controller.snapshot.phase==InitialInstallPhase.FAILED&&controller.receipt==null&&controller.snapshot.mutationMayHaveStarted)
                    if(args[0]=="controller-close-fail")check(controller.snapshot.commitMayHaveBeenWritten)
                }
                if(args[0] !in setOf("controller-persist-fail","controller-start","controller-start-clean-debug","controller-paused-watchdog"))check(target.halted)
            }
            check(exported.contentEquals(stored)&&snapshots.first().phase==InitialInstallPhase.CONNECTING)
            checkNotNull(DkUsbOperationGate.acquire("following diagnostic")).close()
            if(args[0].startsWith("controller-resume")){
                target.onMemoryWrite={_,_->};val option=evidence.options(request.target).single();val retained=evidence.reopen(option.bindingId)
                val reopened=retained.reopenOriginal("content://cloud/moved-original"){checkNotNull(stored)}
                val resumedRequest=request.copy(requestId="00000000-0000-0000-0000-000000000001")
                fun link(r:InstallCaptureRequest,cancelled:()->Boolean,authority:((Long)->ResumeHardwareAuthority)?):InitialInstallConnection{
                    val token=checkNotNull(DkUsbOperationGate.acquire("synthetic explicit repair"));val lease=NrfInitialInstallLease(JlinkInstallWire(target,{token.checkCurrent()}),token,cancelled)
                    try{if(authority==null)lease.open(r.target) else lease.openForResume(r.target,authority(token.generation))}
                    catch(error:Exception){try{lease.finish()}finally{token.close()};throw error}
                    return object:InitialInstallConnection{override val lease=lease;override val provenance=QuiescentProvenance("synthetic","synthetic",3300,0x1366,0x1060,4,0x85,3);override fun close(){token.close()}}
                }
                val after=InitialInstallController({r,c,_->link(r,c,null)},persistence,FileInstallJournal(Path.of(args[3],"transactions")),resumeConnect={r,c,a->link(r,c,a)})
                val before=target.memoryWrites.count{it.first in 0L..0xfffffL}
                val priorResets=target.resetCount
                if(args[0]=="controller-resume-verified"){target.flashAcl[7][0]=0xf8000;target.flashAcl[7][1]=4096;target.flashAcl[7][2]=2}
                after.prepareResumeCandidate(resumedRequest,candidate,reopened,evidence.journal,option.journalHeadSha256)
                check(after.snapshot.phase==InitialInstallPhase.AWAITING_RESUME_REVIEW&&after.snapshot.resume&&after.snapshot.binding==binding)
                if(args[0]=="controller-resume-cancel"){
                    after.cancel();after.cancelAndClose();check(after.snapshot.phase==InitialInstallPhase.CANCELLED&&target.halted)
                    check(target.memoryWrites.count{it.first in 0L..0xfffffL}==before)
                }else{
                    val review=ResumeOwnerReview(resumedRequest.requestId,binding.id,candidate.releaseSha256,checkNotNull(after.snapshot.resumeHeadSha256))
                    check(runCatching{after.resume(review.copy(journalHeadSha256="00".repeat(32)))}.isFailure)
                    after.resume(review);check(after.snapshot.phase==InitialInstallPhase.VERIFIED_HALTED&&after.receipt!=null&&target.halted)
                    if(args[0]=="controller-resume-verified"){check(target.memoryWrites.count{it.first in 0L..0xfffffL}==before);check(target.resetCount==priorResets&&target.flashAcl[7][2]==2L){"Verify-only repair must not clear ACL or request a preparation reset"}}
                }
                checkNotNull(DkUsbOperationGate.acquire("post resume diagnostic")).close()
            }
            if(args[0]=="controller-partial-cancel"){
                val after=InitialInstallController({_,_,_->error("Must not reconnect after unfinished NVMC mutation")},persistence,FileInstallJournal(Path.of(args[3],"transactions")))
                after.beginCandidate(request.copy(requestId="00000000-0000-0000-0000-000000000000"),candidate)
                check(after.snapshot.phase==InitialInstallPhase.FAILED&&after.snapshot.message.contains("repair"))
            }
        }
        "lease-watchdog-paused","lease-watchdog-running","lease-retired-reset-flag" -> {
            val token=checkNotNull(DkUsbOperationGate.acquire("watchdog precondition test"))
            val target=ProgrammingWireTarget()
            target.wdtRunning=args[0]!="lease-retired-reset-flag";target.wdtRunsWhileHalted=args[0]=="lease-watchdog-running"
            val lease=NrfInitialInstallLease(JlinkInstallWire(target,{token.checkCurrent()}),token)
            check(runCatching{lease.open(TargetIdentity(0x12345678,0xabcdef01,0x41414430),allowResetCatch=args[0]=="lease-retired-reset-flag")}.isFailure)
            check(target.memoryWrites.isEmpty()&&target.resetCount==0);lease.finish();token.close()
        }
        "lease-before-cancel","lease-after-cancel","lease-happy","lease-wdt","lease-control","lease-ready","lease-posthalt-mode","lease-posthalt-busy","lease-cross-boundary","lease-mid-batch-cancel","lease-batch-uid","lease-ff-words" -> {
            val token=checkNotNull(DkUsbOperationGate.acquire("test lease"))
            val target=ProgrammingWireTarget();var cancelled=false;var clock=0L
            val wire=JlinkInstallWire(target,{token.checkCurrent()})
            if(args[0]=="lease-wdt"){target.wdtRunning=true;target.wdtRunsWhileHalted=true}
            if(args[0]=="lease-control")target.debugControl=5
            if(args[0]=="lease-posthalt-mode")target.onMemoryWrite={address,value->if(address==0xe000edf0L&&value and 3==3L)target.mode=1}
            if(args[0]=="lease-posthalt-busy")target.onMemoryWrite={address,value->if(address==0xe000edf0L&&value and 3==3L)target.neverReady=true}
            if(args[0]=="lease-mid-batch-cancel")target.onMemoryWrite={address,_->if(address==0x1000L)cancelled=true}
            if(args[0]=="lease-batch-uid")target.onMemoryWrite={address,_->if(address==0x1000L)target.uid0=target.uid0 xor 1}
            val identity=TargetIdentity(0x12345678,0xabcdef01,0x41414430)
            val lease=NrfInitialInstallLease(wire,token,{cancelled},{clock.also{clock+=10_000_000}})
            if(args[0] in setOf("lease-wdt","lease-control","lease-posthalt-mode","lease-posthalt-busy")) {
                check(runCatching{lease.open(identity)}.isFailure)
                if(args[0] in setOf("lease-wdt","lease-control"))check(target.memoryWrites.isEmpty())
                else check(target.memoryWrites.none{it.first==0x4001e504L||it.first==0x4001e508L})
                lease.finish();token.close();return
            }
            lease.open(identity);check(target.halted)
            val hash="00".repeat(32);val binding=InstallBinding(identity,hash,hash,hash,hash,hash,hash,hash)
            val session=lease.authorizer(binding).acquire(binding)
            when(args[0]) {
        "restore-mode1","restore-paused-watchdog","restore-running-watchdog","restore-bad-uicr","restore-wrong-uid","restore-acl","restore-acl-watchdog" -> originalRestoreLeaseProbe(args[0])
        "resume-mode1","resume-mode2","resume-cancel","resume-bad-uicr","resume-mode-ack-loss","resume-unconfirmed" -> resumeLeaseProbe(args)
                "lease-cross-boundary"->{val before=target.events.size;check(runCatching{session.program(0x3f0,ByteArray(256),token.generation)}.isFailure);check(target.events.size==before)}
                "lease-ff-words"->{session.program(0x1000,ByteArray(8){0xff.toByte()},token.generation);check(target.memoryWrites.none{it.first in 0..0xfffffL})}
                "lease-mid-batch-cancel","lease-batch-uid"->{
                    check(runCatching{session.program(0x1000,ByteArray(256),token.generation)}.isFailure)
                    val writes=target.memoryWrites.count{it.first in 0..0xfffffL};check(writes in 1..64)
                    if(args[0]=="lease-mid-batch-cancel")check(writes==1)
                    check(target.mode==1) // Boundary identity failure/cancel issues no next NVMC mutation.
                }
                "lease-before-cancel"->{cancelled=true;check(runCatching{session.check(token.generation,identity)}.isFailure)}
                "lease-after-cancel"->{session.erasePage(0x1000,token.generation);cancelled=true;val n=target.memoryWrites.size;check(runCatching{session.program(0x1000,byteArrayOf(1,2,3,4),token.generation)}.isFailure);check(target.memoryWrites.size==n)}
                "lease-ready"->{target.neverReady=true;check(runCatching{session.erasePage(0x1000,token.generation)}.isFailure);check(target.memoryWrites.none{it.first==0x4001e508L})}
                "lease-happy"->{session.erasePage(0x1000,token.generation);session.program(0x1000,byteArrayOf(1,2,3,4),token.generation);check(session.readFlash(0x1000,4).contentEquals(byteArrayOf(1,2,3,4)))}
            }
            session.close();val cleanupWrites=target.memoryWrites.size;val cleanup=runCatching{lease.finish()}
            if(args[0]=="lease-batch-uid"){check(cleanup.isFailure&&target.memoryWrites.size==cleanupWrites)}else cleanup.getOrThrow()
            check(target.halted==(args[0] !in setOf("lease-before-cancel","lease-cross-boundary")))
            token.close()
        }
        "wire-policy" -> {
            val target=ProgrammingWireTarget();val wire=JlinkInstallWire(target)
            wire.initialize()
            check(wire.readWords(0x10000100L,4).contentEquals(byteArrayOf(0x40,0x28,5,0)))
            val traffic=target.events.size
            for(call in listOf<()->Unit>({wire.readWords(0x4001e50c,4)}, {wire.readWords(0x3fc,8)},
                {wire.programFlashWords(0x3f0,ByteArray(256))},
                {wire.eraseFlashPage(0x100000)},{wire.programFlashWords(0x10001000,byteArrayOf(0,0,0,0))},
                {wire.setNvmcMode(3)},{wire.writeDebugControl(0xa05f0005L)}))check(runCatching(call).isFailure)
            check(target.events.size==traffic)
            wire.writeDebugControl(0xa05f0003L);wire.setNvmcMode(2);wire.eraseFlashPage(0x1000)
            wire.setNvmcMode(1);wire.programFlashWords(0x1000,byteArrayOf(1,2,3,4));wire.setNvmcMode(0)
            check(wire.readWords(0x1000,4).contentEquals(byteArrayOf(1,2,3,4)))
            check(target.memoryWrites.none{it.first in 0x10001000L..0x10001fffL||it.first==0x4001e50cL})
        }
        "wire-wait" -> {
            val target=ProgrammingWireTarget();val wire=JlinkInstallWire(target);wire.initialize()
            target.inject(true,false,12,2)
            check(runCatching{wire.writeDebugControl(0xa05f0003L)}.isFailure)
            check(target.dummyWrites==1&&target.memoryWrites.none{it.first==0xe000edf0L}) // No replay of a queued mutation.
            check(target.apModes.all{it})
            val before=target.memoryWrites.size;target.inject(true,false,12,4)
            check(runCatching{wire.writeDebugControl(0xa05f0003L)}.isFailure)
            check(target.memoryWrites.size==before)
        }
        "wire-posted-read" -> {
            val target=ProgrammingWireTarget();for(i in 0 until 512)target.flash[i]=i.toByte()
            val wire=JlinkInstallWire(target);wire.initialize()
            target.inject(true,true,12,2,skip=3)
            check(wire.readWords(0,512).contentEquals(target.flash.copyOfRange(0,512)))
            check(target.events.count{it=="line-reset"}==2)
            target.corruptReadParity=true
            check(runCatching{wire.readWords(0,4)}.isFailure)
        }
        "gate" -> {
            val lease=checkNotNull(DkUsbOperationGate.acquire("first installation"))
            check(DkUsbOperationGate.acquire("watch")==null)
            lease.checkCurrent();val old=lease.generation
            val denied=AtomicInteger();val start=CountDownLatch(1)
            val threads=(0..7).map{Thread{start.await();if(DkUsbOperationGate.acquire("probe")==null)denied.incrementAndGet()}.also{it.start()}}
            start.countDown();threads.forEach{it.join()};check(denied.get()==8)
            lease.close();lease.close()
            check(runCatching{lease.checkCurrent()}.isFailure)
            val next=checkNotNull(DkUsbOperationGate.acquire("backup"));check(next.generation>old)
            lease.close();check(DkUsbOperationGate.acquire("another")==null)
            next.close();checkNotNull(DkUsbOperationGate.acquire("new")).close()
        }
        else -> error("Unknown programming test")
    }
}
