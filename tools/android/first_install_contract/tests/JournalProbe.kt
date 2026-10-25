package org.openvimar.installer

import java.nio.file.Path
import java.util.concurrent.CountDownLatch
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

internal fun journalProbe(directory:Path) {
    val hash="11".repeat(32)
    val binding=InstallBinding(TargetIdentity(0x11223344,0x55667788,0x41414430),hash,hash,hash,hash,hash,hash,hash)
    val initial=InstallJournalRecord(binding,1,InstallPhase.PREPARED,null,false,false)
    val start=CountDownLatch(1);val claims=AtomicInteger()
    val threads=(1..2).map{thread{start.await();if(FileInstallJournal(directory).begin(initial))claims.incrementAndGet()}}
    start.countDown();threads.forEach{it.join()};check(claims.get()==1)
    val store=FileInstallJournal(directory);check(store.load(binding.id)==initial)
    check(!store.begin(initial));check(store.load(binding.id)==initial)
    val next=initial.copy(sequence=2,phase=InstallPhase.PAGE_ERASE_INTENT,address=0,mutationMayHaveStarted=true)
    store.save(next);check(FileInstallJournal(directory).load(binding.id)==next)
    try{store.save(initial);error("Stale sequence replaced durable intent")}catch(_:IllegalArgumentException){}
    check(store.load(binding.id)==next)
}
