package org.openvimar.updater.ble

import android.Manifest
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import io.runtime.mcumgr.*
import io.runtime.mcumgr.ble.McuMgrBleTransport
import io.runtime.mcumgr.ble.exception.McuMgrDisconnectedException
import io.runtime.mcumgr.exception.*
import io.runtime.mcumgr.managers.*
import io.runtime.mcumgr.response.McuMgrResponse
import kotlinx.coroutines.*
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import org.openvimar.updater.core.TransportDisconnected

/** Owns one Nordic manager. System pairing UI is the sole pairing authority. */
internal class AndroidBleGateway(context:Context,private val address:String):BleGateway {
 private val context=context.applicationContext
 private var device:BluetoothDevice?=null
 private val lifecycle=Any()
 private var transport:McuMgrBleTransport?=null
 private var owner:OwnedSubmission?=null
 private var imageManager:ImageManager?=null
 private var osManager:DefaultManager?=null
 private var identityManager:RuntimeIdentityManager?=null
 private var bootHistoryManager:RecoveryBootHistoryManager?=null
 private var migrationManager:MigrationBootManager?=null
 @Volatile private var generation=0
 @Volatile private var preparation:BlePreparation<BluetoothDevice>?=null
 private fun permission(){
  if(Build.VERSION.SDK_INT>=31) check(context.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT)==PackageManager.PERMISSION_GRANTED){"Bluetooth permission required"}
 }
 // permission() checks CONNECT; revocation races propagate SecurityException to the coordinator.
 @android.annotation.SuppressLint("MissingPermission")
 override fun checkReady(){permission();check(device?.bondState==BluetoothDevice.BOND_BONDED){"Android authenticated bond required; pair using system UI"};check(transport!=null){"Not connected"}}
 // permission() checks CONNECT before bond access/createBond; SecurityException pauses the run.
 @android.annotation.SuppressLint("MissingPermission")
 override suspend fun connect(address:String){
  check(address.equals(this.address,true)){"Unexpected BLE address"};close()
  val diagnosticToken=BleDiagnostics.begin(this.address)
  permission()
  val connectingGeneration=generation
  val pending=BlePreparation(AndroidPairingPlatform(context))
  preparation=pending
  try {
   val peer=pending.connectLeFirst(this.address){selected -> initializeNative(selected,connectingGeneration,diagnosticToken)}
   check(peer.address.equals(this.address,true)){"Unexpected BLE peer"}
   check(peer.bondState==BluetoothDevice.BOND_BONDED){"Android pairing was lost before connection"}
   synchronized(lifecycle){
    check(generation==connectingGeneration){"Bluetooth connection interrupted"}
    val owned=transport ?: error("Bluetooth connection closed")
    // Optional params ENOTSUP can overwrite Nordic's limit with zero; restore after readiness.
    owned.setMaxPacketLength(244)
    imageManager=ImageManager(owned).also{it.setUploadMtu(244)};osManager=DefaultManager(owned);identityManager=RuntimeIdentityManager(owned);migrationManager=MigrationBootManager(owned);bootHistoryManager=RecoveryBootHistoryManager(owned)
   }
   checkReady()
  }catch(t:Throwable){close();throw t}
  finally{if(preparation===pending)preparation=null}
 }
 /** Establish LE first, then explicitly pair before authenticated CCC initialization. */
 private suspend fun initializeNative(peer:BluetoothDevice,connectingGeneration:Int,diagnosticToken:Long){
  check(peer.address.equals(this.address,true)){"Unexpected BLE peer"}
  val initialBond=InitialBondQueue()
  var initializationFailure:Exception?=null
  val owned=object:McuMgrBleTransport(context,peer) {
   // McuMgr2.7.4 makes initialize() final. The pinned Ble2.11 callback's
   // initGatt queue is prepended to it, after discovery on the live LE link.
   // This avoids relying on CCC authentication to display pairing on Android16.
   @Suppress("DEPRECATION","OVERRIDE_DEPRECATION")
   override fun getGattCallback():BleManagerGattCallback=object:BleManagerGattCallback() {
    // Required service discovery and invalidation are owned by McuMgr's final
    // outer overrides. These are the same no-op defaults as BleManager2.11.
    override fun isRequiredServiceSupported(gatt:BluetoothGatt)=false
    override fun onServicesInvalidated(){}
    override fun initGatt(gatt:BluetoothGatt)=try{initialBondRequests(gatt)}catch(failure:Exception){
     // Native callbacks must report permission/target failures to the awaiting
     // connection, rather than throw on Android's callback thread.
     initializationFailure=failure;BleDiagnostics.error(diagnosticToken,BleDiagnostics.Stage.BOND);null
    }
   }
   @android.annotation.SuppressLint("MissingPermission") // connect() checked CONNECT; pre31 ADMIN is install-time.
   private fun initialBondRequests(gatt:BluetoothGatt):java.util.Deque<no.nordicsemi.android.ble.Request>? {
    permission();check(gatt.device.address.equals(this@AndroidBleGateway.address,true)){"Unexpected BLE peer"}
    val state=when(gatt.device.bondState){BluetoothDevice.BOND_BONDED->BondState.BONDED;BluetoothDevice.BOND_BONDING->BondState.BONDING;else->BondState.NONE}
    return initialBond.prepare(state){
     // Unlike ensureBond(), this never deletes an existing bond. Encrypted,
     // authenticated CCC access and checkReady() remain mandatory afterwards.
     createBondInsecure().fail{_,status->
      BleDiagnostics.error(diagnosticToken,BleDiagnostics.Stage.BOND,status)
      initializationFailure=IllegalStateException("Android pairing did not complete (native status $status). Save the trial report before retrying.")
     }
    }
   }
   // Observe only this library's whitelisted metadata. Never forward its raw
   // messages (which can contain CBOR, packet bytes or pairing data) to Logcat.
   override fun getMinLogPriority()=android.util.Log.VERBOSE
   override fun log(priority:Int,message:String){NordicGattTrace.capture(diagnosticToken,message)}
  }
  val capturedOwner=OwnedSubmission{BleDiagnostics.gatt(diagnosticToken,BleDiagnostics.GattPhase.CLOSED);owned.release()}
  synchronized(lifecycle){
   if(generation!=connectingGeneration){capturedOwner.close();error("Bluetooth connection interrupted")}
   device=peer;transport=owned;owner=capturedOwner
  }
  owned.setInitialMtu(247);owned.setMaxPacketLength(244)
  withTimeout(120_000){suspendCancellableCoroutine<Unit>{c ->
   val token=connectingGeneration
   c.invokeOnCancellation{capturedOwner.close();if(token==generation)close()}
   capturedOwner.submit{
    BleDiagnostics.gatt(diagnosticToken,BleDiagnostics.GattPhase.STARTED)
    owned.connect(object:McuMgrTransport.ConnectionCallback{
    override fun onConnected(){if(c.isActive && token==generation){
     val failure=initializationFailure
     if(failure!=null){BleDiagnostics.gatt(diagnosticToken,BleDiagnostics.GattPhase.FAILED);c.resumeWithException(failure)}
     else{BleDiagnostics.gatt(diagnosticToken,BleDiagnostics.GattPhase.READY);c.resume(Unit)}
    }}
    override fun onDeferred(){if(c.isActive && token==generation){BleDiagnostics.gatt(diagnosticToken,BleDiagnostics.GattPhase.DEFERRED);c.resumeWithException(IllegalStateException("Android deferred the Bluetooth connection. Wait a few seconds and retry the operation."))}}
    override fun onError(t:Throwable){if(c.isActive && token==generation){BleDiagnostics.gatt(diagnosticToken,BleDiagnostics.GattPhase.FAILED);c.resumeWithException(initializationFailure ?: classify(t))}}
   })}
  }}
 }
 private fun classify(t:Throwable):Throwable=if(t is McuMgrDisconnectedException) TransportDisconnected(t.message ?: "BLE disconnected") else t
 private suspend fun <T:McuMgrResponse> request(send:(McuMgrCallback<T>)->Unit):T {
  val capturedOwner=synchronized(lifecycle){owner} ?: error("Bluetooth connection closed")
  return withTimeout(125_000){
  suspendCancellableCoroutine {c ->
   val token=generation
   c.invokeOnCancellation{capturedOwner.close();if(token==generation)close()}
   capturedOwner.submit{send(object:McuMgrCallback<T>{
    override fun onResponse(response:T){if(c.isActive && token==generation){
     try {
      if(response is MigrationBootResponse)response.validateWire()
      if(response is RuntimeIdentityResponse)response.validateWire()
      if(response is RecoveryBootHistoryResponse)response.validateWire()
      if(response.isSuccess)c.resume(response) else if(response is RuntimeIdentityResponse)c.resumeWithException(response.rejection()) else if(response is MigrationBootResponse)c.resumeWithException(response.rejection()) else if(response is RecoveryBootHistoryResponse)c.resumeWithException(response.rejection()) else c.resumeWithException(IllegalStateException("The dimmer refused the Bluetooth request. Export the diagnostic report. Technical detail: rc=${response.rc}, group=${response.groupReturnCode}"))
     }catch(failure:Exception){c.resumeWithException(failure)}
    }}
    override fun onError(error:McuMgrException){if(c.isActive && token==generation)c.resumeWithException(classify(error))}
   })}
  }
 }
 }
 override suspend fun identity():org.openvimar.updater.core.RuntimeIdentity {
  checkReady();val manager=identityManager ?: error("Bluetooth identity manager unavailable")
  return try {request{cb:McuMgrCallback<RuntimeIdentityResponse> -> manager.read(cb)}.identity()}
  catch(e:org.openvimar.updater.core.IdentityCommandUnavailable){throw e}
  catch(e:org.openvimar.updater.core.TransportDisconnected){throw e}
  catch(e:CancellationException){throw e}
  catch(e:Exception){throw IllegalStateException("Runtime identity unavailable or unsupported by this legacy recovery; common release cannot be installed. "+e.message,e)}
 }
 override suspend fun identityV2():org.openvimar.updater.core.RuntimeIdentity {
  checkReady();val manager=identityManager ?: error("Bluetooth identity manager unavailable")
  return request{cb:McuMgrCallback<RuntimeIdentityV2Response> -> manager.readV2(cb)}.identity()
 }
 override suspend fun bootHistory():org.openvimar.updater.core.RecoveryBootHistory {
  checkReady();val manager=bootHistoryManager ?: error("Bluetooth boot-history manager unavailable")
  return request{cb:McuMgrCallback<RecoveryBootHistoryResponse> -> manager.read(cb)}.history()
 }
 override suspend fun images():List<Slot>{checkReady();val manager=imageManager ?: error("Bluetooth connection closed");val response=request{cb:McuMgrCallback<io.runtime.mcumgr.response.img.McuMgrImageStateResponse> -> manager.list(cb)}
  return response.images?.map{Slot(it.image,it.slot,it.hash?.joinToString(""){byte->"%02x".format(byte.toInt() and 255)},it.active,it.bootable,it.version)} ?: error("Missing image records")
 }
 override suspend fun chunk(data:ByteArray,offset:Int,image:Int):Chunk{checkReady();val manager=imageManager ?: error("Bluetooth connection closed");val response=request{cb:McuMgrCallback<io.runtime.mcumgr.response.img.McuMgrImageUploadResponse> -> manager.upload(data,offset,image,cb)};return Chunk(response.off,response.match)}
 override suspend fun reset(){checkReady();val manager=osManager ?: error("Bluetooth connection closed");try{request{cb:McuMgrCallback<io.runtime.mcumgr.response.dflt.McuMgrOsResponse> -> manager.reset(cb)}}catch(_:McuMgrTimeoutException){throw ResetResponseLost()}catch(t:TimeoutCancellationException){currentCoroutineContext().ensureActive();throw ResetResponseLost()}}
 override suspend fun bootMigration(hash:String):org.openvimar.updater.core.ResetAck {
  checkReady();val manager=migrationManager ?: error("Migration boot manager unavailable")
  return try{request{cb:McuMgrCallback<MigrationBootResponse> -> manager.boot(hash,cb)}.acknowledgement()}
  catch(_:McuMgrTimeoutException){throw ResetResponseLost()}
  catch(t:TimeoutCancellationException){currentCoroutineContext().ensureActive();throw ResetResponseLost()}
 }
 override fun close(){
  preparation?.close();preparation=null
  val capturedOwner=synchronized(lifecycle){
   generation++;val captured=owner;owner=null;transport=null;imageManager=null;osManager=null;identityManager=null;migrationManager=null;bootHistoryManager=null;device=null;captured
  }
  capturedOwner?.close()
 }
}
