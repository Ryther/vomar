package org.openvimar.updater

import android.app.Activity
import android.app.AlertDialog
import android.app.Instrumentation
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Bitmap
import android.net.Uri
import android.test.ActivityInstrumentationTestCase2
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.TextView
import java.io.File
import java.security.KeyFactory
import java.security.spec.X509EncodedKeySpec
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.openvimar.updater.core.*

/** Actual native UI/service on the software emulator; radio/image fixtures are synthetic. */
@Suppress("DEPRECATION")
class BleTrialUiTest:ActivityInstrumentationTestCase2<BleTrialActivity>(BleTrialActivity::class.java) {
 private lateinit var runtime:BleTrialRuntime
 private lateinit var radio:Radio
 private lateinit var zip:File
 private val address="AA:BB:CC:DD:EE:FF"
 private lateinit var metadata:JsonObject
 private fun hash(role:String)=metadata.getValue(role).jsonObject.getValue("signedRegionSha256").jsonPrimitive.content
 private inner class Radio:BleTransport,MigrationBootTransport,ZigbeePairingTransport {
  @Volatile var pairingRequests=0;var pairingAck=ResetAck.ACKNOWLEDGED;var pairingGate:CompletableDeferred<Unit>?=null;@Volatile var connections=0;@Volatile var writes=0;@Volatile var resets=0;var uploadGate:CompletableDeferred<Unit>?=null
  var remote=RemoteImages(RemoteImage(metadata.getValue("allowedSourceSignedHashes").jsonArray[0].jsonPrimitive.content,false,true,"0.5.5"),RemoteImage(hash("recovery"),true,true))
  override suspend fun connect(address:String){connections++}
  override suspend fun identityV2()=RuntimeIdentity(2,"VIMAR30805",2,listOf("11223344","55667788"),"",LoaderContract(LoaderContract.COMMON,metadata.getValue("loaderContracts").jsonArray[0].jsonObject.getValue("sha256").jsonPrimitive.content),"12".repeat(32))
  override suspend fun identity()=identityV2()
  override suspend fun images()=remote
  override suspend fun upload(data:ByteArray,onAck:suspend(Int)->Unit){writes++;onAck(data.size/2);uploadGate?.await();onAck(data.size);remote=remote.copy(primary=RemoteImage(hash("main"),false,true))}
  override suspend fun reset():ResetAck{resets++;return ResetAck.ACKNOWLEDGED}
  override suspend fun bootMigration(expectedHash:String)=error("No migration expected in this synthetic native test")
  override suspend fun pairingCapabilities()=ZigbeePairingCapabilities(1,120,true)
  override suspend fun startZigbeePairing():ResetAck {pairingRequests++;pairingGate?.await();return pairingAck}
  override suspend fun close(){}
 }
 override fun setUp(){
  super.setUp()
  val context=instrumentation.targetContext
  // The transport remains synthetic; a fresh AVD still needs the foreground
  // permission prerequisites checked by the actual activity and service.
  PermissionPolicy.required(android.os.Build.VERSION.SDK_INT).forEach { permission ->
   instrumentation.uiAutomation.executeShellCommand("pm grant ${context.packageName} $permission").use { descriptor ->
    java.io.FileInputStream(descriptor.fileDescriptor).use { it.readBytes() }
   }
  }
  context.getSharedPreferences("ble-trial",0).edit().clear().commit()
  File(context.filesDir,"ble-trial-state").deleteRecursively()
  File(context.filesDir,"ble-trial-report.json").delete();File(context.filesDir,"ble-trial-report.json.bak").delete()
  zip=File(context.filesDir,"native-trial-fixture.zip").apply{writeBytes(instrumentation.context.assets.open("synthetic-ble-trial.zip").use{it.readBytes()})}
  metadata=java.util.zip.ZipInputStream(zip.inputStream()).use{stream->
   var result:JsonObject?=null
   while(true){val entry=stream.nextEntry?:break;if(entry.name=="manifest.json")result=Json.parseToJsonElement(stream.readBytes().toString(Charsets.UTF_8)).jsonObject}
   requireNotNull(result)
  }
  val key=KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(instrumentation.context.assets.open("synthetic-ble-trial-public.der").use{it.readBytes()}))
  radio=Radio()
  runtime=BleTrialRuntime(context,key,{_,check->check();radio})
  AndroidBleTrialOwner.installForTest(runtime)
 }
 override fun tearDown(){
  try{
   instrumentation.targetContext.stopService(Intent(instrumentation.targetContext,BleTrialService::class.java))
   waitUntil{!runtime.controller.state.value.busy}
   AndroidBleTrialOwner.installForTest(null)
   instrumentation.targetContext.getSharedPreferences("ble-trial",0).edit().clear().commit()
  }finally{super.tearDown()}
 }
 private fun nodes(v:View):List<View> = listOf(v)+if(v is ViewGroup)(0 until v.childCount).flatMap{nodes(v.getChildAt(it))}else emptyList()
 private fun screenContext()=instrumentation.targetContext
 private fun button(tag:String)=nodes(activity.window.decorView).filterIsInstance<Button>().single{it.tag==tag}
 private fun assertTargetPhase(phase:BleTrialPhase){
  // The fixture enters upload before its first acknowledgement is durably saved.
  // Wait for the resulting state and its main-thread render, rather than writes>0.
  waitUntil{
   var ready=false
   instrumentation.runOnMainSync{
    val text=nodes(activity.window.decorView).filterIsInstance<TextView>().single{it.tag=="ble.trial.operation"}.text
    ready=runtime.controller.state.value.phase==phase&&text.contains(phase.label)
   }
   ready
  }
  val summary=nodes(activity.window.decorView).filterIsInstance<TextView>().single{it.tag=="ble.trial.operation"}
  assertTrue("Target must remain visible",summary.getGlobalVisibleRect(android.graphics.Rect()))
  assertTrue("Pinned feedback identifies the selected dimmer",summary.text.contains(address))
  val rendered=summary.text.toString();val model=runtime.controller.state.value
  assertTrue("Pinned feedback names the current phase: expected=${phase.label}; rendered=$rendered; controller=${model.phase}; progress=${model.progressPercent}; busy=${model.busy}",rendered.contains(phase.label))
 }
 private fun waitUntil(condition:()->Boolean){val end=System.currentTimeMillis()+15000;while(System.currentTimeMillis()<end){instrumentation.waitForIdleSync();if(condition())return;Thread.sleep(50)};assertTrue("Timed out waiting for native state: ${runtime.controller.state.value.status}; ${runtime.message.value}",condition())}
 private fun capture(name:String){
  instrumentation.waitForIdleSync();Thread.sleep(900)
  val bitmap=instrumentation.uiAutomation.takeScreenshot()
  try{val c=activity.resources.configuration;val path=File(instrumentation.targetContext.getExternalFilesDir("ui-review-v061"),"ble-trial-$name-${c.screenWidthDp}x${c.screenHeightDp}-font${(c.fontScale*100).toInt()}.png");path.parentFile!!.mkdirs();path.outputStream().use{bitmap.compress(Bitmap.CompressFormat.PNG,100,it)}}finally{bitmap.recycle()}

  // Capture the actual app Window Surface separately from compositor/system
  // windows. Emulator System UI ANR overlays remain visible in full-screen
  // captures above; no production image is changed or fabricated.
  val activeDialog=BleTrialActivity::class.java.getDeclaredField("dialog").apply{isAccessible=true}.get(activity) as? AlertDialog
  val nativeWindow=activeDialog?.takeIf{it.isShowing}?.window ?: activity.window
  val windowBitmap=Bitmap.createBitmap(nativeWindow.decorView.width,nativeWindow.decorView.height,Bitmap.Config.ARGB_8888)
  val copied=CompletableDeferred<Int>()
  try{
   instrumentation.runOnMainSync{android.view.PixelCopy.request(nativeWindow,windowBitmap,{result->copied.complete(result)},android.os.Handler(android.os.Looper.getMainLooper()))}
   val result=runBlocking{withTimeout(15000){copied.await()}}
   assertEquals("Native Window Surface capture must succeed",android.view.PixelCopy.SUCCESS,result)
   val c=activity.resources.configuration
   val path=File(instrumentation.targetContext.getExternalFilesDir("ui-review-v061-window"),"ble-trial-window-$name-${c.screenWidthDp}x${c.screenHeightDp}-font${(c.fontScale*100).toInt()}.png")
   path.parentFile!!.mkdirs();path.outputStream().use{windowBitmap.compress(Bitmap.CompressFormat.PNG,100,it)}
  }finally{windowBitmap.recycle()}
 }
 private fun prepareReview(){val screen=activity;runBlocking{runtime.importCandidate(Uri.fromFile(zip));runtime.controller.inspect(address)};waitUntil{button("ble.trial.run").isEnabled};assertEquals(0,radio.writes)}
 private fun approve(){
  instrumentation.runOnMainSync{button("ble.trial.run").performClick()};instrumentation.waitForIdleSync()
  val f=BleTrialActivity::class.java.getDeclaredField("dialog").apply{isAccessible=true};val shown=f.get(activity) as AlertDialog
  instrumentation.runOnMainSync{shown.getButton(AlertDialog.BUTTON_POSITIVE).performClick()}
 }
 fun testIdleScreenExplainsMountedBluetoothTrialAndCannotStartWithoutReview(){
  val screen=activity;instrumentation.waitForIdleSync()
  val views=nodes(screen.window.decorView);val texts=views.filterIsInstance<TextView>().map{it.text.toString()}
  assertTrue(texts.contains("Update firmware"));assertTrue(texts.any{it.contains("older firmware")&&it.contains("lamp off")})
  assertTrue(button("ble.trial.choose").isEnabled);assertFalse(button("ble.trial.find").isEnabled);assertFalse(button("ble.trial.run").isEnabled)
  assertFalse(runtime.controller.state.value.busy);capture("idle")
 }
 fun testDocumentPickerResultImportsCandidateWithoutNormalReleaseOrRadio(){
  val screen=activity
  val filter=IntentFilter(Intent.ACTION_OPEN_DOCUMENT).apply{addCategory(Intent.CATEGORY_OPENABLE);addDataType("*/*")}
  val monitor=instrumentation.addMonitor(filter,Instrumentation.ActivityResult(Activity.RESULT_OK,Intent().setData(Uri.fromFile(zip))),true)
  try{instrumentation.runOnMainSync{button("ble.trial.choose").performClick()};waitUntil{runtime.selection.value!=null&&button("ble.trial.find").isEnabled};assertTrue(monitor.hits>0)}finally{instrumentation.removeMonitor(monitor)}
  assertEquals(0,radio.writes);assertEquals(0,radio.resets)
  assertNull(DocumentRepository(instrumentation.targetContext).pendingCommon())
  assertNull(AndroidFleetReleases(instrumentation.targetContext).selected())
  capture("candidate")
 }
 fun testReviewCanBeCancelledWithoutWriting(){
  prepareReview();instrumentation.runOnMainSync{button("ble.trial.run").performClick()};instrumentation.waitForIdleSync();capture("review")
  val f=BleTrialActivity::class.java.getDeclaredField("dialog").apply{isAccessible=true};val shown=f.get(activity) as AlertDialog
  instrumentation.runOnMainSync{shown.getButton(AlertDialog.BUTTON_NEGATIVE).performClick()}
  waitUntil{runtime.controller.state.value.review==null};assertEquals(0,radio.writes);assertEquals(0,radio.resets)
 }
 fun testConfirmedTrialRunsRealServiceAndReportsVerifiedReset(){
  prepareReview();approve();waitUntil{runtime.controller.state.value.acknowledged==true&&!runtime.controller.state.value.busy}
  assertEquals(1,radio.writes);assertEquals(1,radio.resets)
  val report=runBlocking{runtime.reportBytes()};assertNotNull(report)
  val json=org.json.JSONObject(String(report!!));assertEquals(address,json.getString("address"));assertTrue(json.getBoolean("resetAcknowledged"))
  assertFalse(button("ble.trial.run").isEnabled);assertTargetPhase(BleTrialPhase.AWAITING_RETURN);assertNull(runtime.controller.state.value.review);capture("complete")
 }
 fun testStopDuringUploadDrainsServiceWithoutReset(){
  radio.uploadGate=CompletableDeferred();prepareReview();approve();waitUntil{radio.writes==1&&runtime.controller.state.value.busy};assertTrue(AndroidSessionOwner.get(screenContext()).busy.value);assertFalse(AndroidSessionOwner.get(screenContext()).inspect());assertTargetPhase(BleTrialPhase.TRANSFERRING);assertNull(runtime.controller.state.value.review);capture("upload")
  instrumentation.runOnMainSync{button("ble.trial.stop").performClick()};waitUntil{!runtime.controller.state.value.busy}
  assertEquals(0,radio.resets);assertFalse(AndroidSessionOwner.get(screenContext()).busy.value);assertNull(runtime.controller.state.value.review);assertTrue(runtime.controller.state.value.status.contains("stopped"));assertTargetPhase(BleTrialPhase.PAUSED);capture("stopped")
 }
 fun testStatusAndStopRemainVisibleWhenTaskContentScrolls(){
  radio.uploadGate=CompletableDeferred();prepareReview();approve();waitUntil{radio.writes==1&&runtime.controller.state.value.busy}
  val content=nodes(activity.window.decorView).single{it.tag=="ble.trial.content"} as android.widget.ScrollView
  instrumentation.runOnMainSync{content.fullScroll(View.FOCUS_DOWN)};instrumentation.waitForIdleSync()
  val status=nodes(activity.window.decorView).single{it.tag=="ble.trial.status"}
  val stop=button("ble.trial.stop")
  assertTrue("Status must remain on screen",status.getGlobalVisibleRect(android.graphics.Rect()))
  assertTrue("Stop must remain on screen",stop.getGlobalVisibleRect(android.graphics.Rect()))
  assertTrue(stop.isEnabled);assertTargetPhase(BleTrialPhase.TRANSFERRING)
  instrumentation.runOnMainSync{stop.performClick()};waitUntil{!runtime.controller.state.value.busy};assertEquals(0,radio.resets)
 }
 fun testRotationNeverStartsConnectionOrRestoresApproval(){
  val screen=activity;instrumentation.waitForIdleSync()
  val monitor=instrumentation.addMonitor(BleTrialActivity::class.java.name,null,false)
  try{instrumentation.runOnMainSync{screen.recreate()};val replacement=monitor.waitForActivityWithTimeout(8000);assertNotNull(replacement);setActivity(replacement)}finally{instrumentation.removeMonitor(monitor)}
  instrumentation.waitForIdleSync()
  val state=runtime.controller.state.value;assertFalse(state.busy);assertNull(state.review);assertEquals(0,radio.writes)
 }
 fun testRegisteredNameIsRetainedForDisplayAndClearedForAnotherAddress(){
  val context=instrumentation.targetContext
  val preferences=context.getSharedPreferences("fleet-ui",0)
  val saved=preferences.getString("devices",null);val savedBatches=preferences.getString("batches",null)
  try{
   preferences.edit().remove("devices").commit()
   FleetStore(context).upsert(DeviceRecord("trial-name-fixture","Hall dimmer",address=address.lowercase()))
   radio.uploadGate=CompletableDeferred();prepareReview()
   fun nameView()=nodes(activity.window.decorView).filterIsInstance<TextView>().single{it.tag=="ble.trial.name"}
   assertEquals("Hall dimmer",nameView().text.toString())
   assertTrue(nameView().getGlobalVisibleRect(android.graphics.Rect()));assertEquals(0,radio.writes);assertEquals(0,radio.resets)
   approve();waitUntil{radio.writes==1&&runtime.controller.state.value.busy}
   assertEquals("Hall dimmer",nameView().text.toString());assertTargetPhase(BleTrialPhase.TRANSFERRING)
   // Changing organisational metadata cannot rebind or authorize the active trial.
   FleetStore(context).upsert(DeviceRecord("trial-name-fixture","Renamed while active",address=address))
   instrumentation.runOnMainSync{button("ble.trial.stop").performClick()};waitUntil{!runtime.controller.state.value.busy}
   assertEquals("Hall dimmer",nameView().text.toString());assertNull(runtime.controller.state.value.review)
   runBlocking{runtime.controller.inspect("11:22:33:44:55:66")};instrumentation.waitForIdleSync()
   assertEquals(View.GONE,nameView().visibility)
   assertEquals("11:22:33:44:55:66",runtime.controller.state.value.target?.address)
   assertEquals(1,radio.writes);assertEquals(0,radio.resets)
  }finally{preferences.edit().apply{
   if(saved==null)remove("devices")else putString("devices",saved)
   if(savedBatches==null)remove("batches")else putString("batches",savedBatches)
  }.commit()}
 }
 fun testProcessOwnerRecreationRestoresSelectionWithoutDisplayedTargetOrApproval(){
  prepareReview();assertTargetPhase(BleTrialPhase.REVIEW)
  runtime=BleTrialRuntime(instrumentation.targetContext)
  AndroidBleTrialOwner.installForTest(runtime)
  val monitor=instrumentation.addMonitor(BleTrialActivity::class.java.name,null,false)
  try{instrumentation.runOnMainSync{activity.recreate()};val replacement=monitor.waitForActivityWithTimeout(8000);assertNotNull(replacement);setActivity(replacement)}finally{instrumentation.removeMonitor(monitor)}
  instrumentation.waitForIdleSync()
  assertNotNull(runtime.selection.value);assertNull(runtime.controller.state.value.target);assertNull(runtime.controller.state.value.review)
  assertFalse(button("ble.trial.run").isEnabled);assertEquals(0,radio.writes);assertEquals(0,radio.resets)
 }
 fun testActiveTransferSurvivesRotationWithoutDoubleStart(){
  radio.uploadGate=CompletableDeferred();prepareReview();approve();waitUntil{radio.writes==1&&runtime.controller.state.value.busy}
  val monitor=instrumentation.addMonitor(BleTrialActivity::class.java.name,null,false)
  try{instrumentation.runOnMainSync{activity.recreate()};val replacement=monitor.waitForActivityWithTimeout(8000);assertNotNull(replacement);setActivity(replacement)}finally{instrumentation.removeMonitor(monitor)}
  instrumentation.waitForIdleSync();assertTrue(runtime.controller.state.value.busy);assertEquals(1,radio.writes);assertTargetPhase(BleTrialPhase.TRANSFERRING);assertNull(runtime.controller.state.value.review);assertFalse(button("ble.trial.run").isEnabled);capture("rotated-upload")
  instrumentation.runOnMainSync{button("ble.trial.stop").performClick()};waitUntil{!runtime.controller.state.value.busy};assertEquals(0,radio.resets)
 }
 fun testNativeWindowVisualJourney(){
  val screen=activity;instrumentation.waitForIdleSync()
  val appearance=androidx.core.view.WindowCompat.getInsetsController(screen.window,screen.window.decorView)
  val light=screen.resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK!=android.content.res.Configuration.UI_MODE_NIGHT_YES
  assertEquals("Status bar appearance must follow the active theme",light,appearance.isAppearanceLightStatusBars)
  assertEquals("Navigation bar appearance must follow the active theme",light,appearance.isAppearanceLightNavigationBars)
  capture("idle")
  runBlocking{runtime.importCandidate(Uri.fromFile(zip))};waitUntil{button("ble.trial.find").isEnabled};capture("candidate")
  runBlocking{runtime.controller.inspect(address)};waitUntil{button("ble.trial.run").isEnabled}
  instrumentation.runOnMainSync{button("ble.trial.run").performClick()};instrumentation.waitForIdleSync();capture("review")
  val f=BleTrialActivity::class.java.getDeclaredField("dialog").apply{isAccessible=true};instrumentation.runOnMainSync{(f.get(activity) as AlertDialog).getButton(AlertDialog.BUTTON_NEGATIVE).performClick()}
  radio.uploadGate=CompletableDeferred();runBlocking{runtime.controller.inspect(address)};waitUntil{button("ble.trial.run").isEnabled};approve();waitUntil{radio.writes==1&&runtime.controller.state.value.busy};capture("upload")
  val monitor=instrumentation.addMonitor(BleTrialActivity::class.java.name,null,false)
  try{instrumentation.runOnMainSync{activity.recreate()};val replacement=monitor.waitForActivityWithTimeout(8000);assertNotNull(replacement);setActivity(replacement)}finally{instrumentation.removeMonitor(monitor)}
  instrumentation.waitForIdleSync();assertTrue(runtime.controller.state.value.busy);capture("rotated-upload")
  instrumentation.runOnMainSync{button("ble.trial.stop").performClick()};waitUntil{!runtime.controller.state.value.busy};assertEquals(0,radio.resets);capture("stopped")
  radio.uploadGate=null;runBlocking{runtime.controller.inspect(address)};waitUntil{button("ble.trial.run").isEnabled};approve();waitUntil{runtime.controller.state.value.acknowledged==true&&!runtime.controller.state.value.busy}
  assertEquals(2,radio.writes);assertEquals(1,radio.resets);capture("complete")
 }
 fun testManifestKeepsTrialComponentsPrivate(){
  val context=instrumentation.targetContext
  assertFalse(context.packageManager.getServiceInfo(android.content.ComponentName(context,BleTrialService::class.java),0).exported)
  assertFalse(context.packageManager.getActivityInfo(android.content.ComponentName(context,BleTrialActivity::class.java),0).exported)
 }
 fun testZigbeePairingNeedsExplicitConfirmationWithoutFirmwareSelection(){
  setActivityIntent(Intent(instrumentation.targetContext,BleTrialActivity::class.java).putExtra("pairingOnly",true))
  val screen=activity;instrumentation.waitForIdleSync()
  assertNull(runtime.selection.value)
  assertFalse(button("ble.trial.choose").getGlobalVisibleRect(android.graphics.Rect()))
  assertTrue(button("ble.pairing.review").isEnabled)
  runBlocking{runtime.controller.inspectPairing(address)}
  waitUntil{runtime.controller.state.value.pairingReview!=null&&!runtime.controller.state.value.busy}
  var nativeState=""
  try{waitUntil{
   var ready=false
   instrumentation.runOnMainSync{
    val foreground=BleTrialActivity::class.java.getDeclaredField("foreground").apply{isAccessible=true}.getBoolean(screen)
    val button=button("ble.pairing.review")
    nativeState="foreground=$foreground focus=${screen.hasWindowFocus()} shown=${button.isShown} enabled=${button.isEnabled} text=${button.text}"
    ready=foreground&&button.isShown&&button.isEnabled&&button.text.toString()=="Review Zigbee pairing"
   }
   ready
  }}catch(failure:AssertionError){capture("zigbee-pairing-not-ready");throw AssertionError(nativeState,failure)}
  instrumentation.runOnMainSync{button("ble.pairing.review").performClick()}
  instrumentation.waitForIdleSync()
  val field=BleTrialActivity::class.java.getDeclaredField("dialog").apply{isAccessible=true}
  val shown=field.get(screen) as AlertDialog
  assertTrue(shown.isShowing);assertEquals(0,radio.pairingRequests)
  capture("zigbee-pairing-review")
  instrumentation.runOnMainSync{shown.getButton(AlertDialog.BUTTON_POSITIVE).performClick()}
  waitUntil{!runtime.controller.state.value.busy&&runtime.controller.state.value.acknowledged==true}
  assertEquals(1,radio.pairingRequests);assertEquals(0,radio.writes);assertEquals(0,radio.resets)
  assertNull(runtime.controller.state.value.pairingReview)
  capture("zigbee-pairing-acknowledged")
 }


 private fun pairingDialog():AlertDialog?=BleTrialActivity::class.java.getDeclaredField("dialog").apply{isAccessible=true}.get(activity) as? AlertDialog
 private fun showPairingReview(){
  waitUntil{
   var ready=false
   instrumentation.runOnMainSync{
    ready=BleTrialActivity::class.java.getDeclaredField("foreground").apply{isAccessible=true}.getBoolean(activity)&&
     button("ble.pairing.review").isEnabled&&button("ble.pairing.review").text.toString()=="Review Zigbee pairing"
   }
   ready
  }
  instrumentation.runOnMainSync{button("ble.pairing.review").performClick()}
  instrumentation.waitForIdleSync()
 }
 private fun withSelectedPairingDevice(selectedAddress:String=address,uid:List<String> = listOf("11223344","55667788"),work:()->Unit){
  val preferences=instrumentation.targetContext.getSharedPreferences("fleet-ui",0)
  val devices=preferences.getString("devices",null);val batches=preferences.getString("batches",null)
  try{
   preferences.edit().remove("devices").commit()
   FleetStore(instrumentation.targetContext).upsert(DeviceRecord("selected-pairing-fixture","Pairing fixture",address=selectedAddress,uid=uid))
   setActivityIntent(Intent(instrumentation.targetContext,BleTrialActivity::class.java).putExtra("pairingOnly",true).putExtra("deviceId","selected-pairing-fixture"))
   work()
  }finally{preferences.edit().apply{
   if(devices==null)remove("devices")else putString("devices",devices)
   if(batches==null)remove("batches")else putString("batches",batches)
  }.commit()}
 }
 fun testSelectedPairingInspectionUsesServiceAndCancelRevokesReviewWithoutRequest(){
  withSelectedPairingDevice{
   val screen=activity;instrumentation.waitForIdleSync()
   assertEquals(0,radio.connections);assertNull(runtime.selection.value)
   instrumentation.runOnMainSync{button("ble.pairing.review").performClick()}
   waitUntil{runtime.controller.state.value.pairingReview!=null&&!runtime.controller.state.value.busy}
   assertEquals(1,radio.connections);assertEquals(0,radio.pairingRequests)
   showPairingReview();assertTrue(pairingDialog()!!.isShowing)
   instrumentation.runOnMainSync{pairingDialog()!!.getButton(AlertDialog.BUTTON_NEGATIVE).performClick()}
   waitUntil{runtime.controller.state.value.pairingReview==null}
   assertEquals(0,radio.pairingRequests);assertEquals(0,radio.writes);assertEquals(0,radio.resets)
   val report=org.json.JSONObject(String(runBlocking{runtime.reportBytes()}!!))
   assertEquals("zigbee_pairing",report.getString("operation"))
   assertTrue(report.getString("interpretation").contains("does not establish successful Zigbee association"))
  }
 }
 fun testPairingDialogBackCancelAlsoExpiresReview(){
  setActivityIntent(Intent(instrumentation.targetContext,BleTrialActivity::class.java).putExtra("pairingOnly",true))
  val screen=activity
  runBlocking{runtime.controller.inspectPairing(address)}
  showPairingReview();assertTrue(pairingDialog()!!.isShowing)
  instrumentation.runOnMainSync{pairingDialog()!!.cancel()}
  waitUntil{runtime.controller.state.value.pairingReview==null}
  assertEquals(0,radio.pairingRequests);assertEquals(0,radio.writes);assertEquals(0,radio.resets)
 }
 fun testPairingReviewForDifferentRegisteredAddressCannotOpenConfirmation(){
  withSelectedPairingDevice(selectedAddress="11:22:33:44:55:66"){
   val screen=activity
   runBlocking{runtime.controller.inspectPairing(address)}
   showPairingReview()
   waitUntil{runtime.message.value=="Inspect the selected device again before pairing."}
   assertNull(pairingDialog());assertNull(runtime.controller.state.value.pairingReview)
   assertEquals(0,radio.pairingRequests);assertEquals(0,radio.writes);assertEquals(0,radio.resets)
  }
 }
 fun testPairingReviewForDifferentRegisteredUidCannotOpenConfirmation(){
  withSelectedPairingDevice(uid=listOf("99999999","88888888")){
   val screen=activity
   runBlocking{runtime.controller.inspectPairing(address)}
   showPairingReview()
   waitUntil{runtime.message.value=="Inspect the selected device again before pairing."}
   assertNull(pairingDialog());assertNull(runtime.controller.state.value.pairingReview)
   assertEquals(0,radio.pairingRequests);assertEquals(0,radio.writes);assertEquals(0,radio.resets)
  }
 }
 fun testLostPairingAcknowledgmentShowsUncertainOutcomeAndNeverRetries(){
  radio.pairingAck=ResetAck.LOST
  setActivityIntent(Intent(instrumentation.targetContext,BleTrialActivity::class.java).putExtra("pairingOnly",true))
  val screen=activity
  runBlocking{runtime.controller.inspectPairing(address)}
  showPairingReview()
  instrumentation.runOnMainSync{pairingDialog()!!.getButton(AlertDialog.BUTTON_POSITIVE).performClick()}
  waitUntil{!runtime.controller.state.value.busy&&runtime.controller.state.value.acknowledged==false}
  assertEquals(1,radio.pairingRequests);assertNull(runtime.controller.state.value.pairingReview)
  assertTrue(runtime.controller.state.value.status.contains("no automatic retry"))
  assertEquals("Inspect for Zigbee pairing",button("ble.pairing.review").text.toString())
  assertEquals("Export pairing report",button("ble.trial.export").text.toString())
  val report=org.json.JSONObject(String(runBlocking{runtime.reportBytes()}!!))
  assertEquals("zigbee_pairing",report.getString("operation"));assertFalse(report.getBoolean("resetAcknowledged"))
  assertEquals(0,radio.writes);assertEquals(0,radio.resets)
 }
 fun testStopAfterPairingSubmissionKeepsUncertaintyAndDoesNotResetOrRetry(){
  radio.pairingGate=CompletableDeferred()
  setActivityIntent(Intent(instrumentation.targetContext,BleTrialActivity::class.java).putExtra("pairingOnly",true))
  val screen=activity
  runBlocking{runtime.controller.inspectPairing(address)}
  showPairingReview()
  instrumentation.runOnMainSync{pairingDialog()!!.getButton(AlertDialog.BUTTON_POSITIVE).performClick()}
  waitUntil{radio.pairingRequests==1&&runtime.controller.state.value.busy}
  assertEquals("Stop",button("ble.trial.stop").text.toString())
  instrumentation.runOnMainSync{button("ble.trial.stop").performClick()}
  waitUntil{!runtime.controller.state.value.busy}
  assertEquals(BleTrialPhase.PAUSED,runtime.controller.state.value.phase)
  assertTrue(runtime.controller.state.value.status.contains("uncertain after Stop"))
  assertEquals(false,runtime.controller.state.value.acknowledged);assertNull(runtime.controller.state.value.pairingReview)
  assertEquals(1,radio.pairingRequests);assertEquals(0,radio.writes);assertEquals(0,radio.resets)
 }

}
