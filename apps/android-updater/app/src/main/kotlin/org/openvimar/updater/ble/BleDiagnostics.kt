package org.openvimar.updater.ble

import java.util.Locale

/** Bounded metadata only: never accepts an Intent, credential, payload, or exception message. */
internal object BleDiagnostics {
 enum class Stage { AVAILABILITY, SCAN, BOND, ADAPTER }
 enum class GattPhase { STARTED, READY, DEFERRED, FAILED, CLOSED }
 enum class NativePhase { CONNECTION_STATE, SERVICES_DISCOVERED, MTU_REQUESTED, MTU_NEGOTIATED,
  MTU_FAILED, NOTIFICATIONS_REQUESTED, AUTHENTICATION_REQUIRED, NOTIFICATIONS_ENABLED,
  LIBRARY_DISCONNECT_REQUESTED, LIBRARY_GATT_CLOSED, BOND_REQUESTED, BOND_CREATE_CALLED, BOND_ESTABLISHED, BOND_FAILED }
 private var sequence=0L
 private var address:String?=null
 private var owner=0L
 private val events=ArrayDeque<Map<String,Any?>>()
 @Synchronized fun begin(expectedAddress:String):Long {
  address=expectedAddress.uppercase(Locale.US);owner=++sequence;events.clear()
  append(owner,"attempt_started");return owner
 }
 @Synchronized fun token(expectedAddress:String):Long? = owner.takeIf{address==expectedAddress.uppercase(Locale.US)}
 @Synchronized fun snapshot(expectedAddress:String):List<Map<String,Any?>> =
  if(address==expectedAddress.uppercase(Locale.US))events.map{it.toMap()} else emptyList()
 @Synchronized private fun append(token:Long,type:String,vararg fields:Pair<String,Any?>) {
  if(token!=owner || address==null)return
  if(events.size==40)events.removeFirst()
  events.addLast(linkedMapOf<String,Any?>("event" to type,"attempt" to token,"atMillis" to System.currentTimeMillis(),*fields))
 }
 fun gatt(token:Long,phase:GattPhase)=append(token,"gatt","phase" to phase.name)
 fun nativeGatt(token:Long,phase:NativePhase,status:Int?=null,newState:Int?=null,mtu:Int?=null)=
  append(token,"native_gatt","phase" to phase.name,"status" to status,"newState" to newState,"mtu" to mtu)
 fun observedBond(token:Long,state:BondState)=append(token,"bond_observed","state" to state.name)
 fun scanStarted(token:Long)=append(token,"scan_started")
 @Synchronized fun foundExpected(token:Long){
  if(events.none{it["event"]=="scan_found_expected"})append(token,"scan_found_expected")
 }
 fun createBond(token:Long,accepted:Boolean)=append(token,"create_bond","accepted" to accepted)
 fun bond(token:Long,previous:Int,current:Int,actual:Int,reason:Int?)=append(token,"bond_state",
  "previous" to previous,"current" to current,"actual" to actual,"aospReasonBestEffortNonPublicContract" to reason)
 fun pairing(token:Long,variant:Int?)=append(token,"pairing_request","variant" to variant)
 fun adapter(token:Long,state:Int)=append(token,"adapter_state","state" to state)
 fun error(token:Long,stage:Stage,code:Int?=null)=append(token,"error","stage" to stage.name,"code" to code)
 fun bootHistory(token:Long,history:org.openvimar.updater.core.RecoveryBootHistory) {
  history.validate();append(token,"boot_history_validated","sequence" to history.sequence,"entryCount" to history.entries.size,
   "pendingReason" to history.pendingReason,"storageValid" to history.state.storageValid)
 }
}
