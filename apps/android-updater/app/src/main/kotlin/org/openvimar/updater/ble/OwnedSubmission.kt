package org.openvimar.updater.ble

/**
 * Serializes synchronous enqueue with release of one captured manager.
 * close blocks later submissions. Reentrant close during enqueue defers release until enqueue
 * returns (including exceptional return), so no connection can be queued after its final release.
 */
internal class OwnedSubmission(private val release:()->Unit) {
 private val lock=Any()
 private var closed=false
 private var submitting=0
 private var released=false
 fun submit(block:()->Unit):Boolean=synchronized(lock){
  if(closed)return@synchronized false
  submitting++
  try {block();true} finally {submitting--;releaseIfClosed()}
 }
 fun close()=synchronized(lock){closed=true;releaseIfClosed()}
 private fun releaseIfClosed(){if(closed && submitting==0 && !released){released=true;release()}}
}
