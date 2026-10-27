package org.openvimar.updater

import org.junit.Assert.*
import org.junit.Test
import org.openvimar.updater.installer.OperationProgressTracker

class InstallProgressTest {
 @Test fun totalNeverRestartsAtPhaseBoundaryAndSkippedWorkAdvances(){
  var now=0L;val tracker=OperationProgressTracker(linkedMapOf("Check" to 1,"Write" to 6,"Verify" to 1,"Final" to 1)){now}
  val a=tracker.update("Check",100,100);assertEquals(111,a.permille)
  now=1000;val b=tracker.update("Write",1,100);assertTrue(b.permille>=a.permille)
  now=2000;val c=tracker.update("Final",1,100);assertTrue(c.permille>=888)
  assertTrue(tracker.update("Check",1,100).permille>=c.permille)
  assertEquals(1000,tracker.update("Final",100,100).permille)
 }
 @Test fun estimateNeedsMeasurementsAndRelearnsWhenPhaseChanges(){
  var now=0L;val tracker=OperationProgressTracker(linkedMapOf("Read" to 1,"Write" to 6)){now}
  assertNull(tracker.update("Read",0,100).remainingMillis)
  now=1000;assertNull(tracker.update("Read",10,100).remainingMillis)
  now=4000;val learned=tracker.update("Read",40,100);assertNotNull(learned.remainingMillis);assertTrue(learned.remainingMillis!!>0)
  now=5000;assertNull(tracker.update("Write",1,100).remainingMillis)
  now=9000;assertNotNull(tracker.update("Write",50,100).remainingMillis)
  now=30000;assertNull(tracker.update("Write",50,100).remainingMillis)
 }
 @Test fun usbPresenceChecksAreBoundedButFailureIsSticky(){
  var now=0L;var calls=0;var present=true
  val guard=DkUsbPresenceGuard({now}){calls++;check(present)}
  repeat(10000){guard.check()};assertEquals(1,calls)
  now=250_000_000;guard.check();assertEquals(2,calls)
  present=false;now=500_000_000;assertTrue(runCatching{guard.check()}.isFailure)
  present=true;assertTrue(runCatching{guard.check()}.isFailure)
 }
 @Test fun invalidWorkAndUnknownStagesCannotProduceAnEstimate(){
  for(stages in listOf(emptyMap(),mapOf("Read" to 0),mapOf("Read" to -1),linkedMapOf("Read" to 2,"Write" to -1))){
   assertThrows(IllegalArgumentException::class.java){OperationProgressTracker(stages)}
  }
  val tracker=OperationProgressTracker(mapOf("Read" to 1))
  for((done,size) in listOf(0 to 0,-1 to 100,101 to 100)){
   assertThrows(IllegalArgumentException::class.java){tracker.update("Read",done,size)}
  }
  assertThrows(IllegalArgumentException::class.java){tracker.update("Unreviewed stage",1,100)}
 }
 @Test fun stalledOrImplausiblySlowMeasurementsDoNotCreateACountdown(){
  var now=0L;val tracker=OperationProgressTracker(mapOf("Read" to 1)){now}
  assertNull(tracker.update("Read",0,100).remainingMillis)
  now=3000;assertNull(tracker.update("Read",0,100).remainingMillis)
  now=8L*24*60*60*1000
  val tooSlow=tracker.update("Read",1,100)
  assertNull(tooSlow.remainingMillis);assertEquals(10,tooSlow.permille)
  assertEquals(0L,tracker.update("Read",100,100).remainingMillis)
 }
}
