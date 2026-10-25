package org.openvimar.updater

import android.content.Context
import android.content.ContextWrapper
import android.graphics.Bitmap
import android.test.ActivityInstrumentationTestCase2
import android.view.View
import android.view.ViewGroup
import android.widget.CheckBox
import android.widget.FrameLayout
import android.widget.TextView
import kotlinx.coroutines.*
import java.io.File

/** Actual production views with isolated synthetic metadata. No network/radio/update executor runs. */
@Suppress("DEPRECATION")
class NativeFleetUiTest:ActivityInstrumentationTestCase2<MainActivity>(MainActivity::class.java){
    private val testScope=CoroutineScope(SupervisorJob()+Dispatchers.IO)
    private var ui:NativeFleetUi?=null
    private var imports=0
    private var executions=0
    private val target=FleetReleaseRef("a".repeat(64),"0.6.1","b".repeat(64),"/synthetic/never-opened.zip")
    private var priorTheme:String?=null
    override fun setUp(){super.setUp();setActivityInitialTouchMode(true);instrumentation.setInTouchMode(true);val p=instrumentation.targetContext.getSharedPreferences("fleet-ui",Context.MODE_PRIVATE);priorTheme=p.getString("theme",null);p.edit().putString("theme","Dark").commit()}
    override fun tearDown(){instrumentation.runOnMainSync{ui?.close()};testScope.cancel();instrumentation.targetContext.getSharedPreferences("fleet-ui",Context.MODE_PRIVATE).edit().apply{if(priorTheme==null)remove("theme")else putString("theme",priorTheme)}.commit();super.tearDown()}
    private fun record(i:Int,version:String?="0.6.0")=DeviceRecord("fixture-$i",when(i){1->"Bathroom · Ceiling light";2->"Studio · Reading light";else->"Room $i · Main light"},"Ground floor",address="C0:00:00:00:00:${"%02X".format(i)}",uid=listOf("12345678","%08x".format(i)),installedVersion=version,firmwareKind=FirmwareKind.CUSTOM,observedAt=1234,observationSource="Synthetic instrumentation observation")
    private fun fixture(records:List<DeviceRecord>,groups:List<FleetGroup> = emptyList()):NativeFleetUi{
        val context=object:ContextWrapper(activity){override fun getSharedPreferences(name:String,mode:Int)=super.getSharedPreferences("native-ui-test-$name",mode)}
        context.getSharedPreferences("fleet-ui",Context.MODE_PRIVATE).edit().clear().commit()
        val store=FleetStore(context);store.preferences.edit().putBoolean("autoCheck",false).commit();records.forEach(store::upsert)
        val persistence=object:FleetQueuePersistence{var data=groups;override fun load()=data;override fun save(groups:List<FleetGroup>){data=groups}}
        val runtime=FleetRuntime(store,AndroidFleetReleases(context),testScope,persistence,FleetJobExecutor{_,_->executions++;error("A UI review must never execute updates")},{it},{},{error("No BLE in UI review")})
        instrumentation.runOnMainSync{ui=NativeFleetUi(activity,FrameLayout(activity),{imports++},{},{},{},{},{},runtime);activity.setContentView(ui!!.root)}
        instrumentation.waitForIdleSync();Thread.sleep(250)
        instrumentation.runOnMainSync{NativeFleetUi::class.java.getDeclaredField("release").apply{isAccessible=true}.set(ui,target);ui!!.navigate("devices")}
        instrumentation.waitForIdleSync();return ui!!
    }
    private fun nodes(view:View=ui!!.root):List<View> = listOf(view)+if(view is ViewGroup)(0 until view.childCount).flatMap{nodes(view.getChildAt(it))}else emptyList()
    private fun texts()=nodes().filterIsInstance<TextView>().map{it.text.toString()}
    private fun windowNodes(matches:(List<android.view.accessibility.AccessibilityNodeInfo>)->Boolean):List<android.view.accessibility.AccessibilityNodeInfo>{
        fun walk(node:android.view.accessibility.AccessibilityNodeInfo):List<android.view.accessibility.AccessibilityNodeInfo> = listOf(node)+(0 until node.childCount).flatMap{node.getChild(it)?.let(::walk)?:emptyList()}
        val end=System.currentTimeMillis()+10000
        while(System.currentTimeMillis()<end){
            instrumentation.waitForIdleSync()
            val root=instrumentation.uiAutomation.rootInActiveWindow
            if(root!=null){val found=walk(root);if(matches(found))return found}
            Thread.sleep(100)
        }
        error("Expected native dialog did not become accessible")
    }
    private fun click(text:String){val view=nodes().filterIsInstance<TextView>().firstOrNull{it.text.toString()==text}?:error("Missing action $text");instrumentation.runOnMainSync{assertTrue(view.isEnabled);view.performClick()};instrumentation.waitForIdleSync()}
    private fun capture(name:String){instrumentation.waitForIdleSync();Thread.sleep(1500);val config=activity.resources.configuration;val viewport="${config.screenWidthDp}x${config.screenHeightDp}-font${(config.fontScale*100).toInt()}";val file=File(instrumentation.targetContext.getExternalFilesDir("ui-review-v050"),"$viewport/$name.png");file.parentFile!!.mkdirs();instrumentation.uiAutomation.takeScreenshot().let{bitmap->try{file.outputStream().use{bitmap.compress(Bitmap.CompressFormat.PNG,100,it)}}finally{bitmap.recycle()}}}
    fun testCurrentDeviceIsGreenAndExcludedFromUpdate(){
        val native=fixture(listOf(record(1,"0.6.1"),record(2)))
        assertTrue(texts().contains("Up to date"));assertTrue(texts().contains("Update available · BT"))
        instrumentation.runOnMainSync{nodes().filterIsInstance<CheckBox>().forEach{it.performClick()}}
        click("Review update · 1 compatible")
        assertTrue(texts().contains("1 compatible · 1 excluded"));assertTrue(texts().contains("Excluded from this group"));assertTrue(texts().any{it.contains("already uses the selected release")});capture("review-exclusion-dark")
        assertEquals(0,executions);assertEquals(0,imports)
        instrumentation.runOnMainSync{native.back()}
    }
    fun testImportActionReenablesAfterBusyOperation(){
        val native=fixture(emptyList())
        instrumentation.runOnMainSync{native.present(SessionPresentation(busy=true,operation=SessionOperation.INSPECT))}
        var action=nodes().first{it.tag=="fleet.release.action"};assertFalse(action.isEnabled)
        instrumentation.runOnMainSync{native.present(SessionPresentation(busy=false,operation=SessionOperation.IDLE))}
        action=nodes().first{it.tag=="fleet.release.action"};assertTrue(action.isEnabled)
    }
    fun testRecoveryHistoryAndItsExportStayWithTheSelectedDevice(){
        val a=record(1);val b=record(2);val native=fixture(listOf(a,b))
        var reads=0;var exports=0
        instrumentation.runOnMainSync{native.setHistoryReader{selected->assertEquals(a.id,selected.id);reads++;native.historyStarted(selected)}}
        val title=nodes().filterIsInstance<TextView>().first{it.text.toString()==a.name}
        instrumentation.runOnMainSync{(title.parent as View).performClick()};instrumentation.waitForIdleSync()
        click("Read recovery history");assertEquals(1,reads)
        instrumentation.runOnMainSync{native.historyResult(a.address!!,a.uid,1234567890,"Read two saved boot records for this dimmer."){exports++}}
        instrumentation.waitForIdleSync();assertTrue(texts().contains("Read two saved boot records for this dimmer."))
        click("Save history report");assertEquals(1,exports)
        instrumentation.runOnMainSync{native.historyStatus(null,"An unrelated completed command",false)};instrumentation.waitForIdleSync()
        assertTrue(texts().contains("Read two saved boot records for this dimmer."))
        instrumentation.runOnMainSync{native.back()};instrumentation.waitForIdleSync()
        val other=nodes().filterIsInstance<TextView>().first{it.text.toString()==b.name}
        instrumentation.runOnMainSync{(other.parent as View).performClick()};instrumentation.waitForIdleSync()
        assertFalse(texts().contains("Read two saved boot records for this dimmer."));assertFalse(texts().contains("Save history report"))
        assertEquals(1,exports);assertEquals(1,reads);assertEquals(0,executions)
    }
    fun testRecoveryHistoryFailureCanRebindToItsDeviceWithoutLeakingIntoAnother(){
        val a=record(1);val b=record(2);val native=fixture(listOf(a,b))
        instrumentation.runOnMainSync{native.setHistoryReader{error("This presentation test must not execute a Bluetooth diagnostic")};native.historyStatus(a.address,"This updater does not support saved recovery history.",false)}
        val title=nodes().filterIsInstance<TextView>().first{it.text.toString()==a.name}
        instrumentation.runOnMainSync{(title.parent as View).performClick()};instrumentation.waitForIdleSync()
        assertTrue(texts().contains("This updater does not support saved recovery history."))
        assertFalse(texts().contains("Save history report"))
        instrumentation.runOnMainSync{native.back()};instrumentation.waitForIdleSync()
        val other=nodes().filterIsInstance<TextView>().first{it.text.toString()==b.name}
        instrumentation.runOnMainSync{(other.parent as View).performClick()};instrumentation.waitForIdleSync()
        assertFalse(texts().contains("This updater does not support saved recovery history."))
        fun readAction()=nodes().filterIsInstance<TextView>().single{it.text.toString()=="Read recovery history"}
        assertTrue("The injected read action must be available before testing its busy lifecycle",readAction().isEnabled)
        instrumentation.runOnMainSync{native.present(SessionPresentation(busy=true,operation=SessionOperation.INSPECT))};instrumentation.waitForIdleSync()
        assertFalse(readAction().isEnabled)
        instrumentation.runOnMainSync{native.present(SessionPresentation(busy=false,operation=SessionOperation.INSPECT))};instrumentation.waitForIdleSync()
        assertTrue("Another device's completed diagnostic must release this action",readAction().isEnabled)
        assertEquals(0,executions)
    }
    fun testActivityExpandsGroupBelowItsRowWithoutNavigation(){
        val r=record(2);val group=FleetGroup("fixture-group",target,listOf(FleetJob("fixture-job",r,FleetRoute.BLE,state=FleetJobState.AWAITING_RETURN,message="Synthetic verified image evidence; awaiting owner")),FleetMode.SEQUENTIAL,1234567890)
        val native=fixture(listOf(r),listOf(group))
        instrumentation.runOnMainSync{native.navigate("activity")};instrumentation.waitForIdleSync()
        assertFalse(texts().contains("Synthetic verified image evidence; awaiting owner"))
        val row=nodes().first{it.contentDescription?.toString()?.endsWith("Expand group")==true}
        instrumentation.runOnMainSync{row.performClick()};instrumentation.waitForIdleSync()
        assertTrue(texts().contains("Synthetic verified image evidence; awaiting owner"));assertTrue(texts().contains("Confirm this dimmer is back online"));assertEquals(0,executions)
        capture("activity-inline-dark")
    }
    fun testExpandedActivityGroupsSurviveFreshPresentation(){
        val r=record(2);val message="Synthetic retained group detail"
        // Restart normalizes WAITING_NEARBY to PAUSED and replaces its message.
        // AWAITING_RETURN is durable evidence, so this assertion exercises
        // presentation restoration rather than queue recovery normalization.
        val group=FleetGroup("fixture-retained-group",target,listOf(FleetJob("fixture-retained-job",r,FleetRoute.BLE,state=FleetJobState.AWAITING_RETURN,message=message)),FleetMode.SEQUENTIAL,1234567890)
        val native=fixture(listOf(r),listOf(group))
        instrumentation.runOnMainSync{native.navigate("activity")};instrumentation.waitForIdleSync()
        val row=nodes().first{it.contentDescription?.toString()?.endsWith("Expand group")==true}
        instrumentation.runOnMainSync{row.performClick()};instrumentation.waitForIdleSync()
        assertTrue(texts().contains(message))
        val saved=android.os.Bundle()
        instrumentation.runOnMainSync{native.saveState(saved);native.close()}
        val replacement=fixture(listOf(r),listOf(group))
        instrumentation.runOnMainSync{replacement.restoreState(saved)};instrumentation.waitForIdleSync()
        assertTrue("A fresh presentation must retain the expanded group",texts().contains(message))
        assertTrue(nodes().any{it.contentDescription?.toString()?.endsWith("Collapse group")==true})
        assertEquals(0,executions)
    }
    fun testIndividualCheckboxRefreshesVisibleSelectionSummary(){
        fixture(listOf(record(1),record(2)))
        fun checkboxes()=nodes().filterIsInstance<CheckBox>()
        instrumentation.runOnMainSync{checkboxes().first().performClick()};instrumentation.waitForIdleSync()
        assertEquals("Both list summary and selection footer must show the new count",2,texts().count{it=="1 selected"})
        assertTrue(texts().contains("Select visible"))
        instrumentation.runOnMainSync{checkboxes().last().performClick()};instrumentation.waitForIdleSync()
        assertEquals(2,texts().count{it=="2 selected"});assertTrue(texts().contains("Deselect visible"))
        instrumentation.runOnMainSync{checkboxes().first().performClick()};instrumentation.waitForIdleSync()
        assertEquals(2,texts().count{it=="1 selected"});assertTrue(texts().contains("Select visible"))
        assertEquals(0,executions)
    }
    fun testCaptureApprovedFleetScreensDark(){
        val records=(1..30).map{when(it){1->record(it,"0.6.1");3->record(it,"1.2.1_z").copy(firmwareKind=FirmwareKind.STOCK);else->record(it,if(it%4==0)"0.6.1" else "0.6.0")}}
        val group=FleetGroup("fixture-review",target,listOf(FleetJob("fixture-wait",records[1],FleetRoute.BLE,state=FleetJobState.WAITING_NEARBY,message="Stand near Studio · Reading light")),FleetMode.NETWORK_PARALLEL,1792770000000)
        val native=fixture(records,listOf(group));capture("devices-30-dark")
        val filter=nodes().first{it.contentDescription?.toString()?.startsWith("Filter devices:")==true}
        instrumentation.runOnMainSync{filter.performClick()};capture("filter-list-dark")
        instrumentation.sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
        instrumentation.setInTouchMode(true)
        instrumentation.runOnMainSync{native.navigate("updates")};capture("updates-dark")
        instrumentation.runOnMainSync{native.navigate("add")};capture("add-device-dark")
        instrumentation.runOnMainSync{native.navigate("settings")};capture("settings-dark")
        instrumentation.runOnMainSync{native.navigate("network")};capture("network-dark")
        instrumentation.runOnMainSync{native.navigate("activity")};capture("activity-dark")
        assertEquals(0,executions)
    }
    fun testNavigationClearsSystemButtonsAndOpensSettings(){
        fixture(emptyList())
        instrumentation.waitForIdleSync();Thread.sleep(300)
        val nav=nodes().filterIsInstance<TextView>().first{it.text.toString()=="Settings"}
        val position=IntArray(2);instrumentation.runOnMainSync{nav.getLocationOnScreen(position)}
        val inset=androidx.core.view.ViewCompat.getRootWindowInsets(ui!!.root)!!.getInsets(androidx.core.view.WindowInsetsCompat.Type.systemBars())
        assertTrue("App navigation must end above Android system navigation",position[1]+nav.height<=activity.resources.displayMetrics.heightPixels-inset.bottom)
        click("Settings");assertTrue(texts().contains("Appearance"))
    }
    fun testDkToolsUseSelectedDarkAppearance(){
        fixture(emptyList())
        val dk=instrumentation.startActivitySync(android.content.Intent(instrumentation.targetContext,DkUsbDiagnosticsActivity::class.java).addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
        try{
            instrumentation.waitForIdleSync()
            assertEquals(android.content.res.Configuration.UI_MODE_NIGHT_YES,dk.resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK)
            assertTrue(nodes(dk.window.decorView).filterIsInstance<TextView>().any{it.text.toString()=="Start SWD monitor"})
            val scroller=nodes(dk.window.decorView).filterIsInstance<android.widget.ScrollView>().single()
            val location=IntArray(2);instrumentation.runOnMainSync{scroller.getLocationOnScreen(location)}
            val safe=androidx.core.view.ViewCompat.getRootWindowInsets(scroller)!!.getInsets(androidx.core.view.WindowInsetsCompat.Type.systemBars())
            assertTrue("DK scroll viewport must end above Android system navigation",location[1]+scroller.height-scroller.paddingBottom<=dk.resources.displayMetrics.heightPixels-safe.bottom)
            capture("dk-tools-dark")
        }finally{instrumentation.runOnMainSync{dk.finish()}}
    }
    fun testCaptureLightAppearance(){
        instrumentation.targetContext.getSharedPreferences("fleet-ui",Context.MODE_PRIVATE).edit().putString("theme","Light").commit()
        val native=fixture(listOf(record(1,"0.6.1"),record(2)))
        assertEquals(android.content.res.Configuration.UI_MODE_NIGHT_NO,activity.resources.configuration.uiMode and android.content.res.Configuration.UI_MODE_NIGHT_MASK)
        capture("devices-light")
        instrumentation.runOnMainSync{native.navigate("settings")};capture("settings-light")
    }
    private fun openConnectionDraft(native:NativeFleetUi){
        instrumentation.runOnMainSync{native.navigate("network")};instrumentation.waitForIdleSync()
        val add=nodes().single{it.contentDescription=="Add connection"&&it.isShown}
        instrumentation.runOnMainSync{add.performClick()};instrumentation.waitForIdleSync()
    }
    private fun editField(label:String)=nodes().filterIsInstance<android.widget.EditText>().single{it.hint.toString()==label}
    private fun openTopics(){val row=nodes().first{it.contentDescription?.toString()?.startsWith("Zigbee topics (")==true};instrumentation.runOnMainSync{row.performClick()};instrumentation.waitForIdleSync()}
    fun testTopicsStopOfferingMoreThanThreeEntries(){
        val native=fixture(emptyList());openConnectionDraft(native);openTopics()
        repeat(3){i->click("Add topic");instrumentation.runOnMainSync{editField("Topic name (required)").setText("Topic $i");editField("MQTT base topic (required)").setText("topic$i")};click("Save topic")}
        val add=nodes().filterIsInstance<TextView>().single{it.text=="Add topic"}
        assertFalse(add.isEnabled);assertTrue(texts().contains("Up to 3 topics per connection."));assertEquals(0,executions)
    }
    fun testAdvancedToolsHaveOneEntryAndReturnToSettings(){
        val native=fixture(emptyList())
        instrumentation.runOnMainSync{native.navigate("settings")};instrumentation.waitForIdleSync()
        assertTrue(texts().contains("Tools"));assertFalse(texts().contains("DK tools"));assertFalse(texts().contains("Bluetooth trial"))
        val tools=nodes().filterIsInstance<TextView>().single{it.text.toString()=="Tools"}
        instrumentation.runOnMainSync{generateSequence(tools as View){it.parent as? View}.first{it.isClickable}.performClick()};instrumentation.waitForIdleSync()
        assertTrue(texts().contains("First installation"));assertTrue(texts().contains("DK tools"));assertTrue(texts().contains("Bluetooth trial"))
        assertFalse(texts().contains("Save latest update report"));capture("tools-dark")
        instrumentation.runOnMainSync{assertTrue(native.back())};instrumentation.waitForIdleSync()
        assertTrue(texts().contains("Appearance"));assertEquals(0,executions)
    }
    fun testToolsReportTracksCompletedOperationWithoutReopening(){
        val native=fixture(emptyList());instrumentation.runOnMainSync{native.navigate("tools")};instrumentation.waitForIdleSync()
        assertFalse(texts().contains("Save latest update report"))
        instrumentation.runOnMainSync{native.present(SessionPresentation(busy=true,reportAvailable=true))};instrumentation.waitForIdleSync()
        fun report()=nodes().filterIsInstance<TextView>().single{it.text.toString()=="Save latest update report"}
        assertFalse(report().isEnabled)
        instrumentation.runOnMainSync{native.present(SessionPresentation(busy=false,reportAvailable=true))};instrumentation.waitForIdleSync()
        assertTrue(report().isEnabled);assertEquals(0,executions)
    }
    fun testNetworkAndReleaseFieldsUseTechnicalKeyboards(){
        val native=fixture(emptyList())
        instrumentation.runOnMainSync{native.navigate("network")};instrumentation.waitForIdleSync()
        val fields=nodes().filterIsInstance<android.widget.EditText>()
        val address=fields.single{it.tag=="network.address"}
        val topic=fields.single{it.hint.toString().startsWith("Base topic")}
        val username=fields.single{it.hint.toString().startsWith("Username")}
        val password=fields.single{it.hint.toString()=="Password"}
        val forbidden=android.text.InputType.TYPE_TEXT_FLAG_AUTO_CORRECT or android.text.InputType.TYPE_TEXT_FLAG_CAP_SENTENCES or android.text.InputType.TYPE_TEXT_FLAG_CAP_WORDS or android.text.InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS
        listOf(address,topic,username,password).forEach{field->
            assertEquals("Technical input must preserve literal characters",0,field.inputType and forbidden)
            assertTrue(field.imeOptions and android.view.inputmethod.EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING!=0)
        }
        assertEquals(android.text.InputType.TYPE_TEXT_VARIATION_URI,address.inputType and android.text.InputType.TYPE_MASK_VARIATION)
        assertTrue(password.transformationMethod is android.text.method.PasswordTransformationMethod)
        assertFalse(password.isSaveEnabled);assertFalse(username.isSaveEnabled)
        instrumentation.runOnMainSync{address.setText("broker.example:1833")}
        assertEquals("tcp://broker.example:1833",normalizeBrokerUri(address.text.toString()))
        capture("network-keyboards-dark")
        instrumentation.runOnMainSync{native.navigate("updates")};instrumentation.waitForIdleSync()
        click("Release source");click("Change source");Thread.sleep(500)
        val source=windowNodes{it.any{node->node.className=="android.widget.EditText"}}.single{it.className=="android.widget.EditText"}
        assertEquals(android.text.InputType.TYPE_TEXT_VARIATION_URI,source.inputType and android.text.InputType.TYPE_MASK_VARIATION)
        assertEquals(0,source.inputType and forbidden)
        instrumentation.sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
        assertEquals(0,executions)
    }
    fun testBackReturnsToReleaseOriginAndKeepsSelection(){
        val native=fixture(listOf(record(1),record(2)))
        instrumentation.runOnMainSync{nodes().filterIsInstance<CheckBox>().first().performClick()}
        click("Open")
        assertTrue(texts().contains("Updates"))
        instrumentation.runOnMainSync{assertTrue(native.back())};instrumentation.waitForIdleSync()
        assertTrue("Back must return to Devices, where release was opened",texts().contains("Search rooms or devices")||nodes().filterIsInstance<android.widget.EditText>().any{it.hint.toString()=="Search rooms or devices"})
        assertTrue(nodes().filterIsInstance<CheckBox>().first().isChecked)
        assertEquals(0,executions)
    }
    fun testBackFromNetworkImportReturnsToAddDevice(){
        val native=fixture(emptyList());instrumentation.runOnMainSync{native.navigate("add")};instrumentation.waitForIdleSync()
        click("Choose Zigbee devices");assertTrue(texts().contains("Connect to Zigbee2MQTT to find devices."))
        instrumentation.runOnMainSync{assertTrue(native.back())};instrumentation.waitForIdleSync()
        assertTrue(texts().contains("Search Bluetooth"));assertEquals(0,executions)
    }
    fun testNonSecretConnectionDraftSurvivesRecreationWithoutConnecting(){
        var native=fixture(emptyList());openConnectionDraft(native)
        instrumentation.runOnMainSync{editField("Connection name (required)").setText("Draft connection");editField("Broker address (required)").setText("ssl://broker.example:8883")}
        val saved=android.os.Bundle();instrumentation.runOnMainSync{native.saveState(saved);native.close()}
        native=fixture(emptyList());instrumentation.runOnMainSync{native.restoreState(saved)};instrumentation.waitForIdleSync()
        assertEquals("Draft connection",editField("Connection name (required)").text.toString())
        assertEquals("ssl://broker.example:8883",editField("Broker address (required)").text.toString())
        assertFalse(AndroidNetworkOwner.get(activity).state.value.connected);assertEquals(0,executions)
    }
    fun testTopicValidationStaysInlineAndDoesNotConnect(){
        val native=fixture(emptyList());openConnectionDraft(native);openTopics();click("Add topic")
        click("Save topic")
        assertNotNull(editField("Topic name (required)").error)
        assertNotNull(editField("MQTT base topic (required)").error)
        assertFalse(AndroidNetworkOwner.get(activity).state.value.connected);assertEquals(0,executions)
    }
    fun testThirtyDeviceGroupIsCompactWithExplicitCompletion(){
        val records=(1..30).map{record(it)}
        val jobs=records.mapIndexed{i,r->FleetJob("compact-$i",r,FleetRoute.BLE,state=if(i==0)FleetJobState.VERIFIED else FleetJobState.AWAITING_RETURN,message="Image checked; awaiting owner $i")}
        val group=FleetGroup("compact-group",target,jobs,FleetMode.SEQUENTIAL,1792770000000)
        val native=fixture(records,listOf(group));instrumentation.runOnMainSync{native.navigate("activity")};instrumentation.waitForIdleSync()
        val row=nodes().single{it.contentDescription?.toString()?.endsWith("Expand group")==true}
        instrumentation.runOnMainSync{row.performClick()};instrumentation.waitForIdleSync()
        assertTrue("Image verification is distinct from group completion",texts().contains("1 of 30 completed"))
        val devices=nodes().filter{it.tag?.toString()?.startsWith("fleet.job.")==true}
        assertEquals(30,devices.size)
        assertFalse("Per-device diagnostics should be disclosed rather than repeated thirty times",texts().contains("Recheck Bluetooth evidence"))
        instrumentation.runOnMainSync{devices[1].performClick()};instrumentation.waitForIdleSync()
        assertTrue(texts().contains("Confirm this dimmer is back online"))
        assertEquals(1,texts().count{it=="Recheck Bluetooth evidence"})
        instrumentation.runOnMainSync{native.present(SessionPresentation())};instrumentation.waitForIdleSync()
        assertEquals(1,texts().count{it=="Recheck Bluetooth evidence"})
        capture("activity-30-compact-dark")
        instrumentation.runOnMainSync{nodes().single{it.tag=="fleet.job.compact-1"}.performClick()};instrumentation.waitForIdleSync()
        assertFalse(texts().contains("Recheck Bluetooth evidence"));assertEquals(0,executions)
    }
    fun testReleaseDetailsUseDisclosureAndFilterUsesOneSelector(){
        val native=fixture(listOf(record(1),record(2)))
        val filter=nodes().single{it.contentDescription?.toString()?.startsWith("Filter devices:")==true}
        instrumentation.runOnMainSync{filter.performClick()};instrumentation.waitForIdleSync()
        val active=windowNodes{it.any{node->node.text?.toString()=="Not updatable"}}
        assertFalse(active.any{it.text?.toString() in listOf("Use list","Use wheel","Done")})
        assertFalse(active.any{it.className=="android.widget.NumberPicker"})
        instrumentation.sendKeyDownUpSync(android.view.KeyEvent.KEYCODE_BACK)
        instrumentation.runOnMainSync{native.navigate("updates")};instrumentation.waitForIdleSync()
        val technical=nodes().filterIsInstance<TextView>().first{it.text.toString().contains("trusted firmware key.")}
        assertFalse(technical.isShown);click("Package details");assertTrue(technical.isShown);assertEquals(0,executions)
    }
    fun testCredentialBearingAddressIsNotSerializedAsANonSecretDraft(){
        val native=fixture(emptyList());openConnectionDraft(native)
        instrumentation.runOnMainSync{editField("Broker address (required)").setText("tcp://private-user:private-password@broker.example")}
        val saved=android.os.Bundle();instrumentation.runOnMainSync{native.saveState(saved)}
        val draft=saved.getBundle("savedConnections")!!
        assertEquals("",draft.getString("address"));assertFalse(draft.toString().contains("private-password"));assertEquals(0,executions)
    }
    fun testDraftEditingRemainsAvailableDuringUnrelatedOperation(){
        val native=fixture(emptyList());val gate=CompletableDeferred<Unit>()
        val work:suspend()->Unit={gate.await()}
        val perform=NativeFleetUi::class.java.declaredMethods.single{it.name=="perform"}.apply{isAccessible=true}
        instrumentation.runOnMainSync{perform.invoke(native,"Synthetic operation",work)}
        openConnectionDraft(native)
        assertTrue(editField("Broker address (required)").isEnabled)
        gate.complete(Unit);instrumentation.waitForIdleSync();assertEquals(0,executions)
    }
    fun testInvalidTopicKeepsItsDraftAndDisplaysAnError(){
        val native=fixture(emptyList());openConnectionDraft(native);openTopics();click("Add topic")
        instrumentation.runOnMainSync{editField("Topic name (required)").setText("Garden");editField("MQTT base topic (required)").setText("bad/+")}
        click("Save topic")
        assertNotNull(editField("MQTT base topic (required)").error)
        assertEquals("Garden",editField("Topic name (required)").text.toString());assertEquals(0,executions)
    }
    fun testShowCommitsWithOneUninterruptedPressDragRelease(){
        fixture(listOf(record(1,"0.6.1"),record(2)))
        val filter=nodes().single{it.contentDescription?.toString()?.startsWith("Filter devices:")==true}
        val location=IntArray(2);instrumentation.runOnMainSync{filter.getLocationOnScreen(location)}
        val down=android.os.SystemClock.uptimeMillis()
        fun send(action:Int,x:Float,y:Float){val event=android.view.MotionEvent.obtain(down,android.os.SystemClock.uptimeMillis(),action,x,y,0);try{assertTrue(instrumentation.uiAutomation.injectInputEvent(event,true))}finally{event.recycle()}}
        send(android.view.MotionEvent.ACTION_DOWN,location[0]+filter.width/2f,location[1]+filter.height/2f)
        val active=windowNodes{it.any{node->node.text?.toString()=="Not updatable"}}
        val target=active.first{it.text?.toString()=="Update available"};val bounds=android.graphics.Rect();target.getBoundsInScreen(bounds)
        assertTrue(texts().any{it=="Show  ·  All"})
        send(android.view.MotionEvent.ACTION_MOVE,bounds.centerX().toFloat(),bounds.centerY().toFloat())
        send(android.view.MotionEvent.ACTION_UP,bounds.centerX().toFloat(),bounds.centerY().toFloat())
        instrumentation.waitForIdleSync()
        assertTrue(texts().contains("Show  ·  Update available"));assertTrue(texts().contains("1 device"));assertTrue(texts().contains("2 devices · saved on this phone"));assertEquals(0,executions)
    }
    fun testCredentialDraftIsNeverRestoredOrDisplayedAsASavedValue(){
        val id=java.util.UUID.randomUUID().toString()
        val p=BrokerProfile(id,"ssl://fixture.invalid",listOf(ZigbeeNetwork(id,"Fixture topic","fixture")),label="Synthetic connection")
        val network=AndroidNetworkOwner.get(activity)
        kotlinx.coroutines.runBlocking{network.saveProfile(p)}
        BrokerCredentials("stored-private-user","stored-private-password".toCharArray()).use{BrokerSecretStore(activity).save(p,it)}
        try {
            val native=fixture(emptyList());instrumentation.runOnMainSync{native.navigate("network")};instrumentation.waitForIdleSync()
            val row=nodes().first{it.contentDescription?.toString()?.startsWith("Synthetic connection.")==true}
            instrumentation.runOnMainSync{row.performClick()};instrumentation.waitForIdleSync()
            assertTrue(texts().contains("Credentials saved on this phone"));assertFalse(texts().any{it.contains("stored-private")})
            click("Change credentials");click("Change username")
            instrumentation.runOnMainSync{editField("Username (optional)").setText("draft-private-user");editField("New password").setText("draft-private-password")}
            val state=android.os.Bundle();instrumentation.runOnMainSync{native.saveState(state)}
            val saved=state.getBundle("savedConnections")!!
            assertFalse(saved.toString().contains("draft-private"));assertEquals("detail",saved.getString("screen"))
            assertEquals(0,executions)
        }finally{kotlinx.coroutines.runBlocking{network.removeProfile(id)}}
    }
    fun testEmptyInventoryStartsWithBluetoothEnrolment(){fixture(emptyList());assertTrue(texts().contains("Add your first dimmer"));click("Add device");assertTrue(texts().contains("Search Bluetooth"));assertTrue(texts().any{it.contains("5 seconds")});assertEquals(0,imports);capture("add-empty-dark")}
}
