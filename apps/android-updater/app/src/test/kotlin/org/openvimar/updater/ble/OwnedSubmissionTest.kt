package org.openvimar.updater.ble

import kotlinx.coroutines.*
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

class OwnedSubmissionTest {
 @Test fun cancellationBeforeConnectSubmissionNeverConnects(){
  var released=0;var connected=0
  val owner=OwnedSubmission{released++}
  owner.close() // invokeOnCancellation may run synchronously during registration
  assertFalse(owner.submit{connected++})
  assertEquals(0,connected);assertEquals(1,released)
 }
 @Test fun cancellationBeforeResetSubmissionNeverSends(){
  var sends=0;val owner=OwnedSubmission{}
  owner.close();owner.submit{sends++};assertEquals(0,sends)
 }
 @Test fun reentrantCancellationDuringConnectReleasesAfterSubmissionReturns(){
  val events=mutableListOf<String>();lateinit var owner:OwnedSubmission
  owner=OwnedSubmission{events+="release"}
  owner.submit{events+="begin";owner.close();events+="queued"}
  assertEquals(listOf("begin","queued","release"),events)
  assertFalse(owner.submit{fail("released connection cannot enqueue more commands")})
  owner.close();assertEquals(1,events.count{it=="release"})
 }
 @Test fun throwingSubmissionStillReleasesCapturedOwner(){
  var released=0;val owner=OwnedSubmission{released++}
  try{owner.submit{owner.close();error("send failed")};fail()}catch(_:IllegalStateException){}
  assertEquals(1,released)
 }
 @Test fun concurrentCloseCannotReleaseBeforeEnqueueFinishes(){
  val entered=CountDownLatch(1);val finish=CountDownLatch(1);val done=CountDownLatch(1)
  val events=java.util.Collections.synchronizedList(mutableListOf<String>())
  val owner=OwnedSubmission{events+="release"}
  val sending=Thread{owner.submit{entered.countDown();check(finish.await(2,TimeUnit.SECONDS));events+="queued"}}
  sending.start();assertTrue(entered.await(2,TimeUnit.SECONDS))
  val closing=Thread{owner.close();done.countDown()};closing.start()
  finish.countDown();sending.join(2000);assertTrue(done.await(2,TimeUnit.SECONDS));closing.join(2000)
  assertEquals(listOf("queued","release"),events)
 }
 @Test fun alreadyCancelledContinuationDoesNotSubmitAfterHandlerRegistration()=runBlocking {
  var released=0;var connected=0;val owner=OwnedSubmission{released++}
  val task=launch(start=CoroutineStart.UNDISPATCHED){
   currentCoroutineContext().job.cancel()
   suspendCancellableCoroutine<Unit>{c -> c.invokeOnCancellation{owner.close()};owner.submit{connected++}}
  }
  task.join();assertEquals(0,connected);assertEquals(1,released)
 }
 @Test fun continuationCancellationInsideSendReleasesAfterSendReturns()=runBlocking {
  val events=mutableListOf<String>();val owner=OwnedSubmission{events+="release"}
  val task=launch(start=CoroutineStart.UNDISPATCHED){suspendCancellableCoroutine<Unit>{c ->
   c.invokeOnCancellation{owner.close()}
   owner.submit{c.cancel();events+="queued"}
  }}
  task.join();assertEquals(listOf("queued","release"),events)
 }
}
