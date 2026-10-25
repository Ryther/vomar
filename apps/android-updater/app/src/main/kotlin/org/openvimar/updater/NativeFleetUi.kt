package org.openvimar.updater

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.content.res.ColorStateList
import android.net.Uri
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.widget.*
import androidx.core.view.ViewCompat
import kotlinx.coroutines.*
import org.json.JSONArray
import java.text.DateFormat
import java.util.Date
import java.util.UUID

/** Pure draft helpers: no credential, connection or update authority. */
internal fun safeNetworkAddressDraft(address:String):String=if(runCatching{normalizeBrokerUri(address)}.isSuccess)address else ""
internal fun nextNetworkDraftId(existing:Collection<String>):String {
    var number=1
    while("network-$number" in existing)number++
    return "network-$number"
}

/** Native fleet presentation. Mutation authority stays in the verified runtime executors. */
internal class NativeFleetUi(
    private val activity: Activity,
    private val sessionView: View,
    private val choosePackage: () -> Unit,
    private val importZigbee: () -> Unit,
    private val exportReport: () -> Unit,
    private val requestBluetooth: () -> Unit,
    private val searchBluetooth: () -> Unit,
    private val prepareBluetoothUpdate: () -> Unit,
    private val runtime:FleetRuntime=AndroidFleetOwner.get(activity,AndroidNetworkOwner.get(activity).executor)
) {
    private val network=AndroidNetworkOwner.get(activity)
    val store = runtime.records
    private var release:FleetReleaseRef?=null
    private var releaseInitialised=false
    private val openGroups=linkedSetOf<String>()
    private val openJobs=linkedSetOf<String>()
    private val closedJobs=linkedSetOf<String>()
    private val openGroupOptions=linkedSetOf<String>()
    private data class Route(val page:String,val detail:String?,val offset:Int)
    private val history=mutableListOf<Route>()
    private val connectionsUi:SavedConnectionsUi by lazy { SavedConnectionsUi(activity,network,scope,
        {name,description,plus,edit->title.text=name;subtitle.text=description;subtitle.visibility=if(description.isBlank())View.GONE else View.VISIBLE;addButton.visibility=if(plus)View.VISIBLE else View.GONE;addButton.isEnabled=connectionsUi.canAdd;addButton.contentDescription=if(name=="Zigbee topics")"Add topic" else "Add connection";networkEditButton.visibility=if(edit)View.VISIBLE else View.GONE},
        {if(returnToZigbeeImport){returnToZigbeeImport=false;navigate("zigbee-import")}},importZigbee) }
    private var returnToZigbeeImport=false
    private val zigbeeSelection=linkedSetOf<String>()
    private var zigbeeTopicFilter:String?=null
    private var importProfile:String?=null
    private var sourceSettingsExpanded=false
    private var packageDetailsExpanded=false
    private var jobBusy=false
    val root = LinearLayout(activity)
    private val page = LinearLayout(activity).apply{orientation=LinearLayout.VERTICAL}
    private val toolbar = LinearLayout(activity).apply{orientation=LinearLayout.VERTICAL}
    private val title = text("Devices",24,true)
    private val subtitle = text("",14,secondary=true)
    private val backButton=NativeUi.iconButton(activity,"back","Back"){back()}
    private val addButton=NativeUi.iconButton(activity,"plus","Add device"){navigate("add")}
    private val networkEditButton=button("Edit"){connectionsUi.editCurrent()}.apply{visibility=View.GONE}
    private val frame = FrameLayout(activity)
    private val scroll = ScrollView(activity).apply{isFillViewport=true}
    private val body = column()
    private val footer = column()
    private val navigation = LinearLayout(activity)
    private val tabs=linkedMapOf<String,Button>()
    private val scope=CoroutineScope(SupervisorJob()+Dispatchers.Main.immediate)
    private var state=SessionPresentation()
    private var pageId="devices"
    private var detailId:String?=null
    private var filter="All"
    private var query=""
    private val selected=linkedSetOf<String>()
    private var activeBatch:String?=store.preferences.getString("activeBatch",null)
    private var sourceBusy=false
    private var releaseLoad:Job?=null
    private var releaseFetch:Job?=null
    private var commonPending=false
    private var bootstrapPending=false
    private var currentServiceStatus=""
    private var sourceMessage=""
    private var releasesChecked=false
    private var deviceRows:LinearLayout?=null
    private var historyReader:((DeviceRecord)->Unit)?=null
    private var pendingHistoryId:String?=null
    private val historyMessages=mutableMapOf<String,String>()
    private data class HistoryResult(val observedAt:Long,val save:()->Unit)
    private val historyResults=mutableMapOf<String,HistoryResult>()
    private val diagnosticsExpanded=mutableSetOf<String>()
    private val informationExpanded=mutableSetOf<String>()
    private val expanded=activity.resources.configuration.screenWidthDp>=600
    private val filters=listOf("All","Up to date","Update available","Not updatable")
    init {
        NativeUi.insets(root)
        root.orientation=if(expanded)LinearLayout.HORIZONTAL else LinearLayout.VERTICAL
        root.setBackgroundColor(color(R.color.ui_surface))
        toolbar.setPadding(dp(20),dp(16),dp(20),dp(12))
        val heading=LinearLayout(activity).apply{gravity=Gravity.CENTER_VERTICAL}
        heading.addView(backButton,LinearLayout.LayoutParams(dp(48),dp(48)))
        heading.addView(title,LinearLayout.LayoutParams(0,-2,1f))
        heading.addView(addButton,LinearLayout.LayoutParams(dp(48),dp(48)))
        heading.addView(networkEditButton,LinearLayout.LayoutParams(-2,dp(48)))
        toolbar.addView(heading);toolbar.addView(subtitle)
        ViewCompat.setAccessibilityHeading(title,true)
        page.addView(toolbar,LinearLayout.LayoutParams(-1,-2))
        body.setPadding(dp(20),dp(8),dp(20),dp(24));scroll.addView(body,FrameLayout.LayoutParams(-1,-2,Gravity.TOP or Gravity.CENTER_HORIZONTAL))
        frame.addView(scroll,FrameLayout.LayoutParams(-1,-1));frame.addView(sessionView,FrameLayout.LayoutParams(-1,-1))
        page.addView(frame,LinearLayout.LayoutParams(-1,0,1f))
        footer.setPadding(dp(20),dp(4),dp(20),dp(8));page.addView(footer)
        navigation.orientation=if(expanded)LinearLayout.VERTICAL else LinearLayout.HORIZONTAL
        navigation.setBackgroundColor(color(R.color.ui_surface))
        navigation.setPadding(dp(8),dp(4),dp(8),dp(4))
        listOf("devices" to "Devices","activity" to "Activity","settings" to "Settings").forEach{(id,label)->
            val button=button(label){navigate(id)}.apply{contentDescription=label;setPadding(dp(4),dp(12),dp(4),dp(12));textSize=13f}
            NativeUi.navigation(activity,button,id,id=="devices")
            tabs[id]=button
            navigation.addView(button,if(expanded)LinearLayout.LayoutParams(dp(112),-2).apply{topMargin=dp(8)} else LinearLayout.LayoutParams(0,-2,1f))
        }
        if(expanded) {root.addView(navigation,LinearLayout.LayoutParams(dp(112),-1));root.addView(page,LinearLayout.LayoutParams(0,-1,1f))}
        else {root.addView(page,LinearLayout.LayoutParams(-1,0,1f));root.addView(View(activity).apply{setBackgroundColor(color(R.color.ui_line))},LinearLayout.LayoutParams(-1,dp(1)));root.addView(navigation,LinearLayout.LayoutParams(-1,-2))}
        if(expanded)page.addOnLayoutChangeListener{_,left,_,right,_,_,_,_,_->
            val width=minOf(dp(720),right-left)
            if(width>0){
                listOf(toolbar,footer).forEach{view->val params=view.layoutParams as LinearLayout.LayoutParams;if(params.width!=width){params.width=width;params.gravity=Gravity.CENTER_HORIZONTAL;view.layoutParams=params}}
                val params=body.layoutParams as FrameLayout.LayoutParams;if(params.width!=width){params.width=width;params.gravity=Gravity.TOP or Gravity.CENTER_HORIZONTAL;body.layoutParams=params}
            }
        }
        renderPage()
        scope.launch { release=withContext(Dispatchers.IO){runCatching{runtime.releases.selected()}.getOrNull()};releaseInitialised=true;if(release==null&&commonPending&&!sourceBusy)adoptCommon();renderPage() }
        scope.launch { runtime.queue.groups.collect { if(pageId=="activity")refreshPage() else if(pageId=="network")connectionsUi.updateAvailability() } }
        scope.launch { FleetUpdateService.status.collect{if(it.isNotBlank())sourceNotice(it)} }
        scope.launch {
            var previousConnection:String?=null
            network.state.collect { value ->
            val currentConnection=network.activeProfileId.takeIf{value.connected}
            val connectionChanged=currentConnection!=previousConnection;previousConnection=currentConnection
            if(pageId=="network")connectionsUi.updateState()
            if(pageId=="zigbee-import")refreshPage()
            var changed=false
            value.devices.forEach { observed ->
                val known=store.devices.firstOrNull{it.networkId==observed.networkId&&it.ieee==observed.ieee}
                if(known!=null){val merged=ZigbeeDeviceMetadata.mergeSaved(known,observed);if(known!=merged){store.upsert(merged);changed=true}}
            }
            if((changed||connectionChanged)&&pageId in listOf("devices","device"))refreshPage()
        } }
    }
    private fun refreshPage(){val offset=scroll.scrollY;renderPage();scroll.post{scroll.scrollTo(0,offset)}}
    private fun perform(label:String,work:suspend()->Unit){
        if(jobBusy)return
        jobBusy=true
        scope.launch { try{work()}catch(e:CancellationException){throw e}catch(e:Exception){sourceNotice(e.message?:"$label failed. Try again.")}finally{jobBusy=false;refreshPage()} }
    }
    private fun deviceStatus(record:DeviceRecord)=if(release!=null)FleetPolicy.status(record,release) else FleetPolicy.status(record,state)
    private fun dp(n:Int)=(n*activity.resources.displayMetrics.density+0.5f).toInt()
    private fun color(id:Int)=activity.getColor(id)
    private fun column()=LinearLayout(activity).apply{orientation=LinearLayout.VERTICAL}
    private fun text(value:String,size:Int=15,bold:Boolean=false,secondary:Boolean=false)=NativeUi.label(activity,value,size,bold,secondary)
    private fun add(view:View,parent:LinearLayout=body,gap:Int=8){parent.addView(view,LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(gap)})}
    private fun copy(value:String,parent:LinearLayout=body,secondary:Boolean=true)=text(value,15,secondary=secondary).also{add(it,parent)}
    private fun section(value:String,parent:LinearLayout=body)=text(value,20,true).also{ViewCompat.setAccessibilityHeading(it,true);add(it,parent,24)}
    private fun button(value:String,filled:Boolean=false,run:()->Unit)=NativeUi.button(activity,value,filled,action=run)
    private fun action(label:String,parent:LinearLayout=body,filled:Boolean=false,enabled:Boolean=true,run:()->Unit)=button(label,filled,run).also{it.isEnabled=enabled;add(it,parent)}
    private fun divider(parent:LinearLayout=body,gap:Int=16){add(View(activity).apply{setBackgroundColor(color(R.color.ui_line))},parent,gap);parent.getChildAt(parent.childCount-1).layoutParams.height=dp(1)}
    private fun settingRow(label:String,description:String,run:()->Unit){
        val row=LinearLayout(activity).apply{gravity=Gravity.CENTER_VERTICAL;minimumHeight=dp(72);setPadding(0,dp(14),0,dp(14));isClickable=true;isFocusable=true;setBackgroundResource(android.R.drawable.list_selector_background);setOnClickListener{run()};contentDescription="$label. $description"}
        val info=column();info.addView(text(label,16,true));if(description.isNotBlank())add(text(description,13,secondary=true),info,4)
        row.addView(info,LinearLayout.LayoutParams(0,-2,1f))
        row.addView(ImageView(activity).apply{setImageDrawable(NativeUi.Icon(activity,"right",color(R.color.ui_text_secondary)));importantForAccessibility=View.IMPORTANT_FOR_ACCESSIBILITY_NO},LinearLayout.LayoutParams(dp(22),dp(22)))
        add(row,gap=0);divider(gap=0)
    }
    fun saveState(out:Bundle){
        out.putString("fleetPage",pageId);out.putString("fleetDetail",detailId);out.putString("fleetFilter",filter);out.putString("fleetQuery",query)
        out.putStringArrayList("fleetSelected",ArrayList(selected));out.putStringArrayList("fleetOpenGroups",ArrayList(openGroups));out.putStringArrayList("fleetOpenJobs",ArrayList(openJobs));out.putStringArrayList("fleetClosedJobs",ArrayList(closedJobs));out.putStringArrayList("fleetGroupOptions",ArrayList(openGroupOptions));out.putString("fleetActiveBatch",activeBatch)
        out.putParcelableArrayList("fleetHistory",ArrayList(history.map{r->Bundle().apply{putString("page",r.page);putString("detail",r.detail);putInt("offset",r.offset)}}))
        out.putInt("fleetScroll",scroll.scrollY);out.putBoolean("sourceSettingsExpanded",sourceSettingsExpanded);out.putBoolean("packageDetailsExpanded",packageDetailsExpanded)
        out.putBundle("savedConnections",connectionsUi.saveState())
    }
    @Suppress("DEPRECATION")
    fun restoreState(saved:Bundle?){
        if(saved==null)return
        pageId=saved.getString("fleetPage","devices");detailId=saved.getString("fleetDetail");filter=saved.getString("fleetFilter","All");query=saved.getString("fleetQuery","")
        selected.addAll(saved.getStringArrayList("fleetSelected")?:emptyList());openGroups.clear();openGroups.addAll(saved.getStringArrayList("fleetOpenGroups")?:emptyList());openJobs.addAll(saved.getStringArrayList("fleetOpenJobs")?:emptyList());closedJobs.addAll(saved.getStringArrayList("fleetClosedJobs")?:emptyList());openGroupOptions.addAll(saved.getStringArrayList("fleetGroupOptions")?:emptyList());activeBatch=saved.getString("fleetActiveBatch")
        history.clear();saved.getParcelableArrayList<Bundle>("fleetHistory")?.takeLast(32)?.forEach{b->history.add(Route(b.getString("page")?:"devices",b.getString("detail"),b.getInt("offset").coerceAtLeast(0)))}
        sourceSettingsExpanded=saved.getBoolean("sourceSettingsExpanded");packageDetailsExpanded=saved.getBoolean("packageDetailsExpanded")
        saved.getBundle("savedConnections")?.let(connectionsUi::restoreState)
        renderPage();scroll.post{scroll.scrollTo(0,saved.getInt("fleetScroll").coerceAtLeast(0))}
    }
    fun close(){connectionsUi.close();scope.cancel()}
    fun setHistoryReader(reader:(DeviceRecord)->Unit){historyReader=reader}
    fun historyStarted(record:DeviceRecord){pendingHistoryId=record.id;historyResults.remove(record.id);historyMessages[record.id]="Reading saved recovery history…";if(pageId=="device"&&detailId==record.id)refreshPage()}
    fun historyStatus(address:String?,message:String?,busy:Boolean){
        if(address==null||message.isNullOrBlank())return
        val records=store.devices.filter{it.address.equals(address,true)}
        records.forEach{record->
            historyMessages[record.id]=UpdateCopy.visibleStatus(message)
            if(!busy&&pendingHistoryId==record.id)pendingHistoryId=null
        }
        if(pageId=="device"&&records.any{it.id==detailId})refreshPage()
    }
    fun historyResult(address:String,uid:List<String>,observedAt:Long,message:String,save:()->Unit){
        store.devices.filter{it.address.equals(address,true)&&it.uid==uid}.forEach{record->historyMessages[record.id]=message;historyResults[record.id]=HistoryResult(observedAt,save);if(pendingHistoryId==record.id)pendingHistoryId=null}
        if(pageId=="device")refreshPage()
    }
    private fun rememberRoute(){history.add(Route(pageId,detailId,scroll.scrollY));if(history.size>32)history.removeAt(0)}
    fun navigate(id:String){
        if(pageId=="network"&&id!="network"&&connectionsUi.confirmLeave{navigate(id)})return
        if(id=="network"&&pageId!="network")connectionsUi.openList()
        if(pageId=="network"&&id!="network"){returnToZigbeeImport=false;connectionsUi.detach()}
        if(id in listOf("devices","activity","settings"))history.clear() else if(id!=pageId)rememberRoute()
        pageId=id;detailId=null;renderPage();scroll.scrollTo(0,0)
    }
    fun showSession(){navigate("session")}
    private fun adoptCommon(){releaseLoad?.cancel();releaseLoad=scope.launch{runCatching{withContext(Dispatchers.IO){runtime.releases.adoptCurrentCommon()}}.onSuccess{if(it!=null)release=it}.onFailure{if(it is CancellationException)throw it;sourceNotice(it.message?:"Cannot select this firmware package.")};if(pageId!="session")refreshPage()}}
    fun commonReleasePending(value:Boolean){if(commonPending!=value){commonPending=value;renderPage();if(value&&releaseInitialised&&release==null&&!sourceBusy)adoptCommon()}}
    fun commonBootstrapPending(value:Boolean){if(bootstrapPending!=value){bootstrapPending=value;renderPage()}}
    fun serviceStatus(value:String){if(currentServiceStatus!=value){currentServiceStatus=value;if(pageId=="session"&&bootstrapPending)renderPage()}}
    fun isRegisteringDevice()=pageId=="add"
    fun offerIdentity(address:String,uid:List<String>){
        val existing=store.devices.firstOrNull{it.uid==uid||it.address==address}
        val record=existing?.copy(address=address,uid=uid)?:DeviceRecord(uid.joinToString(":"),"Vimar 30805",address=address,uid=uid)
        scope.launch{
            val observed=try{withTimeout(15000){while(state.busy)delay(50);withContext(Dispatchers.IO){runtime.inspectDevice(record,persist=false)}}}catch(e:CancellationException){if(!currentCoroutineContext().isActive)throw e;record}catch(_:Exception){record}
            editRecord(observed)
        }
    }
    fun back():Boolean {
        if(pageId=="network"&&connectionsUi.back())return true
        if(pageId=="network"){returnToZigbeeImport=false;connectionsUi.detach()}
        if(history.isNotEmpty()){
            val previous=history.removeAt(history.lastIndex);pageId=previous.page;detailId=previous.detail;renderPage();scroll.post{scroll.scrollTo(0,previous.offset)};return true
        }
        if(pageId!="devices"){navigate("devices");return true}
        return false
    }
    fun present(value:SessionPresentation){
        val previous=state
        state=value
        if(commonPending&&previous.busy&&!value.busy&&previous.operation==SessionOperation.IMPORT)adoptCommon()
        val batch=store.batches.firstOrNull{it.id==activeBatch && it.digest==value.packageSummary?.digest}
        if(batch!=null && runtime.queue.groups.value.none{g->g.jobs.any{it.route==FleetRoute.BLE&&it.state==FleetJobState.RUNNING}}){
            val next=when{value.busy && value.operation==SessionOperation.UPDATE->"In progress";value.operatorOnline==true && value.imagesVerified->"Online confirmed by owner";value.imagesVerified->"Firmware verified · confirm online";value.hasCheckpoint && !value.busy->"Paused · explicit resume required";previous.busy && previous.operation==SessionOperation.UPDATE && !value.busy->"Operation ended · see session report";else->batch.status}
            if(next!=batch.status){batch.status=next;store.save()}
        }
        // Keep scroll/focus while progress changes; the session panel owns its own live region.
        if(pageId=="session"){if(bootstrapPending)renderPage();return}
        if(pageId in listOf("device","settings","tools")&&(previous.busy!=value.busy || pageId=="tools"&&previous.reportAvailable!=value.reportAvailable)){refreshPage();return}
        if(pageId=="devices" && detailId==null && previous.busy==value.busy && previous.operation==value.operation && previous.packageSummary==value.packageSummary && previous.bluetoothVerified==value.bluetoothVerified && previous.imagesVerified==value.imagesVerified && previous.loaded==value.loaded && previous.observedMainHash==value.observedMainHash)return
        if(pageId=="activity" || pageId=="devices" || pageId=="updates"){val offset=scroll.scrollY;renderPage();scroll.post{scroll.scrollTo(0,offset)}}
    }
    fun beginBatch(pkg:PackageSummary,resume:Boolean){
        if(resume){
            val existing=store.batches.firstOrNull{it.digest==pkg.digest && it.status!="Online confirmed by owner"}
            if(existing!=null){activeBatch=existing.id;existing.expanded=true;store.preferences.edit().putString("activeBatch",existing.id).apply();store.save();return}
        }
        val record=store.devices.firstOrNull{FleetPolicy.matches(it,pkg)}
        val batch=ActivityBatch(UUID.randomUUID().toString(),pkg.digest,record?.name?:pkg.name,pkg.targetVersion,System.currentTimeMillis(),"Requested · waiting for updater")
        activeBatch=batch.id;store.preferences.edit().putString("activeBatch",batch.id).apply();store.batches.add(0,batch);store.save()
    }
    private fun renderPage(){
        deviceRows=null;networkEditButton.visibility=View.GONE;body.removeAllViews();footer.removeAllViews();footer.visibility=View.GONE
        val session=pageId=="session"&&!bootstrapPending
        sessionView.visibility=if(session)View.VISIBLE else View.GONE;scroll.visibility=if(session)View.GONE else View.VISIBLE
        title.maxLines=2
        title.text=when(pageId){"activity"->"Activity";"updates"->"Updates";"settings"->"Settings";"tools"->"Tools";"add"->"Add device";"device"->"Device";"session"->"Update session";"review"->"Review update";"network"->"Connections";"zigbee-import"->"Add device";else->"Devices"}
        subtitle.text=when(pageId){"devices"->"${store.devices.size} ${if(store.devices.size==1)"device" else "devices"} · saved on this phone";"activity"->"Update history";"updates"->"Firmware packages";"settings"->"Connections and preferences";"session"->"Bluetooth · selected dimmer";else->""}
        subtitle.visibility=if(subtitle.text.isBlank())View.GONE else View.VISIBLE
        backButton.visibility=if(pageId in listOf("devices","activity","settings"))View.GONE else View.VISIBLE
        addButton.visibility=if(pageId=="devices")View.VISIBLE else View.GONE
        addButton.isEnabled=true
        addButton.contentDescription=if(pageId=="network")"Add connection or topic" else "Add device"
        addButton.setOnClickListener{if(pageId=="network")connectionsUi.add() else navigate("add")}
        val selectedTab=when(pageId){"updates","network","tools"->"settings";"session"->"activity";"add","device","review","zigbee-import"->"devices";else->pageId}
        tabs.forEach{(id,view)->view.isSelected=id==selectedTab;NativeUi.navigation(activity,view,id,id==selectedTab);ViewCompat.setStateDescription(view,if(id==selectedTab)"Selected" else "")}
        when(pageId){"devices"->devices();"device"->deviceDetail();"activity"->activityPage();"updates"->updates();"settings"->settings();"tools"->tools();"add"->addDevice();"review"->reviewUpdate();"network"->connectionsUi.render(body);"zigbee-import"->zigbeeImportPage();"session"->{
            if(bootstrapPending){
                section("Prepare this dimmer for the release")
                copy("The selected dimmer uses an older Bluetooth updater. Its signed images will be checked before installing the common preparation component; then its live identity will be read.")
                copy("Keep it powered and stay nearby. No device identity file is required.")
                if(currentServiceStatus.isNotBlank())copy(currentServiceStatus).accessibilityLiveRegion=View.ACCESSIBILITY_LIVE_REGION_POLITE
                if(state.busy)add(ProgressBar(activity))
                action(if(state.busy)"Preparing dimmer…" else "Prepare dimmer",filled=true,enabled=!state.busy){prepareBluetoothUpdate()}
                if(state.busy)action("Stop after the current operation"){(activity as? MainActivity)?.stopCurrentUpdate()}
            }
            footer.visibility=View.VISIBLE;action("Back to Activity",footer){navigate("activity")}
        }}
    }
    private fun devices(){
        val available=release?.let{target->store.devices.filter{FleetPolicy.status(it,target).eligibility==Eligibility.UPDATE}}.orEmpty()
        if(available.isNotEmpty()){
            val strip=LinearLayout(activity).apply{gravity=Gravity.CENTER_VERTICAL;setPadding(dp(16),dp(10),dp(8),dp(10));background=NativeUi.shape(activity,color(R.color.ui_panel),10)}
            val info=column();info.addView(text("Firmware ${release!!.version}",15,true))
            add(text(if(available.size==1)"1 device can be updated" else "${available.size} devices can be updated",13,secondary=true),info,3)
            strip.addView(info,LinearLayout.LayoutParams(0,-2,1f))
            strip.addView(button("Review update"){selected.clear();selected.addAll(available.map{it.id});navigate("review")}.apply{tag="fleet.release.action";isEnabled=!state.busy})
            add(strip,gap=4)
        }
        if(store.devices.isEmpty()){
            section("Add your first dimmer")
            copy("Find a nearby dimmer or import one from Zigbee2MQTT.")
            action("Add device",filled=true){navigate("add")}
            action("Import from Zigbee"){networkImport()}
            return
        }
        val search=NativeUi.field(activity,"Search rooms or devices",query,input=NativeUi.Input.SEARCH)
        add(search, gap=20)
        val filterButton=NativeUi.button(activity,"Show  ·  $filter",outline=true){}.apply{setCompoundDrawablesWithIntrinsicBounds(null,null,NativeUi.Icon(activity,"down",color(R.color.ui_primary)),null);compoundDrawablePadding=dp(12)}
        DeviceFilterPopup(activity,filterButton,filters,{filters.indexOf(filter).coerceAtLeast(0)}){choice->filter=filters[choice];renderPage()}
        add(filterButton)
        val rows=column();deviceRows=rows;add(rows)
        search.addTextChangedListener(object:TextWatcher{override fun beforeTextChanged(s:CharSequence?,start:Int,count:Int,after:Int){};override fun onTextChanged(s:CharSequence?,start:Int,before:Int,count:Int){query=s.toString();renderDevices(rows)};override fun afterTextChanged(s:Editable?) {}})
        renderDevices(rows)
    }
    private fun activeZigbeeTopics():Set<String> = if(network.state.value.connected)
        runCatching { network.loadProfiles().firstOrNull{it.id==network.activeProfileId}?.networks.orEmpty().map{it.id}.toSet() }.getOrDefault(emptySet()) else emptySet()
    private fun renderDevices(rows:LinearLayout){
        rows.removeAllViews()
        val activeTopics=activeZigbeeTopics()
        val currentReports=network.state.value.devices.associateBy{it.networkId to it.ieee}
        val visible=store.devices.filter{r->(r.name+" "+r.room).contains(query,true) && when(filter){"Up to date"->deviceStatus(r).eligibility==Eligibility.CURRENT;"Update available"->deviceStatus(r).eligibility==Eligibility.UPDATE;"Not updatable"->deviceStatus(r).eligibility==Eligibility.BLOCKED;else->true}}
        if(visible.isEmpty())copy("No devices match this view.",rows)
        var updateSelectionSummary:()->Unit={}
        if(visible.isNotEmpty()){
            val selection=LinearLayout(activity).apply{gravity=Gravity.CENTER_VERTICAL}
            val count=text("",13,secondary=true)
            selection.addView(count,LinearLayout.LayoutParams(0,-2,1f))
            val selectVisible=button("Select visible"){
                if(visible.all{it.id in selected})visible.forEach{selected.remove(it.id)} else selected.addAll(visible.map{it.id})
                renderDevices(rows)
            }
            selection.addView(selectVisible)
            updateSelectionSummary={
                count.text=if(selected.isEmpty())"${visible.size} ${if(visible.size==1)"device" else "devices"}" else "${selected.size} selected"
                selectVisible.text=if(visible.all{it.id in selected})"Deselect visible" else "Select visible"
            }
            updateSelectionSummary()
            add(selection,rows,4)
        }
        visible.forEach{r->
            divider(rows,0)
            val row=LinearLayout(activity).apply{gravity=Gravity.CENTER_VERTICAL}
            val check=CheckBox(activity).apply{minWidth=dp(48);minHeight=dp(48);buttonTintList=ColorStateList.valueOf(color(R.color.ui_primary));contentDescription="Select ${r.name}";isChecked=selected.contains(r.id);setOnCheckedChangeListener{_,checked->if(checked)selected.add(r.id)else selected.remove(r.id);updateSelectionSummary();selectionFooter()}}
            row.addView(check,LinearLayout.LayoutParams(dp(48),-2))
            val info=column().apply{setPadding(dp(8),dp(16),dp(8),dp(16));isClickable=true;isFocusable=true;minimumHeight=dp(80);setBackgroundResource(android.R.drawable.list_selector_background);setOnClickListener{rememberRoute();detailId=r.id;pageId="device";renderPage();scroll.scrollTo(0,0)}}
            info.addView(text(r.name,16,true));val version=r.installedVersion?.let{if(r.networkId!=null&&(ZigbeeDeviceMetadata.savedReading(r,r.networkId in activeTopics,currentReports[r.networkId to r.ieee])))"$it (saved)" else it};val metadata=listOfNotNull(r.room.takeIf{it.isNotBlank()},version).joinToString(" · ");if(metadata.isNotBlank())add(text(metadata,13,secondary=true),info,4)
            val status=deviceStatus(r)
            add(text(status.label,13).apply{setTextColor(eligibilityColor(status.eligibility))},info,5)
            if(status.eligibility==Eligibility.BLOCKED)add(text(status.reason,13,secondary=true),info,4)
            row.addView(info,LinearLayout.LayoutParams(0,-2,1f))
            row.addView(ImageView(activity).apply{setImageDrawable(NativeUi.Icon(activity,"right",color(R.color.ui_text_secondary)));importantForAccessibility=View.IMPORTANT_FOR_ACCESSIBILITY_NO},LinearLayout.LayoutParams(dp(22),dp(22)))
            add(row,rows,0)
        }
        selectionFooter()
    }
    private fun selectionFooter(){
        footer.removeAllViews();footer.visibility=if(selected.isEmpty())View.GONE else View.VISIBLE
        if(selected.isEmpty())return
        copy("${selected.size} selected",footer,false)
        val compatible=store.devices.count{it.id in selected&&deviceStatus(it).eligibility==Eligibility.UPDATE}
        action("Review update · $compatible compatible",footer,filled=true,enabled=release!=null&&!state.busy&&!jobBusy){navigate("review")}
        if(release==null)copy("Choose firmware in Settings → Firmware updates.",footer)
        action("Clear selection",footer){selected.clear();renderPage()}
    }
    private fun eligibilityColor(status:Eligibility)=color(when(status){Eligibility.CURRENT->R.color.ui_current;Eligibility.UPDATE->R.color.ui_available;Eligibility.BLOCKED->R.color.ui_error})
    private fun deviceDetail(){
        val record=store.devices.firstOrNull{it.id==detailId}?:run{navigate("devices");return}
        title.text=record.name;title.maxLines=2;title.tooltipText=record.name
        if(record.room.isNotBlank())copy(record.room,secondary=false)
        val status=deviceStatus(record)
        copy(status.label,secondary=false).setTextColor(eligibilityColor(status.eligibility))
        val savedVersion=record.networkId!=null&&ZigbeeDeviceMetadata.savedReading(record,record.networkId in activeZigbeeTopics(),network.state.value.devices.firstOrNull{it.networkId==record.networkId&&it.ieee==record.ieee})
        copy(record.installedVersion?.let{"Firmware $it${if(savedVersion)" (saved)" else ""}"}?:"Firmware version not available.",secondary=false)
        if(status.eligibility==Eligibility.BLOCKED)copy(status.reason)
        if(release!=null&&status.eligibility==Eligibility.UPDATE)action("Review update",filled=true){selected.clear();selected.add(record.id);navigate("review")}
        val diagnostics=column()
        if(record.address!=null&&record.uid.size==2)action("Check Bluetooth",diagnostics,enabled=!state.busy&&!jobBusy){perform("Check Bluetooth"){withContext(Dispatchers.IO){runtime.inspectDevice(record)}}}
        if(record.networkId!=null&&record.ieee!=null){
            action("Check Zigbee update",diagnostics,enabled=network.state.value.connected&&!jobBusy){perform("Check Zigbee update"){val result=withContext(Dispatchers.IO){network.check(record.networkId,record.ieee)};sourceNotice(if(result.available)"An update is available. Compatibility is checked before installation." else "No update available.")}}
            action("Turn on Bluetooth",diagnostics,enabled=network.state.value.connected&&!jobBusy){AlertDialog.Builder(activity).setTitle("Turn on Bluetooth?").setMessage("${record.name} temporarily leaves Zigbee. Keep your phone nearby to connect.").setNegativeButton("Cancel",null).setPositiveButton("Turn on"){_,_->perform("Turn on Bluetooth"){withContext(Dispatchers.IO){network.prepareBluetooth(record.networkId,record.ieee)};navigate("add")}}.show()}
        }
        if(FleetPolicy.matches(record,state.packageSummary))action("Open update session",diagnostics){showSession()}
        if(record.address!=null&&record.uid.size==2&&record.firmwareKind!=FirmwareKind.STOCK){
            copy("Read saved restart history over Bluetooth.",diagnostics)
            action("Read recovery history",diagnostics,enabled=!state.busy&&!jobBusy&&historyReader!=null){historyReader?.invoke(record)}
            historyMessages[record.id]?.let{value->add(text(value,15).apply{accessibilityLiveRegion=View.ACCESSIBILITY_LIVE_REGION_POLITE;setPadding(dp(12),dp(12),dp(12),dp(12));background=NativeUi.shape(activity,color(R.color.ui_panel))},diagnostics)}
            historyResults[record.id]?.let{result->
                copy("Saved reading · ${DateFormat.getDateTimeInstance(DateFormat.SHORT,DateFormat.SHORT).format(Date(result.observedAt))}",diagnostics)
                action("Save history report",diagnostics){result.save()}
            }
        }
        if(diagnostics.childCount>0){
            add(NativeUi.disclosure(activity,"Diagnostics","Hide diagnostics",diagnostics,record.id in diagnosticsExpanded){if(it)diagnosticsExpanded.add(record.id)else diagnosticsExpanded.remove(record.id)});add(diagnostics,gap=0)
        }
        action("Edit name and room"){editRecord(record)}
        action("Remove from Devices"){
            AlertDialog.Builder(activity).setTitle("Remove ${record.name}?").setMessage("Only this phone’s organisational record is removed. Update checkpoints and reports are retained.").setNegativeButton("Cancel",null).setPositiveButton("Remove"){_,_->store.devices.removeAll{it.id==record.id};selected.remove(record.id);store.save();navigate("devices")}.show()
        }
        val information=column()
        if(record.networkId!=null){
            record.observedAt?.let{copy("Version received · ${DateFormat.getDateTimeInstance(DateFormat.SHORT,DateFormat.SHORT).format(Date(it))}",information)}
            copy(if(record.networkId in activeZigbeeTopics())"Zigbee2MQTT connected" else "Zigbee2MQTT disconnected",information)
            if(savedVersion)copy("Showing the last saved version.",information)
        }
        if(record.address!=null)copy("Bluetooth: ${record.address}",information)
        if(information.childCount>0){
            add(NativeUi.disclosure(activity,"Device information","Hide device information",information,record.id in informationExpanded){if(it)informationExpanded.add(record.id)else informationExpanded.remove(record.id)});add(information,gap=0)
        }
    }
    private fun addDevice(){
        section("Turn on Bluetooth")
        copy("With custom firmware, hold both buttons for 5 seconds. Keep the dimmer powered and nearby.")
        action("Search Bluetooth",filled=true,enabled=!state.busy){searchBluetooth()}
        val modes=column().apply{visibility=View.GONE}
        copy("Blue / green: a Bluetooth session. It returns to Zigbee after a minute without activity; an update keeps it open.",modes)
        copy("Blue / red: recovery. Hold both buttons for 5 seconds to request a safe return to Zigbee. Earlier firmware may need the app to exit recovery.",modes)
        action("About Bluetooth modes"){modes.visibility=if(modes.visibility==View.VISIBLE)View.GONE else View.VISIBLE}
        add(modes,gap=0)
        section("Import from Zigbee")
        copy("Choose devices from your saved Zigbee2MQTT connection.")
        action("Choose Zigbee devices"){networkImport()}
        settingRow("Update without adding a device","Choose a firmware package first"){navigate("updates")}
    }
    private fun editRecord(record:DeviceRecord){
        val form=column().apply{setPadding(dp(24),dp(8),dp(24),dp(16))}
        copy("Name",form,false)
        val name=NativeUi.field(activity,"Device name",record.name);add(name,form)
        copy("Room (optional)",form,false)
        val room=NativeUi.field(activity,"Room",record.room);add(room,form)
        val dialog=AlertDialog.Builder(activity).setTitle(if(store.devices.any{it.id==record.id})"Edit device" else "Save device").setView(form).setNegativeButton("Cancel",null).setPositiveButton("Save",null).create()
        dialog.setOnShowListener{dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener{val entered=name.text.toString().trim();if(entered.isEmpty())name.error="Enter a device name" else {store.upsert(record.copy(name=entered,room=room.text.toString().trim()));dialog.dismiss();navigate("devices")}}};dialog.show()
    }
    fun acceptZigbeeList(json:String){
        val rows=runCatching{JSONArray(json)}.getOrElse{sourceNotice("Choose a Zigbee2MQTT bridge/devices JSON array. This file could not be read.");return};val candidates=mutableListOf<DeviceRecord>()
        for(i in 0 until rows.length()){
            val row=rows.optJSONObject(i)?:continue;val definition=row.optJSONObject("definition")?:continue
            val model=definition.optString("model")
            val vendor=definition.optString("vendor")
            if(!FleetPolicy.recognisesZigbee(vendor,model))continue
            val ieee=row.optString("ieee_address");if(!ieee.matches(Regex("0x[0-9a-fA-F]{16}")))continue
            candidates.add(DeviceRecord("zigbee:$ieee",row.optString("friendly_name").ifBlank{ieee},""))
        }
        if(candidates.isEmpty()){sourceNotice("No supported Vimar 30805 records were found. Export the bridge/devices JSON array from Zigbee2MQTT.");return}
        val checked=BooleanArray(candidates.size)
        AlertDialog.Builder(activity).setTitle("Import from Zigbee").setMultiChoiceItems(candidates.map{it.name}.toTypedArray(),checked){_,which,value->checked[which]=value}.setNegativeButton("Cancel",null).setPositiveButton("Import selected"){_,_->candidates.forEachIndexed{i,r->if(checked[i])store.upsert(r)};navigate("devices")}.show()
    }
    private fun activityPage(){
        runtime.queue.groups.value.sortedByDescending{it.createdAt}.forEach{renderGroup(it)}
        if(store.batches.isEmpty()&&runtime.queue.groups.value.isEmpty()){
            section("No updates yet")
            copy("Updates appear here with their progress and results.")
            if(state.packageSummary!=null)action("Open update session",filled=true){showSession()} else action("Choose local ZIP…",filled=true,enabled=!state.busy&&!sourceBusy){choosePackage()}
            if(state.hasCheckpoint)copy("An unfinished update is saved. Open the update session to resume it.")
            return
        }
        store.batches.forEachIndexed{index,batch->
            val live=batch.id==activeBatch && batch.digest==state.packageSummary?.digest
            action("${if(batch.expanded)"Hide" else "Show"} group · ${DateFormat.getDateTimeInstance(DateFormat.SHORT,DateFormat.SHORT).format(Date(batch.startedAt))}") {batch.expanded=!batch.expanded;store.save();renderPage()}
            copy("1 device · ${batch.status}",secondary=false)
            if(batch.expanded){
                section(batch.deviceName);copy("Target ${batch.version} · Bluetooth")
                copy(batch.status)
                if(live){
                    if(state.busy && state.operation==SessionOperation.UPDATE){
                        add(ProgressBar(activity,null,android.R.attr.progressBarStyleHorizontal).apply{max=100;isIndeterminate=state.progressPercent==null;progress=state.progressPercent?:0;progressTintList=ColorStateList.valueOf(color(R.color.ui_primary));contentDescription=state.progressPercent?.let{"Transfer $it percent"}?:"Preparing update"})
                    }
                    action(if(state.busy)"Open progress and Stop" else if(state.hasCheckpoint && !state.imagesVerified)"Open session to resume" else "Open session details",filled=true){showSession()}
                    action("Export current report…",enabled=state.reportAvailable && !state.busy){exportReport()}
                } else copy("Earlier update · only its summary is available here.")
            }
            divider()
        }
    }
    private fun updates(){
        if(commonPending){
            if(release==null)section("Firmware ready")
            action("Choose Bluetooth dimmer",filled=true,enabled=!state.busy){searchBluetooth()}
        }
        release?.let{current->
            section("Firmware ${current.version}")
            copy("Package verified",secondary=false)
            if(current.zigbeeOta!=null){
                copy(if(current.zigbeeOta.source.isBlank())"Zigbee updates need a download URL. Bluetooth is available." else "Zigbee download verified.")
                action("Zigbee download URL"){val input=NativeUi.field(activity,"https://…/firmware.ota",current.zigbeeOta.source,input=NativeUi.Input.ADDRESS);val dialog=AlertDialog.Builder(activity).setTitle("Zigbee download URL").setView(input).setNegativeButton("Cancel",null).setPositiveButton("Verify URL"){_,_->perform("Verify carrier"){release=runtime.releases.setOtaSource(current,input.text.toString().trim())}}.create();dialog.show()}
            }
        }
        action(if(sourceBusy)"Checking for updates…" else "Check for updates",filled=!commonPending,enabled=!sourceBusy){checkReleases()}
        if(sourceMessage.isNotBlank())copy(sourceMessage).accessibilityLiveRegion=View.ACCESSIBILITY_LIVE_REGION_POLITE
        section("From this phone")
        action("Choose local ZIP…",enabled=!state.busy&&!sourceBusy){choosePackage()}
        state.packageSummary?.let{pkg->copy("Selected firmware: ${pkg.targetVersion}",secondary=false);action("Open update session"){showSession()}}
        val source=column()
        val repo=store.preferences.getString("source",ReleaseSource.DEFAULT)?:ReleaseSource.DEFAULT
        copy(repo,source,false);action("Change source",source){editSource()}
        add(NativeUi.disclosure(activity,"Download source","Hide download source",source,sourceSettingsExpanded){sourceSettingsExpanded=it},gap=16);add(source,gap=0)
        val details=column()
        copy("Only packages signed with this app’s trusted firmware key are accepted.",details)
        copy("Device compatibility is checked again before an update starts.",details)
        add(NativeUi.disclosure(activity,"Package details","Hide package details",details,packageDetailsExpanded){packageDetailsExpanded=it},gap=0);add(details,gap=0)
        if(!releasesChecked && store.preferences.getBoolean("autoCheck",true)){releasesChecked=true;checkReleases()}
    }
    private fun editSource(){
        val input=NativeUi.field(activity,"https://github.com/owner/repository",store.preferences.getString("source",ReleaseSource.DEFAULT) ?: ReleaseSource.DEFAULT,input=NativeUi.Input.ADDRESS)
        val dialog=AlertDialog.Builder(activity).setTitle("GitHub release source").setView(input).setNegativeButton("Cancel",null).setNeutralButton("Use project default"){_,_->setSource(ReleaseSource.DEFAULT)}.setPositiveButton("Save",null).create()
        dialog.setOnShowListener{dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener{val parsed=ReleaseSource.parse(input.text.toString());if(parsed==null)input.error="Enter a public GitHub owner/repository URL" else{setSource("https://github.com/$parsed");dialog.dismiss()}}};dialog.show()
    }
    private fun setSource(source:String){releaseFetch?.cancel();sourceBusy=false;store.preferences.edit().putString("source",source).apply();sourceMessage="Source saved. Check for updates to download firmware.";releasesChecked=true;renderPage()}
    private fun checkReleases(){
        if(sourceBusy)return
        val source=store.preferences.getString("source",ReleaseSource.DEFAULT)?:ReleaseSource.DEFAULT
        sourceBusy=true;releasesChecked=true;sourceMessage="Downloading and verifying the latest stable release…";if(pageId=="updates")renderPage()
        releaseFetch=scope.launch{
            val result=try{Result.success(runtime.releases.fetchLatest(source))}catch(e:CancellationException){throw e}catch(e:Exception){Result.failure(e)}
            sourceBusy=false
            if(source==store.preferences.getString("source",ReleaseSource.DEFAULT)){
                result.onSuccess{release=it}
                sourceMessage=result.fold({"Release ${it.version} downloaded and signature verified."},{when{it.message?.contains("HTTP 404")==true->"The repository or a published release is not available yet. Choose a local ZIP or change the source.";it.message?.contains("HTTP 403")==true||it.message?.contains("HTTP 429")==true->"GitHub’s request limit was reached. Try later or choose a local ZIP.";else->it.message?:"Cannot fetch this release. Try again or choose a local ZIP."}})
                if(pageId=="updates")renderPage()
            }
        }
    }
    private fun settings(){
        val themes=arrayOf("System","Light","Dark")
        val theme=store.preferences.getString("theme","System")?:"System"
        settingRow("Appearance",theme){
            AlertDialog.Builder(activity).setTitle("Appearance").setSingleChoiceItems(themes,themes.indexOf(theme)){dialog,which->store.preferences.edit().putString("theme",themes[which]).apply();dialog.dismiss();activity.recreate()}.setNegativeButton("Cancel",null).show()
        }
        settingRow("Firmware updates","Download a release or choose a ZIP"){navigate("updates")}
        section("Connections")
        val connections=runCatching{
            if(network.state.value.connected)"${network.loadProfile()?.label} · Connected"
            else {val count=network.loadProfiles().size;"$count saved ${if(count==1)"connection" else "connections"} · Not connected"}
        }.getOrDefault("Saved connections unavailable")
        settingRow("Zigbee2MQTT",connections){navigate("network")}
        settingRow("Bluetooth","Android permissions and pairing"){requestBluetooth()}
        section("Advanced")
        settingRow("Tools","Initial setup, recovery and diagnostics"){navigate("tools")}
        section("Release checks")
        add(CheckBox(activity).apply{text="Check GitHub when Updates opens";setTextColor(color(R.color.ui_text));minHeight=dp(48);isChecked=store.preferences.getBoolean("autoCheck",true);setOnCheckedChangeListener{_,checked->store.preferences.edit().putBoolean("autoCheck",checked).apply()}})
        val appVersion=runCatching{activity.packageManager.getPackageInfo(activity.packageName,0).versionName}.getOrNull()
        copy(listOfNotNull("Vimar Updater",appVersion).joinToString(" · "))
    }
    private fun tools(){
        section("Install")
        settingRow("First installation","Back up a stock dimmer and review its first installation with the DK"){activity.startActivity(Intent(activity,InitialInstallActivity::class.java))}
        section("Check and recover")
        settingRow("DK tools","Check contacts, read identity or save an original backup"){activity.startActivity(Intent(activity,DkUsbDiagnosticsActivity::class.java))}
        settingRow("Bluetooth trial","Inspect and review a signed test package for one nearby dimmer"){activity.startActivity(Intent(activity,BleTrialActivity::class.java))}
        if(state.reportAvailable){section("Reports");action("Save latest update report",enabled=!state.busy){exportReport()}}
    }
    private fun reviewUpdate(){
        val target=release?:run{copy("Choose a firmware package first.");action("Choose release"){navigate("updates")};return}
        val records=store.devices.filter{it.id in selected}
        val included=records.filter{deviceStatus(it).eligibility==Eligibility.UPDATE}
        val excluded=records-included.toSet()
        copy("${included.size} compatible · ${excluded.size} excluded",secondary=false)
        copy("Firmware ${target.version}. Keep this phone nearby for Bluetooth updates.")
        section("Run order")
        val modes=RadioGroup(activity)
        listOf("Sequential" to "Finish one dimmer before starting the next.","Across networks" to "One Zigbee update per network and one Bluetooth connection.").forEachIndexed{i,(label,help)->modes.addView(RadioButton(activity).apply{id=View.generateViewId();text="$label\n$help";textSize=14f;setTextColor(color(R.color.ui_text));setPadding(0,dp(8),0,dp(8));minHeight=dp(64);tag=i})}
        modes.check(modes.getChildAt(0).id);add(modes)
        section("Devices to update")
        included.forEach{r->copy(r.name,secondary=false);copy("${r.installedVersion} → ${target.version} · ${if(FleetPolicy.route(r,target)==FleetRoute.ZIGBEE)"Zigbee OTA" else "Bluetooth"}");divider()}
        if(excluded.isNotEmpty()){section("Excluded from this group");excluded.forEach{copy(it.name,secondary=false);copy(deviceStatus(it).reason)}}
        action("Start ${included.size} ${if(included.size==1)"update" else "updates"}",filled=true,enabled=included.isNotEmpty()&&!jobBusy&&!state.busy){
            runCatching{
                val mode=if(modes.findViewById<RadioButton>(modes.checkedRadioButtonId).tag==1)FleetMode.NETWORK_PARALLEL else FleetMode.SEQUENTIAL
                val group=runtime.queue.createGroup(included,target,mode)
                openGroups.add(group.id);selected.clear();navigate("activity")
                FleetUpdateService.command(activity,FleetUpdateService.START,group.id)
            }.onFailure{sourceNotice(it.message?:"Could not save this group. No update was started.")}
        }
    }
    private fun renderGroup(group:FleetGroup){
        val expanded=group.id in openGroups
        val count=group.jobs.count{it.state==FleetJobState.VERIFIED}
        val updating=group.jobs.count{it.state==FleetJobState.RUNNING}
        val attention=group.jobs.count{it.state in setOf(FleetJobState.WAITING_NEARBY,FleetJobState.PAUSED,FleetJobState.UNCERTAIN_RESET,FleetJobState.AWAITING_RETURN,FleetJobState.BLOCKED,FleetJobState.FAILED)}
        val label=when{count==group.jobs.size->"Complete";updating>0->"In progress";group.cancelled->"Cancelled · check unresolved devices";group.paused->"Paused";else->"Waiting"}
        val stamp=DateFormat.getDateTimeInstance(DateFormat.SHORT,DateFormat.SHORT).format(Date(group.createdAt))
        val row=column().apply{minimumHeight=dp(80);setPadding(0,dp(14),0,dp(14));isClickable=true;isFocusable=true;setBackgroundResource(android.R.drawable.list_selector_background);setOnClickListener{if(expanded)openGroups.remove(group.id)else openGroups.add(group.id);refreshPage()};contentDescription="${group.jobs.size} devices, release ${group.release.version}. $label. ${if(expanded)"Collapse" else "Expand"} group"}
        row.addView(text(if(group.jobs.size==1)group.jobs.single().device.name else "${group.jobs.size} devices · Release ${group.release.version}",16,true))
        add(text("$count of ${group.jobs.size} completed",13,secondary=true),row,4)
        add(text("$updating updating · ${if(attention==1)"1 needs attention" else "$attention need attention"}",13,secondary=true),row,4)
        val stateLine=LinearLayout(activity).apply{gravity=Gravity.CENTER_VERTICAL}
        stateLine.addView(text(label,13),LinearLayout.LayoutParams(0,-2,1f))
        stateLine.addView(ImageView(activity).apply{setImageDrawable(NativeUi.Icon(activity,"down",color(R.color.ui_primary)));rotation=if(expanded)180f else 0f;importantForAccessibility=View.IMPORTANT_FOR_ACCESSIBILITY_NO},LinearLayout.LayoutParams(dp(22),dp(22)))
        add(stateLine,row,4);add(row,gap=0)
        if(expanded){
            copy("$stamp · ${if(group.mode==FleetMode.SEQUENTIAL)"Sequential" else "One update per network · one Bluetooth connection"}")
            if(!group.cancelled&&count!=group.jobs.size){
                val options=column()
                action(if(group.paused)"Resume group" else "Pause group",options,enabled=!jobBusy){if(group.paused)FleetUpdateService.command(activity,FleetUpdateService.RESUME,group.id)else runtime.queue.pause(group.id)}
                action("Cancel remaining updates",options){AlertDialog.Builder(activity).setTitle("Cancel remaining updates?").setMessage("Already submitted Zigbee updates may continue. Their network remains reserved until their outcome is checked.").setNegativeButton("Keep group",null).setPositiveButton("Cancel remaining"){_,_->runtime.queue.cancel(group.id)}.show()}
                add(NativeUi.disclosure(activity,"Group options","Hide group options",options,group.id in openGroupOptions){if(it)openGroupOptions.add(group.id)else openGroupOptions.remove(group.id)},gap=0);add(options,gap=0)
            }
            group.jobs.forEach{job->
                val shown=(group.jobs.size==1&&job.id !in closedJobs)||job.id in openJobs
                val item=column().apply{
                    tag="fleet.job.${job.id}";minimumHeight=dp(64);setPadding(dp(8),dp(12),dp(8),dp(12));isClickable=true;isFocusable=true
                    background=NativeUi.shape(activity,if(shown)color(R.color.ui_panel) else android.graphics.Color.TRANSPARENT)
                    contentDescription="${job.device.name}. ${jobLabel(job.state)}. ${if(shown)"Hide" else "Show"} device details"
                    setOnClickListener{if(shown){openJobs.remove(job.id);closedJobs.add(job.id)}else{openJobs.add(job.id);closedJobs.remove(job.id)};refreshPage()}
                }
                val itemTitle=LinearLayout(activity).apply{gravity=Gravity.CENTER_VERTICAL}
                itemTitle.addView(text(job.device.name,16,true),LinearLayout.LayoutParams(0,-2,1f))
                itemTitle.addView(ImageView(activity).apply{setImageDrawable(NativeUi.Icon(activity,"down",color(R.color.ui_text_secondary)));rotation=if(shown)180f else 0f;importantForAccessibility=View.IMPORTANT_FOR_ACCESSIBILITY_NO},LinearLayout.LayoutParams(dp(22),dp(22)))
                item.addView(itemTitle)
                add(text("${if(job.route==FleetRoute.BLE)"Bluetooth" else "Zigbee OTA"} · ${if(job.route==FleetRoute.BLE&&job.state==FleetJobState.AWAITING_RETURN)"Firmware verified · waiting for Zigbee" else jobLabel(job.state)}",13,secondary=true),item,4)
                add(item,gap=4)
                if(shown){
                    copy(job.message)
                if(job.state==FleetJobState.RUNNING)add(ProgressBar(activity,null,android.R.attr.progressBarStyleHorizontal).apply{max=100;isIndeterminate=job.progress==null;progress=job.progress?:0;progressTintList=ColorStateList.valueOf(color(R.color.ui_primary));contentDescription=job.progress?.let{"Transfer $it percent"}?:"Checking this dimmer"})
                if(job.state==FleetJobState.WAITING_NEARBY&&!group.paused){
                    copy("Stand near this dimmer and enable its Bluetooth mode. Only this selected device will be updated.")
                    if(job.device.networkId!=null&&job.device.ieee!=null)action("Enable Bluetooth from Zigbee",enabled=network.state.value.connected&&!jobBusy){perform("Enable Bluetooth"){withContext(Dispatchers.IO){network.prepareBluetooth(job.device.networkId,job.device.ieee)}}}
                    action("Phone nearby · continue",filled=true){FleetUpdateService.command(activity,FleetUpdateService.NEARBY,group.id,job.id)}
                }
                if(job.route==FleetRoute.ZIGBEE&&job.state in setOf(FleetJobState.UNCERTAIN_RESET,FleetJobState.AWAITING_RETURN))action("Check server status",filled=true,enabled=!jobBusy&&network.state.value.connected){perform("Check update status"){runtime.queue.reconcile(job.id,FleetJobReconciler{network.reconcile(it)})}}
                if(job.route==FleetRoute.BLE&&job.state in setOf(FleetJobState.PAUSED,FleetJobState.UNCERTAIN_RESET,FleetJobState.AWAITING_RETURN)){
                    action("Verify firmware over Bluetooth",filled=job.state!=FleetJobState.AWAITING_RETURN,enabled=!jobBusy&&!state.busy){perform("Read update evidence"){withContext(Dispatchers.IO){runtime.refreshBleEvidence(job.id)}}}
                    action("Open device session",enabled=!jobBusy&&!state.busy){perform("Select device session"){withContext(Dispatchers.IO){runtime.selectBleSession(job.id)};(activity as? MainActivity)?.refreshSelectedSession();showSession()}}
                }
                if(job.route==FleetRoute.BLE&&job.state==FleetJobState.AWAITING_RETURN)action("Confirm this dimmer is back online",filled=true){AlertDialog.Builder(activity).setTitle("Is ${job.device.name} back online?").setMessage("Confirm only after checking this exact dimmer in Zigbee2MQTT or Home Assistant.").setNegativeButton("Not yet",null).setPositiveButton("Back online"){_,_->FleetUpdateService.command(activity,FleetUpdateService.RETURN,group.id,job.id)}.show()}

                }
                divider(gap=4)
            }
        }
        divider(gap=0)
    }
    private fun jobLabel(state:FleetJobState)=when(state){
        FleetJobState.QUEUED->"Queued";FleetJobState.WAITING_NEARBY->"Phone needed";FleetJobState.RUNNING->"Updating";FleetJobState.PAUSED->"Paused";FleetJobState.UNCERTAIN_RESET->"Outcome needs checking";FleetJobState.AWAITING_RETURN->"Waiting for return";FleetJobState.VERIFIED->"Completed";FleetJobState.BLOCKED->"Not updatable";FleetJobState.FAILED->"Needs attention";FleetJobState.CANCELLED->"Cancelled"
    }
    private fun networkImport(){navigate("zigbee-import")}
    private fun zigbeeImportPage(){
        action("Find nearby devices"){navigate("add")}
        section("From Zigbee2MQTT")
        val profile=runCatching{network.loadProfiles().firstOrNull{it.id==network.activeProfileId}}.getOrNull()
        if(!network.state.value.connected || profile==null){copy("Connect to Zigbee2MQTT to find devices.");action("Choose connection",filled=true){returnToZigbeeImport=true;navigate("network")};action("Import an exported device list"){importZigbee()};return}
        if(importProfile!=profile.id){importProfile=profile.id;zigbeeSelection.clear();zigbeeTopicFilter=null}
        copy("${profile.label} · Connected")
        action("Refresh",enabled=!jobBusy){perform("Refresh devices"){withContext(Dispatchers.IO){network.refreshInventory()}}}
        if(profile.networks.size>1){
            val options=listOf("All topics")+profile.networks.map{it.label}
            val button=NativeUi.button(activity,"Zigbee topic · ${profile.networks.firstOrNull{it.id==zigbeeTopicFilter}?.label?:"All topics"}",outline=true){}
            DeviceFilterPopup(activity,button,options,{profile.networks.indexOfFirst{it.id==zigbeeTopicFilter}+1}){position->zigbeeTopicFilter=profile.networks.getOrNull(position-1)?.id;renderPage()};add(button)
        }
        if(zigbeeTopicFilter!=null&&profile.networks.none{it.id==zigbeeTopicFilter})zigbeeTopicFilter=null
        val candidates=network.state.value.devices.filter{zigbeeTopicFilter==null || it.networkId==zigbeeTopicFilter}
        val received=network.state.value.inventoryReceived
        if(candidates.isEmpty())copy(if(!received)"Waiting for Zigbee2MQTT devices…" else "No supported dimmers found in these topics.")
        val selectedText=copy("${zigbeeSelection.size} selected")
        val submit=button("Add selected (${zigbeeSelection.size})",filled=true){
            network.state.value.devices.filter{it.id in zigbeeSelection && profile.networks.any{n->n.id==it.networkId}}.forEach{r->
                if(store.devices.none{it.networkId==r.networkId&&it.ieee==r.ieee})store.upsert(r)
            };zigbeeSelection.clear();navigate("devices")
        }
        candidates.forEach{candidate->
            val topic=profile.networks.firstOrNull{it.id==candidate.networkId}
            val already=store.devices.any{it.networkId==candidate.networkId&&it.ieee==candidate.ieee}
            val row=LinearLayout(activity).apply{gravity=Gravity.CENTER_VERTICAL;minimumHeight=dp(80);isFocusable=true}
            val check=CheckBox(activity).apply{isChecked=candidate.id in zigbeeSelection;isEnabled=!already&&topic!=null;minWidth=dp(48);contentDescription="${candidate.name}. ${topic?.label?:"Topic unavailable"}"}
            val info=column();info.addView(text(candidate.name,16,true));info.addView(text(topic?.label?:"Topic unavailable",13,secondary=true));if(already)info.addView(text("Already added",13,secondary=true))
            row.addView(check,LinearLayout.LayoutParams(dp(56),dp(56)));row.addView(info,LinearLayout.LayoutParams(0,-2,1f))
            check.setOnCheckedChangeListener{_,v->if(v)zigbeeSelection.add(candidate.id)else zigbeeSelection.remove(candidate.id);selectedText.text="${zigbeeSelection.size} selected";submit.text="Add selected (${zigbeeSelection.size})";submit.isEnabled=zigbeeSelection.isNotEmpty()}
            row.setOnClickListener{if(check.isEnabled)check.performClick()};add(row);divider(gap=0)
        }
        zigbeeSelection.retainAll(network.state.value.devices.filter{r->profile.networks.any{it.id==r.networkId}}.map{it.id}.toSet())
        submit.isEnabled=zigbeeSelection.isNotEmpty();add(submit)
        action("Edit topics"){rememberRoute();pageId="network";connectionsUi.openTopics(profile.id);renderPage();scroll.scrollTo(0,0)}
    }
    private fun watch(field:EditText,changed:(String)->Unit){
        field.addTextChangedListener(object:TextWatcher{
            override fun beforeTextChanged(s:CharSequence?,start:Int,count:Int,after:Int){}
            override fun onTextChanged(s:CharSequence?,start:Int,before:Int,count:Int){changed(s.toString())}
            override fun afterTextChanged(s:Editable?){}
        })
    }
    fun sourceNotice(message:String){AlertDialog.Builder(activity).setTitle("Vimar Updater").setMessage(message).setPositiveButton("Close",null).show()}
}
