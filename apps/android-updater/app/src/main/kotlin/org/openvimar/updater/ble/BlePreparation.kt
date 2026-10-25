package org.openvimar.updater.ble

import kotlinx.coroutines.*

enum class BondState { NONE, BONDING, BONDED }
internal data class DiscoveredPeer<P>(val address:String,val peer:P)
internal data class BondEvent(val address:String,val state:BondState)
/** Direct Android API seam; policy below is also used by the real gateway. */
internal interface PairingPlatform<P> {
 fun nearbySmpAddresses():List<String> = emptyList()
 fun checkAvailable()
 fun startScan(address:String,onResult:(Result<DiscoveredPeer<P>>)->Unit):AutoCloseable
 fun bondState(peer:P):BondState
 fun observeBond(peer:P,onState:(Result<BondEvent>)->Unit):AutoCloseable
 fun createBond(peer:P):Boolean
}
internal class BlePreparation<P>(private val platform:PairingPlatform<P>,private val scanTimeout:Long=20_000,private val bondTimeout:Long=90_000) {
 @Volatile private var active:Job?=null
 fun close(){active?.cancel(CancellationException("Bluetooth preparation stopped"))}
 /** Observe pairing before native initialization; the native manager owns its initial bond request. */
 suspend fun connectLeFirst(address:String,initialize:suspend(P)->Unit):P=runPreparation(address,initialize)
 suspend fun prepare(address:String):P=runPreparation(address,null)
 private suspend fun runPreparation(address:String,initialize:(suspend(P)->Unit)?):P=coroutineScope {
  val job=currentCoroutineContext().job
  check(active==null){"Bluetooth preparation is already in progress"};active=job
  try {
   platform.checkAvailable()
   val found=CompletableDeferred<P>()
   val scan=platform.startScan(address){result -> result.fold({if(it.address.equals(address,true))found.complete(it.peer)},{found.completeExceptionally(it)})}
   val peer=try {withTimeoutOrNull(scanTimeout){found.await()} ?: run {platform.checkAvailable();val nearby=platform.nearbySmpAddresses().take(4)
    val diagnostic=if(nearby.isEmpty()) "no other recovery-service device was found" else "other recovery-service addresses (diagnostic only): ${nearby.joinToString()}"
    error("Device not reachable. Turn on Bluetooth on the selected dimmer, move the phone closer and retry.\nTechnical detail: expected $address; $diagnostic.")}}finally{scan.close()}
   platform.checkAvailable()
   if(initialize!=null || platform.bondState(peer)!=BondState.BONDED){
    val bonded=CompletableDeferred<Unit>()
    val failure=CompletableDeferred<Nothing>()
    val observer=platform.observeBond(peer){result -> result.fold({event ->
     if(event.address.equals(address,true))when(event.state){
      BondState.BONDED->bonded.complete(Unit)
      BondState.NONE->{
       val cause=IllegalStateException("Android pairing failed or was cancelled. Complete the system request if it appears, then retry. If this continues, export the report.")
       bonded.completeExceptionally(cause);failure.completeExceptionally(cause)
      }
      BondState.BONDING->Unit
     }
    },{bonded.completeExceptionally(it);failure.completeExceptionally(it)})}
    try {
     // Read again after receiver registration to close the state-change race.
     when(platform.bondState(peer)){
      BondState.BONDED->bonded.complete(Unit)
      BondState.BONDING->Unit
      BondState.NONE->if(initialize==null)check(platform.createBond(peer)){"Android pairing did not start. Check that Bluetooth is on and retry."}
     }
     coroutineScope {
      // A hard bond failure interrupts an initialization waiting for authenticated CCC access.
      val watcher=launch(start=CoroutineStart.UNDISPATCHED){failure.await()}
      try {
       initialize?.invoke(peer)
       platform.checkAvailable()
       if(platform.bondState(peer)==BondState.BONDED)bonded.complete(Unit)
       val remaining=if(initialize==null)bondTimeout else minOf(bondTimeout,5_000)
       withTimeoutOrNull(remaining){bonded.await();true} ?: run {platform.checkAvailable();error("Android pairing timed out. Complete the system request and retry.")}
      }finally{watcher.cancel()}
     }
    }finally{observer.close()}
   }
   platform.checkAvailable()
   check(platform.bondState(peer)==BondState.BONDED){"Android pairing was lost before connecting. Retry; if this continues, export the report."}
   peer
  }finally{if(active===job)active=null}
 }
}
