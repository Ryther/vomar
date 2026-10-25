package org.openvimar.updater.ble

/** Discards raw library messages; the diagnostic report accepts only typed metadata. */
internal object NordicGattTrace {
 private val connection=Regex("\\[Callback] Connection state changed with status: ([0-9]{1,5}) and new state: ([0-3]) \\((DISCONNECTED|CONNECTING|CONNECTED|DISCONNECTING)\\)")
 private val mtu=Regex("MTU changed to: ([0-9]{2,3})")
 private val authentication=Regex("Authentication required \\((5|8|137)\\)")
 fun capture(token:Long,message:String) {
  val phase=when(message) {
   "Services discovered"->BleDiagnostics.NativePhase.SERVICES_DISCOVERED
   "Requesting new MTU..."->BleDiagnostics.NativePhase.MTU_REQUESTED
   "Failed to negotiate MTU, disconnecting..."->BleDiagnostics.NativePhase.MTU_FAILED
   "Enabling notifications for da2e7828-fbce-4e01-ae9e-261174997c48"->BleDiagnostics.NativePhase.NOTIFICATIONS_REQUESTED
   "Notifications enabled"->BleDiagnostics.NativePhase.NOTIFICATIONS_ENABLED
   "gatt.disconnect()"->BleDiagnostics.NativePhase.LIBRARY_DISCONNECT_REQUESTED
   "gatt.close()"->BleDiagnostics.NativePhase.LIBRARY_GATT_CLOSED
   "Starting bonding..."->BleDiagnostics.NativePhase.BOND_REQUESTED
   "device.createBond()"->BleDiagnostics.NativePhase.BOND_CREATE_CALLED
   "Device bonded"->BleDiagnostics.NativePhase.BOND_ESTABLISHED
   "Bonding failed"->BleDiagnostics.NativePhase.BOND_FAILED
   else->null
  }
  if(phase!=null){BleDiagnostics.nativeGatt(token,phase);return}
  connection.matchEntire(message)?.let {
   val status=it.groupValues[1].toInt();if(status>65535)return
   BleDiagnostics.nativeGatt(token,BleDiagnostics.NativePhase.CONNECTION_STATE,status,it.groupValues[2].toInt());return
  }
  mtu.matchEntire(message)?.let {
   val value=it.groupValues[1].toInt();if(value in 23..517)BleDiagnostics.nativeGatt(token,BleDiagnostics.NativePhase.MTU_NEGOTIATED,mtu=value)
   return
  }
  authentication.matchEntire(message)?.let {
   BleDiagnostics.nativeGatt(token,BleDiagnostics.NativePhase.AUTHENTICATION_REQUIRED,status=it.groupValues[1].toInt())
  }
 }
}
