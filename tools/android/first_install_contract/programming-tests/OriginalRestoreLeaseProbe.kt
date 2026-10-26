package org.openvimar.updater

import org.openvimar.installer.*
import org.openvimar.updater.installer.*
import java.time.Instant

internal fun originalRestoreLeaseProbe(scenario:String){
 val target=ProgrammingWireTarget();target.logLimit=10000
 byteArrayOf(0,0,2,0x20,1,0x10,0,0).copyInto(target.flash)
 val token=checkNotNull(DkUsbOperationGate.acquire("synthetic original restore"));val wire=JlinkInstallWire(target,{token.checkCurrent()});wire.initialize()
 val ficr=ByteArray(4096);for(at in ficr.indices step 512)wire.readWords(0x10000000L+at,512).copyInto(ficr,at)
 val regions=mapOf("flash.bin" to target.flash.copyOf(),"ficr.bin" to ficr,"uicr.bin" to ByteArray(4096){0xff.toByte()})
 val raw=QuiescentArchive.create(regions,regions,QuiescentProvenance("synthetic","synthetic",3300,0x1366,0x1060,4,0x85,3),Instant.parse("2026-10-23T12:00:00Z"),Instant.parse("2026-10-23T12:01:00Z"),0,false)
 val original=OriginalArchive.verify(raw);val plan=OriginalRestorePlan.review(original,"ef1faf4b-cd24-42c7-8508-8d51b4f10ad5",token.generation)
 target.mode=1
 if(scenario=="restore-bad-uicr")target.corruptUicr=true
 if(scenario=="restore-wrong-uid")target.uid0=target.uid0 xor 1
 if(scenario in setOf("restore-paused-watchdog","restore-running-watchdog")){target.wdtRunning=true;target.wdtConfig=if(scenario=="restore-running-watchdog")9 else 1;target.wdtCrv=0x50000;target.wdtRren=1}
 if(scenario in setOf("restore-acl","restore-acl-watchdog")){target.flashAcl[7][0]=0xf8000;target.flashAcl[7][1]=4096;target.flashAcl[7][2]=2}
 if(scenario=="restore-acl-watchdog"){target.wdtRunning=true;target.wdtConfig=1;target.wdtCrv=0x50000;target.wdtRren=1}
 val lease=NrfInitialInstallLease(wire,token)
 val result=runCatching{lease.openForOriginalRestore(original.identity,plan)}
 val good=scenario in setOf("restore-mode1","restore-paused-watchdog","restore-acl","restore-acl-watchdog")
 check(result.isSuccess==good){result.toString()}
 if(scenario in setOf("restore-acl","restore-acl-watchdog")){
  check(target.resetCount==0)
  val session=lease.authorizer(plan.binding).acquire(plan.binding)
  session.erasePage(4096,token.generation);check(target.resetCount==1&&target.stockInstructions==0&&target.halted)
  session.program(4096,byteArrayOf(1,2,3,4),token.generation);session.erasePage(8192,token.generation)
  check(target.resetCount==1&&lease.programmingPreparation?.contains("UID/FICR/UICR/watchdog unchanged")==true)
  session.close()
 }
 lease.finish()
 if(good){check(target.halted&&lease.haltRetentionRequired&&target.mode==0);check(lease.authorizerAfterFinishFails(plan))}
 if(scenario=="restore-bad-uicr")check(target.halted&&target.memoryWrites.none{it.first==0x4001e504L})
 if(scenario in setOf("restore-wrong-uid","restore-running-watchdog"))check(target.memoryWrites.isEmpty())
 if(scenario !in setOf("restore-acl","restore-acl-watchdog"))check(target.memoryWrites.none{it.first in 0L..0xfffffL||it.first==0x4001e508L})
 check(target.memoryWrites.none{it.first in 0x4001e800L..0x4001e87fL||it.first in 0x10001000L..0x10001fffL})
 check(target.resetCount==if(scenario in setOf("restore-acl","restore-acl-watchdog"))1 else 0);token.close()
}
private fun NrfInitialInstallLease.authorizerAfterFinishFails(plan:OriginalRestorePlan)=runCatching{authorizer(plan.binding)}.isFailure
