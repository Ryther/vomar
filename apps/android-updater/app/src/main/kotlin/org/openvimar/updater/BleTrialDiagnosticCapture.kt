package org.openvimar.updater

/** Diagnostic ownership follows one admitted trial, independently of the next radio owner. */
internal class BleTrialDiagnosticCapture {
 private var address:String?=null
 private var previousToken:Long?=null
 var events:List<Map<String,Any?>> = emptyList();private set
 fun begin(){address=null;previousToken=null;events=emptyList()}
 fun target(address:String){this.address=address;previousToken=org.openvimar.updater.ble.BleDiagnostics.token(address)}
 fun finish() {
  val target=address ?: return
  if(org.openvimar.updater.ble.BleDiagnostics.token(target)!=previousToken)
   events=org.openvimar.updater.ble.BleDiagnostics.snapshot(target)
 }
}
