package org.openvimar.updater

/** Retains an existing command only; a service intent can never start/replay a read. */
internal class HistoryServiceLifetime {
 private var retainedStartId:Int?=null
 @Synchronized fun keepAlive(startId:Int,ownerRunning:Boolean):Boolean {
  require(startId>0)
  if(ownerRunning)retainedStartId=startId
  return ownerRunning
 }
 /** Exact framework ID prevents a delayed idle event from stopping a newer start. */
 @Synchronized fun releaseOnIdle():Int?=retainedStartId.also{retainedStartId=null}
}
