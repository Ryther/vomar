package org.openvimar.updater.ble

import android.Manifest
import android.annotation.SuppressLint
import android.bluetooth.*
import android.bluetooth.le.*
import android.content.*
import android.content.pm.PackageManager
import android.location.LocationManager
import android.os.Build
import android.os.ParcelUuid
import java.util.UUID
import java.util.Locale
import java.util.concurrent.atomic.AtomicBoolean

/** Public Android APIs only. Registrations own their callback/receiver, never global discovery. */
@SuppressLint("MissingPermission")
internal class AndroidPairingPlatform(private val context:Context):PairingPlatform<BluetoothDevice> {
 private val smpService=ParcelUuid(UUID.fromString("8d53dc1d-1db7-4cd3-868b-8a527460aa84"))
 private val nearbySmp=LinkedHashSet<String>()
 override fun nearbySmpAddresses():List<String> = synchronized(nearbySmp){nearbySmp.toList()}
 private fun adapter():BluetoothAdapter=context.getSystemService(BluetoothManager::class.java)?.adapter ?: error("Bluetooth is unavailable on this phone")
 override fun checkAvailable(){
  val permissions=if(Build.VERSION.SDK_INT>=31)listOf(Manifest.permission.BLUETOOTH_SCAN,Manifest.permission.BLUETOOTH_CONNECT) else listOf(Manifest.permission.ACCESS_FINE_LOCATION)
  check(permissions.all{context.checkSelfPermission(it)==PackageManager.PERMISSION_GRANTED}){"Bluetooth permissions are missing. Allow scanning and connections in Android app settings."}
  check(adapter().isEnabled){"Bluetooth is off. Turn it on and retry."}
  if(Build.VERSION.SDK_INT<31)check(context.getSystemService(LocationManager::class.java)?.isProviderEnabled(LocationManager.NETWORK_PROVIDER)==true || context.getSystemService(LocationManager::class.java)?.isProviderEnabled(LocationManager.GPS_PROVIDER)==true){"Android location is off. Turn it on in Settings and retry; this Android version requires it for Bluetooth discovery."}
 }
 private fun receiver(filter:IntentFilter,receive:(Intent)->Unit):AutoCloseable {
  val owned=object:BroadcastReceiver(){override fun onReceive(context:Context,intent:Intent){receive(intent)}}
  // Bluetooth broadcasts can originate from the privileged Bluetooth process, not the system UID.
  if(Build.VERSION.SDK_INT>=33)context.registerReceiver(owned,filter,Context.RECEIVER_EXPORTED) else context.registerReceiver(owned,filter)
  val closed=AtomicBoolean(false)
  return AutoCloseable{if(closed.compareAndSet(false,true))context.unregisterReceiver(owned)}
 }
 override fun startScan(address:String,onResult:(Result<DiscoveredPeer<BluetoothDevice>>)->Unit):AutoCloseable {
  val trace=BleDiagnostics.token(address)
  trace?.let{BleDiagnostics.scanStarted(it)}
  checkAvailable()
  synchronized(nearbySmp){nearbySmp.clear()}
  val scanner=adapter().bluetoothLeScanner ?: error("Bluetooth scanning is unavailable. Check that Bluetooth is on.")
  val callback=object:ScanCallback(){
   override fun onScanResult(callbackType:Int,result:ScanResult){
    try{
     val peer=result.device
     if(peer.address.equals(address,true)){trace?.let{BleDiagnostics.foundExpected(it)};onResult(Result.success(DiscoveredPeer(peer.address,peer)))}
     else if(result.scanRecord?.serviceUuids?.contains(smpService)==true){
      synchronized(nearbySmp){if(nearbySmp.size<4)nearbySmp.add(peer.address)}
     }
    }catch(e:SecurityException){trace?.let{BleDiagnostics.error(it,BleDiagnostics.Stage.SCAN)};onResult(Result.failure(IllegalStateException("Bluetooth permissions were revoked during scanning",e)))}
   }
   override fun onBatchScanResults(results:MutableList<ScanResult>){results.forEach{onScanResult(0,it)}}
   override fun onScanFailed(errorCode:Int){trace?.let{BleDiagnostics.error(it,BleDiagnostics.Stage.SCAN,errorCode)};onResult(Result.failure(IllegalStateException("Bluetooth scanning failed. Wait a few seconds and retry.\nTechnical detail: scan error $errorCode.")))}
  }
  val state=receiver(IntentFilter(BluetoothAdapter.ACTION_STATE_CHANGED)){intent ->
   trace?.let{BleDiagnostics.adapter(it,intent.getIntExtra(BluetoothAdapter.EXTRA_STATE,BluetoothAdapter.ERROR))}
   if(intent.getIntExtra(BluetoothAdapter.EXTRA_STATE,BluetoothAdapter.ERROR)!=BluetoothAdapter.STATE_ON)onResult(Result.failure(IllegalStateException("Bluetooth turned off during discovery. Turn it on and retry.")))
  }
  try{scanner.startScan(listOf(
   ScanFilter.Builder().setDeviceAddress(address.uppercase(Locale.US)).build(),
   ScanFilter.Builder().setServiceUuid(smpService).build()
  ),ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(),callback)}catch(t:Throwable){trace?.let{BleDiagnostics.error(it,BleDiagnostics.Stage.SCAN)};state.close();throw t}
  val closed=AtomicBoolean(false)
  return AutoCloseable{if(closed.compareAndSet(false,true))try{scanner.stopScan(callback)}catch(_:SecurityException){/* Revocation prevents stop; receiver still must be removed. */}finally{state.close()}}
 }
 override fun bondState(peer:BluetoothDevice):BondState {
  val state=when(peer.bondState){BluetoothDevice.BOND_BONDED->BondState.BONDED;BluetoothDevice.BOND_BONDING->BondState.BONDING;else->BondState.NONE}
  BleDiagnostics.token(peer.address)?.let{BleDiagnostics.observedBond(it,state)}
  return state
 }
 override fun createBond(peer:BluetoothDevice):Boolean {
  val trace=BleDiagnostics.token(peer.address)
  try{return peer.createBond().also{accepted->trace?.let{BleDiagnostics.createBond(it,accepted)}}}
  catch(t:Throwable){trace?.let{BleDiagnostics.error(it,BleDiagnostics.Stage.BOND)};throw t}
 }
 override fun observeBond(peer:BluetoothDevice,onState:(Result<BondEvent>)->Unit):AutoCloseable {
  val trace=BleDiagnostics.token(peer.address)
  val filter=IntentFilter(BluetoothDevice.ACTION_BOND_STATE_CHANGED).apply{addAction(BluetoothAdapter.ACTION_STATE_CHANGED);addAction(BluetoothDevice.ACTION_PAIRING_REQUEST)}
  return receiver(filter){intent ->
   try{
    if(intent.action==BluetoothAdapter.ACTION_STATE_CHANGED){
     trace?.let{BleDiagnostics.adapter(it,intent.getIntExtra(BluetoothAdapter.EXTRA_STATE,BluetoothAdapter.ERROR))}
     if(intent.getIntExtra(BluetoothAdapter.EXTRA_STATE,BluetoothAdapter.ERROR)!=BluetoothAdapter.STATE_ON)onState(Result.failure(IllegalStateException("Bluetooth turned off during pairing. Turn it on and retry.")))
    }else{
     @Suppress("DEPRECATION") val changed=intent.getParcelableExtra<BluetoothDevice>(BluetoothDevice.EXTRA_DEVICE)
     if(changed!=null && changed.address.equals(peer.address,true)){
      if(intent.action==BluetoothDevice.ACTION_PAIRING_REQUEST){
       // Never read EXTRA_PAIRING_KEY or dump the Intent/Bundle.
       trace?.let{BleDiagnostics.pairing(it,if(intent.hasExtra(BluetoothDevice.EXTRA_PAIRING_VARIANT))intent.getIntExtra(BluetoothDevice.EXTRA_PAIRING_VARIANT,BluetoothDevice.ERROR) else null)}
       return@receiver
      }
      // This AOSP extra is not a public SDK contract; absent on some implementations.
      val reasonKey="android.bluetooth.device.extra.REASON"
      trace?.let{BleDiagnostics.bond(it,
       intent.getIntExtra(BluetoothDevice.EXTRA_PREVIOUS_BOND_STATE,BluetoothDevice.ERROR),
       intent.getIntExtra(BluetoothDevice.EXTRA_BOND_STATE,BluetoothDevice.ERROR),peer.bondState,
       if(intent.hasExtra(reasonKey))intent.getIntExtra(reasonKey,BluetoothDevice.ERROR) else null)}
      // Re-read actual state instead of trusting exported receiver payloads.
      onState(Result.success(BondEvent(changed.address,bondState(peer))))
     }
    }
   }catch(e:SecurityException){trace?.let{BleDiagnostics.error(it,BleDiagnostics.Stage.BOND)};onState(Result.failure(IllegalStateException("Bluetooth permissions were revoked during pairing",e)))}
  }
 }
}
