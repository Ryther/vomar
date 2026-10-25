package org.openvimar.updater

/** A detached report snapshot has no executable firmware or approval authority. */
internal object BleTrialReport {
 fun snapshot(state:BleTrialState,address:String,digest:String?,version:String?,
     appVersion:String,androidApi:Int,androidRelease:String,diagnostics:List<Map<String,Any?>>):Map<String,Any?> =
  linkedMapOf("kind" to "single-device-ble-candidate-trial","candidateDigest" to digest,
   "firmwareVersion" to version,"address" to address,"status" to state.status,
   "resetAcknowledged" to state.acknowledged,"appVersion" to appVersion,"androidApi" to androidApi,
   "androidRelease" to androidRelease,"bleDiagnostic" to diagnostics.map{it.toMap()})
}
