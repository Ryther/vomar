package org.openvimar.updater.core

import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

@Serializable data class BootHistoryEntry(val sequence:Long,val image:Int,val reason:Int,val rawResetFlags:Long)
@Serializable data class BootHistoryState(val initialized:Boolean,val loadedValid:Boolean,val storageValid:Boolean,
 val loadRc:Int,val decodeRc:Int,val saveRc:Int,val viewRc:Int)
@Serializable data class RecoveryBootHistory(val protocol:Int=1,val recordSize:Int=88,val capacity:Int=6,val currentImage:Int=1,
 val sequence:Long,val pendingReason:Int,val state:BootHistoryState,val entries:List<BootHistoryEntry>) {
 fun validate() {
  require(protocol==1&&recordSize==88&&capacity==6&&currentImage==1){"Unsupported recovery boot-history format"}
  require(sequence in 0L..0xffffffffL&&pendingReason in 0..7&&entries.size<=6){"Invalid recovery boot-history bounds"}
  require(entries.all{it.sequence in 0L..0xffffffffL&&it.image in 0..1&&it.reason in 0..7&&it.rawResetFlags in 0L..0xffffffffL}){"Invalid boot-history observation"}
 }
}
@Serializable data class BootHistoryObservation(val address:String,val identity:RuntimeIdentity,val history:RecoveryBootHistory,val observedAtMillis:Long)
interface BootHistoryTransport:BleTransport {suspend fun bootHistory():RecoveryBootHistory}
class BootHistoryUnavailable:Exception("Recovery boot history is unsupported by this firmware. No device changes were requested.")

/** Explicit discovery only. Connecting/authenticating and resource teardown belong to the one owner. */
object BootHistoryDiagnostic {
 suspend fun read(address:String,transport:BootHistoryTransport,expectedUid:List<String>?=null,checkActive:()->Unit={},now:()->Long=System::currentTimeMillis):BootHistoryObservation {
  require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(address)){"Invalid selected Bluetooth address"}
  val pinned=expectedUid?.toList();validateUid(pinned)
  val context=currentCoroutineContext()
  fun check(){context.ensureActive();checkActive()}
  check();val before=RuntimeIdentityLookup.inspect(transport);check()
  require(pinned==null||before.uid==pinned){"Runtime UID differs from the selected dimmer; boot history was not accepted"}
  val history=transport.bootHistory();check();history.validate()
  val after=RuntimeIdentityLookup.inspect(transport);check()
  require(before==after){"Runtime identity changed during the diagnostic read; boot history was not accepted"}
  return BootHistoryObservation(address,before,history,now()).also(BootHistoryReports::validateObservation)
 }
 internal fun validateUid(uid:List<String>?) {require(uid==null||(uid.size==2&&uid.all{Regex("[0-9a-f]{8}").matches(it)})){"Invalid expected dimmer UID"}}
}

@Serializable enum class BootHistoryReadState {READING,COMPLETE,UNSUPPORTED,FAILED,CANCELLED}
@Serializable data class BootHistoryDiagnosticReport(val attemptId:String,val address:String,val expectedUid:List<String>?,val state:BootHistoryReadState,
 val startedAtMillis:Long,val finishedAtMillis:Long?,val observation:BootHistoryObservation?,val schemaVersion:Int=1,
 val interpretation:String=BootHistoryReports.INTERPRETATION)

/** Bounded parsed metadata only; never carries credentials, raw SMP or firmware bytes. */
object BootHistoryReports {
 const val MAX_BYTES=16384
 const val INTERPRETATION="Raw observations only: reset flags and pending requests do not prove a reset cause. CHORD records a firmware condition/request, not proven human input. ZIGBEE records a request, not its publisher or automation identity."
 private val json=Json{encodeDefaults=true}
 fun validateObservation(observation:BootHistoryObservation) {
  require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(observation.address)&&observation.observedAtMillis>=0)
  RuntimeIdentityLookup.validate(observation.identity);observation.history.validate()
 }
 fun validate(report:BootHistoryDiagnosticReport) {
  require(report.schemaVersion==1&&report.interpretation==INTERPRETATION&&Regex("[A-Za-z0-9-]{1,64}").matches(report.attemptId))
  require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(report.address)&&report.startedAtMillis>=0)
  BootHistoryDiagnostic.validateUid(report.expectedUid)
  require(if(report.state==BootHistoryReadState.READING)report.finishedAtMillis==null else report.finishedAtMillis!=null&&report.finishedAtMillis>=report.startedAtMillis)
  if(report.state==BootHistoryReadState.COMPLETE){
   val observed=requireNotNull(report.observation);validateObservation(observed)
   require(observed.address==report.address&&(report.expectedUid==null||report.expectedUid==observed.identity.uid))
   require(observed.observedAtMillis>=report.startedAtMillis&&observed.observedAtMillis<=requireNotNull(report.finishedAtMillis))
  }else require(report.observation==null){"An incomplete diagnostic cannot publish an observation"}
 }
 fun encode(report:BootHistoryDiagnosticReport):ByteArray {
  validate(report);return json.encodeToString(BootHistoryDiagnosticReport.serializer(),report).toByteArray(Charsets.UTF_8).also{require(it.size<=MAX_BYTES)}
 }
 fun decode(bytes:ByteArray):BootHistoryDiagnosticReport {
  require(bytes.size in 1..MAX_BYTES){"Boot-history report exceeds its metadata bound"}
  return json.decodeFromString<BootHistoryDiagnosticReport>(bytes.toString(Charsets.UTF_8)).also(::validate)
 }
 fun summary(history:RecoveryBootHistory):String {
  history.validate()
  val reason=when(history.entries.lastOrNull()?.reason){
   0->"no reason recorded";1->"recovery reason unknown";2->"Zigbee request (publisher unknown)";3->"button-chord condition/request (human input unproven)"
   4->"OTA installation request";5->"OTA completion request";6->"MAIN start request";7->"boot-selector request";else->"no stored boot entries"
  }
  return "Recovery history saved: ${history.entries.size} recorded boots. Latest recorded reason: $reason. These observations do not prove a reset cause."
 }
}
