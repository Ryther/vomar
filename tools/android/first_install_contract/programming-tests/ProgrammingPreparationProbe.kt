package org.openvimar.updater

import org.openvimar.installer.*
import org.openvimar.updater.installer.*

/** Regression on the actual Kotlin wire/lease against independently modeled
 * volatile nRF52840 FLASH permissions. No USB or physical device access. */
internal fun programmingPreparationProbe(scenario:String,candidate:InspectedCommonCandidate?=null){
 val target=ProgrammingWireTarget();target.logLimit=2000
 if(scenario!="prepare-acl-empty-vectors")byteArrayOf(0,0,2,0x20,1,0x10,0,0).copyInto(target.flash)
 if(scenario=="prepare-acl-even-vector")target.flash.fill(0,4,8)
 target.faultOnProtectedErase=scenario=="prepare-acl-fault"
 val slot=if(scenario=="prepare-acl-upper")7 else 0
 if(scenario!="prepare-no-acl"){
  target.flashAcl[slot][0]=if(slot==7)0xf8000 else 0
  target.flashAcl[slot][1]=if(scenario=="prepare-acl-empty")0 else 4096
  target.flashAcl[slot][2]=if(scenario=="prepare-acl-read-denied")3 else 2
 }
 target.wrongResetPc=scenario=="prepare-acl-wrong-pc"
 target.wrongResetMsp=scenario=="prepare-acl-wrong-msp"
 target.retainAclOnReset=scenario=="prepare-acl-persistent"
 target.ignoreVectorCatch=scenario=="prepare-acl-uncaught"
 val identity=TargetIdentity(0x12345678,0xabcdef01,0x41414430)
 val token=checkNotNull(DkUsbOperationGate.acquire("synthetic programming preparation"))
 val hash="00".repeat(32);val binding=InstallBinding(identity,hash,candidate?.releaseSha256?:hash,candidate?.familySha256?:hash,hash,hash,hash,hash)
 var cancelled=false
 if(scenario=="prepare-acl-cancel")target.onMemoryWrite={at,_->if(at==0xe000ed0cL)cancelled=true}
 val handoff=if(scenario=="prepare-acl-watchdog"){
  target.wdtRunning=true;target.wdtCrv=327680;target.wdtRren=1
  checkNotNull(candidate).authorizeWatchdogHandoff(identity,token.generation)
 }else null
 var clock=0L
 val lease=NrfInitialInstallLease(JlinkInstallWire(target,{token.checkCurrent()}),token,{cancelled},{clock.also{clock+=10_000_000}})
 var completed=false
 try{
  lease.open(identity,watchdogHandoff=handoff)
  check(target.resetCount==0&&target.halted)
  val session=lease.authorizer(binding).acquire(binding)
  check(target.resetCount==0){"Read/acquire must not reset a target"}
  if(scenario=="prepare-acl-capture"){
   check(lease.readOriginalRegion("uicr.bin").all{it==0xff.toByte()})
   check(target.resetCount==0&&target.memoryWrites.none{it.first==0x4001e504L||it.first==0x4001e508L});session.close();completed=true;return
  }
  val before=target.flash.copyOf();val outcome=runCatching{session.erasePage(0,token.generation)}
  if(scenario in setOf("prepare-acl-persistent","prepare-acl-uncaught","prepare-acl-cancel","prepare-acl-read-denied","prepare-acl-wrong-pc","prepare-acl-wrong-msp")){
   check(outcome.isFailure){"Unconfirmed preparation must stop"}
   check(target.resetCount==if(scenario=="prepare-acl-read-denied")0 else 1){"Unexpected preparation reset count"}
   check(target.flash.contentEquals(before)&&target.memoryWrites.none{it.first==0x4001e504L||it.first==0x4001e508L||it.first in 0L..0xfffffL})
   check(lease.haltRetentionRequired)
  }else{
   outcome.getOrThrow()
   val expected=if(scenario in setOf("prepare-no-acl","prepare-acl-empty"))0 else 1
   check(target.resetCount==expected&&target.halted&&target.stockInstructions==0)
   if(expected==1)check(lease.resetCatchUsed&&target.flashAcl.all{it[1]==0L&&it[2]==0L})
   session.program(0,byteArrayOf(1,2,3,4),token.generation);session.erasePage(4096,token.generation)
   check(target.resetCount==expected&&target.flash.copyOfRange(0,4).contentEquals(byteArrayOf(1,2,3,4)))
   if(handoff!=null)check(target.wdtRunning&&target.wdtConfig==1L&&target.wdtCrv==327680L&&target.wdtRren==1L)
  }
  check(target.memoryWrites.none{it.first in 0x4001e800L..0x4001e87fL||it.first in 0x10001000L..0x10001fffL})
  session.close();completed=true
 }finally{try{if(completed)lease.finish() else runCatching{lease.finish()}}finally{token.close()}}
}
