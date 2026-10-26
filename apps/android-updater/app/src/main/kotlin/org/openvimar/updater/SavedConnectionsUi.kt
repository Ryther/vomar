package org.openvimar.updater

import android.app.Activity
import android.app.AlertDialog
import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.Gravity
import android.view.View
import android.widget.*
import kotlinx.coroutines.*
import java.util.UUID

/** Screen-local drafts never contain a username, password, or execution authority. */
internal class SavedConnectionsUi(
    private val activity:Activity,
    private val network:AndroidNetworkOwner,
    private val scope:CoroutineScope,
    private val header:(String,String,Boolean,Boolean)->Unit,
    private val onConnected:()->Unit,
    private val offlineImport:()->Unit,
    private val dock:(View?)->Unit={},
    private val headerState:(String?,Int?)->Unit={_,_->}
) {
    private var parent:LinearLayout?=null
    private var screen="list"
    private var profileId:String?=null
    private var topicId:String?=null
    private var topicName=""
    private var topicBase=""
    private var returnFromTopics=false
    private var draft:BrokerProfile?=null
    private var dirty=false
    private var busy=false
    private var task:Job?=null
    private var failure:String?=null
    private var pendingRemoval:String?=null
    private val connectionErrors=mutableMapOf<String,String>()
    private var statusView:TextView?=null
    private var availabilityRefresh:(()->Unit)?=null
    private var secretFields=mutableListOf<EditText>()
    private val controls=mutableListOf<View>()
    private fun id()=UUID.randomUUID().toString()
    private fun dp(n:Int)=NativeUi.dp(activity,n)
    private fun current()=profileId?.let{runCatching{network.profile(it)}.getOrNull()}
    private fun online()=network.state.value.connected && network.activeProfileId==profileId
    private fun column()=LinearLayout(activity).apply{orientation=LinearLayout.VERTICAL}
    private fun add(view:View,container:LinearLayout=parent!!,gap:Int=8):View {container.addView(view,LinearLayout.LayoutParams(-1,-2).apply{topMargin=dp(gap)});return view}
    private fun text(value:String,strong:Boolean=false,secondary:Boolean=true,container:LinearLayout=parent!!)=NativeUi.label(activity,value,if(strong)20 else 15,strong,secondary).also{add(it,container)}
    private fun action(label:String,enabled:Boolean=true,filled:Boolean=false,container:LinearLayout=parent!!,run:()->Unit)=NativeUi.button(activity,label,filled){if(!busy)run()}.also{it.isEnabled=enabled&&!busy;controls.add(it);add(it,container)}
    private fun formActions(label:String,enabled:Boolean=true,cancel:()->Unit,save:()->Unit):Button {
        val row=LinearLayout(activity).apply{gravity=Gravity.END or Gravity.CENTER_VERTICAL}
        val cancelButton=NativeUi.button(activity,"Cancel"){if(!busy)cancel()}
        val saveButton=NativeUi.button(activity,label,filled=true){if(!busy)save()}.apply{isEnabled=enabled&&!busy}
        row.addView(cancelButton,LinearLayout.LayoutParams(-2,-2))
        row.addView(saveButton,LinearLayout.LayoutParams(0,-2,1f).apply{leftMargin=dp(8)})
        controls.addAll(listOf(cancelButton,saveButton));add(row,gap=16);return saveButton
    }
    private fun field(label:String,value:String,input:NativeUi.Input=NativeUi.Input.TEXT,changed:(String)->Unit):EditText {
        text(label,secondary=false)
        return NativeUi.field(activity,label,value,input=input).also { f->add(f);controls.add(f);f.addTextChangedListener(object:TextWatcher{
            override fun beforeTextChanged(s:CharSequence?,start:Int,count:Int,after:Int){}
            override fun onTextChanged(s:CharSequence?,start:Int,before:Int,count:Int){dirty=true;changed(s.toString())}
            override fun afterTextChanged(s:Editable?){}
        }) }
    }
    private fun row(label:String,description:String,run:()->Unit) {
        val r=LinearLayout(activity).apply{gravity=Gravity.CENTER_VERTICAL;minimumHeight=dp(72);isClickable=true;isFocusable=true;setPadding(0,dp(12),0,dp(12));setBackgroundResource(android.R.drawable.list_selector_background);contentDescription="$label. $description";setOnClickListener{if(!busy)run()}}
        val info=column();info.addView(NativeUi.label(activity,label,16,true));info.addView(NativeUi.label(activity,description,13,secondary=true))
        r.addView(info,LinearLayout.LayoutParams(0,-2,1f));r.addView(ImageView(activity).apply{setImageDrawable(NativeUi.Icon(activity,"right",activity.getColor(R.color.ui_text_secondary)));importantForAccessibility=View.IMPORTANT_FOR_ACCESSIBILITY_NO},LinearLayout.LayoutParams(dp(24),dp(24)))
        controls.add(r);add(r,gap=0);add(View(activity).apply{setBackgroundColor(activity.getColor(R.color.ui_line))},gap=0).layoutParams.height=dp(1)
    }
    private fun editableRow(label:String,description:String,key:String,kind:String,canRemove:Boolean,open:()->Unit,edit:()->Unit,remove:()->Unit) {
        val r=LinearLayout(activity).apply{gravity=Gravity.CENTER_VERTICAL;minimumHeight=dp(64);contentDescription="$label. $description";isClickable=true;isFocusable=true;setOnClickListener{if(!busy){if(pendingRemoval==key){pendingRemoval=null;draw()}else open()}}}
        val info=column();info.addView(NativeUi.label(activity,label,16,true));info.addView(NativeUi.label(activity,description,13,secondary=true))
        r.addView(info,LinearLayout.LayoutParams(0,-2,1f))
        if(pendingRemoval==key){
            val confirm=NativeUi.button(activity,"Delete",filled=true,danger=true){if(!busy&&canRemove){pendingRemoval=null;remove()}}.apply{contentDescription="Confirm remove $kind $label";isEnabled=canRemove&&!busy}
            controls.add(confirm);r.addView(confirm,LinearLayout.LayoutParams(-2,-2).apply{marginStart=dp(8)})
        } else {
            val editButton=NativeUi.actionIcon(activity,"edit","Edit $kind $label"){if(!busy){pendingRemoval=null;edit()}}
            val trash=NativeUi.actionIcon(activity,"trash","Remove $kind $label",danger=true){if(!busy&&canRemove){pendingRemoval=key;draw()}}.apply{isEnabled=canRemove&&!busy}
            listOf(editButton,trash).forEach{controls.add(it);r.addView(it,LinearLayout.LayoutParams(dp(48),dp(48)))}
        }
        controls.add(r);add(r,gap=0)
        add(View(activity).apply{setBackgroundColor(activity.getColor(R.color.ui_line))},gap=0).layoutParams.height=dp(1)
    }
    private fun section(title:String){text(title,strong=true,secondary=false).let{(it.layoutParams as LinearLayout.LayoutParams).topMargin=dp(24)}}
    fun showDetail(id:String){profileId=id;draft=null;dirty=false;go("detail")}
    fun openList(){screen="list";draft=null;dirty=false;failure=null;returnFromTopics=false}
    fun openTopics(id:String){profileId=id;screen="topics";draft=null;dirty=false;failure=null;returnFromTopics=true}
    fun render(container:LinearLayout) {parent=container;draw()}
    private fun draw() {
        val container=parent ?: return
        availabilityRefresh=null;dock(null);headerState(null,null)
        val retainedDirty=dirty;secretFields.forEach{it.text.clear()};secretFields.clear();dirty=retainedDirty;controls.clear();statusView=null;container.removeAllViews()
        val p=current()
        header(when(screen){"list"->"Connections";"detail"->p?.label?:"Connection";"edit"->if(p==null)"Add connection" else "Edit connection";"topics"->"Zigbee topics";"topic"->if(topicId==null)"Add topic" else "Edit topic";else->"Change credentials"},
            when(screen){"list"->"Zigbee2MQTT";"topics","topic","credentials"->p?.label?:draft?.label.orEmpty();else->""},screen=="list" || screen=="topics",screen=="detail")
        when(screen){"list"->list();"detail"->detail();"edit"->edit();"topics"->topics();"topic"->topic();"credentials"->credentials()}
        failure?.let { text(it,secondary=false).apply{setTextColor(activity.getColor(R.color.ui_error));accessibilityLiveRegion=View.ACCESSIBILITY_LIVE_REGION_POLITE} }
        if(busy){controls.forEach{it.isEnabled=false};text("Working…")}
    }
    val canAdd:Boolean get()=!busy&&(screen=="list"||screen=="topics"&&(draft?:current())?.networks.orEmpty().size<3)
    fun add() {if(busy)return;when(screen){"list"->{profileId=null;draft=BrokerProfile(id(),"",emptyList(),label="");dirty=false;go("edit")};"topics"->{if((draft?:current())?.networks.orEmpty().size<3){topicId=null;go("topic")}}}}
    fun editCurrent(){if(!busy){draft=current();dirty=false;go("edit")}}
    private fun go(next:String){
        if(next=="topic"){val n=(draft?:current())?.networks?.firstOrNull{it.id==topicId};topicName=n?.label.orEmpty();topicBase=n?.baseTopic.orEmpty();dirty=false}
        if(next=="topics")dirty=draft!=null
        if(next=="detail"||next=="list")dirty=false
        failure=null;pendingRemoval=null;screen=next;draw()
    }
    private fun list() {
        text("Saved on this phone")
        val profiles=try{network.loadProfiles()}catch(_:Exception){text("Saved connections could not be read. Your data has not been changed.",secondary=false);return}
        if(profiles.isEmpty()){text("No saved connections",true,false);text("Save your broker and Zigbee2MQTT topics on this phone.");action("Add connection"){add()}}
        profiles.forEach { p->
            editableRow(p.label,"${if(network.state.value.connected&&network.activeProfileId==p.id)"Connected" else "Not connected"} · ${p.networks.size} ${if(p.networks.size==1)"topic" else "topics"}","profile:${p.id}","connection",!network.connectionInUse(p),
                open={showDetail(p.id)},edit={profileId=p.id;draft=p;dirty=false;go("edit")},
                remove={operate{network.removeProfile(p.id)}})
        }
        if(profiles.size>1)text("One active connection at a time.")
        action("Import from a file"){offlineImport()}
    }
    private fun detail() {
        val p=current() ?: run{screen="list";draw();return}
        val error=connectionErrors[p.id]!=null || network.activeProfileId==p.id&&network.state.value.connectionError
        if(online())connectionErrors.remove(p.id)
        headerState(if(online())"Connected" else if(error)"Connection error" else "Not connected",activity.getColor(if(online())R.color.ui_current else if(error)R.color.ui_available else R.color.ui_error))
        section("Broker address");text(p.serverUri)
        section("Credentials")
        val saved=network.hasCredentials(p)
        val unavailable=saved&&!network.credentialsAvailable(p)
        text(if(unavailable)"Saved credentials unavailable" else if(saved)"Credentials saved on this phone" else "No credentials saved",secondary=false)
        action(if(saved)"Change credentials" else "Add credentials"){dirty=false;go("credentials")}
        val rule=View(activity).apply{setBackgroundColor(activity.getColor(R.color.ui_line))}
        add(rule,gap=24).layoutParams.height=dp(1)
        row("Zigbee topics (${p.networks.size})",p.networks.joinToString(" · "){it.label}){draft=null;go("topics")}
        val held=network.connectionInUse(p)
        if(held)text("Wait for the current update to finish.")
        val connectButton=NativeUi.button(activity,if(online())"Disconnect" else "Connect",filled=!online()){
            if(!busy){if(online())operate{network.disconnect()}else connect(p)}
        }.apply{isEnabled=!held&&!busy;tag="connection.connect"}
        controls.add(connectButton);dock(connectButton)
    }
    private fun connect(p:BrokerProfile) {
        connectionErrors.remove(p.id)
        val other=network.loadProfiles().firstOrNull{it.id==network.activeProfileId&&it.id!=p.id&&network.state.value.connected}
        if(other!=null)AlertDialog.Builder(activity).setTitle("Switch to ${p.label}?").setMessage("${other.label} will disconnect. Its settings stay saved.").setNegativeButton("Cancel",null).setPositiveButton("Switch and connect"){_,_->operate(connecting=true){network.connect(p)}}.show()
        else operate(connecting=true){network.connect(p)}
    }
    private fun showIssues(issues:List<BrokerValidationIssue>) {
        var first:EditText?=null
        issues.forEach { issue->
            val label=when(issue.field){BrokerValidationField.BROKER->if(issue.message.contains("connection name"))"Connection name (required)" else "Broker address (required)";BrokerValidationField.NETWORK_NAME->"Topic name (required)";BrokerValidationField.BASE_TOPIC->"MQTT base topic (required)";else->""}
            val target=controls.filterIsInstance<EditText>().firstOrNull{it.contentDescription==label}
            if(target!=null){target.error=issue.message;if(first==null)first=target}
            else add(NativeUi.status(activity,issue.message).apply{setTextColor(activity.getColor(R.color.ui_error))})
        }
        first?.let{it.requestFocus();it.post{it.requestRectangleOnScreen(android.graphics.Rect(0,0,it.width,it.height),true)}}
    }
    private fun edit() {
        val original=current();val d=draft ?: original ?: return
        var submit:Button?=null
        fun label(){val changes=runCatching{connectionTransportChanged(original,draft!!)}.getOrDefault(true);submit?.text=if(online()&&changes)"Save and reconnect" else "Save connection";submit?.isEnabled=!busy&&draft!!.networks.isNotEmpty()&&(!network.connectionInUse(original)||!changes)}
        availabilityRefresh={label()}
        field("Connection name (required)",d.label){draft=draft!!.copy(label=it);label()}
        field("Broker address (required)",d.serverUri,NativeUi.Input.ADDRESS){draft=draft!!.copy(serverUri=it);label()}.tag="network.address"
        text("Use the MQTT broker address, rather than the Zigbee2MQTT web address.")
        val consent=CheckBox(activity).apply{text="Allow an unencrypted connection on my local network";isChecked=d.allowInsecureLocal;minHeight=dp(48);setTextColor(activity.getColor(R.color.ui_text));setOnCheckedChangeListener{_,v->dirty=true;draft=draft!!.copy(allowInsecureLocal=v);label()}};add(consent);controls.add(consent)
        row("Zigbee topics (${d.networks.size})","Configure one to three named topics."){go("topics")}
        val changedEndpoint=original!=null && runCatching{normalizeBrokerUri(d.serverUri)!=original.serverUri}.getOrDefault(false)
        // The address field can change after this render. Check again when Save is pressed.
        if(changedEndpoint)text("The new broker will not receive the old credentials.")
        submit=formActions("Save connection",d.networks.isNotEmpty(),{discard{draft=null;go(if(original==null)"list" else "detail")}}) {
            val candidate=draft!!.copy(label=draft!!.label.trim(),serverUri=draft!!.serverUri.trim())
            val issues=candidate.validationIssues()
            if(issues.isNotEmpty()){showIssues(issues);return@formActions}
            try{BrokerProfileStore.replaceInCatalog(network.loadProfiles(),if(original!=null&&original.serverUri!=candidate.validated().serverUri)candidate.copy(networks=candidate.networks.map{it.copy(id=id())})else candidate)}catch(_:Exception){failure="Choose a different connection and topic name.";draw();return@formActions}
            if(original!=null && original.serverUri!=candidate.validated().serverUri){
                AlertDialog.Builder(activity).setTitle("Credentials for the new broker").setMessage("Save this address without the previous credentials, then use Change credentials before connecting. Saved devices keep their previous topic association.").setNegativeButton("Keep editing",null).setPositiveButton("Save without credentials"){_,_->
                    val rebound=candidate.copy(networks=candidate.networks.map{it.copy(id=id())})
                    operate { network.saveProfile(rebound,clearCredentials=true,disconnectAfterSave=online());profileId=rebound.id;draft=null;dirty=false;screen="detail" }
                }.show()
            } else operate {network.saveProfile(candidate,reconnect=online()&&connectionTransportChanged(original,candidate));profileId=candidate.id;draft=null;dirty=false;screen="detail"}
        }
        label()
    }
    private fun topics() {
        val p=draft?:current() ?: return
        p.networks.forEach{n->editableRow(n.label,n.baseTopic,"topic:${n.id}","topic",!network.connectionInUse(current())&&(draft!=null||p.networks.size>1),
            open={topicId=n.id;go("topic")},edit={topicId=n.id;go("topic")},remove={
                val next=p.copy(networks=p.networks.filterNot{it.id==n.id})
                if(draft!=null){draft=next;dirty=true;go("topics")}else operate{network.saveProfile(next,reconnect=online());dirty=false;screen="topics"}
            })}
        if(p.networks.isEmpty()){text("No topics yet");action("Add topic"){add()}}
        if(p.networks.size==3)text("Up to 3 topics per connection.")
    }
    private fun topic() {
        val p=draft?:current() ?: return
        val old=p.networks.firstOrNull{it.id==topicId}
        var name=topicName;var base=topicBase
        var submit:Button?=null
        fun update(){val transport=old==null || old.baseTopic!=base.trim();submit?.text=if(online()&&draft==null&&transport)"Save and reconnect" else "Save topic";submit?.isEnabled=!busy&&(!network.connectionInUse(current())||!transport)}
        availabilityRefresh={update()}
        field("Topic name (required)",name){name=it;topicName=it;update()}
        field("MQTT base topic (required)",base,NativeUi.Input.IDENTIFIER){base=it;topicBase=it;update()}
        text("Use the base topic from Zigbee2MQTT.")
        val held=network.connectionInUse(current())
        submit=formActions("Save topic",true,{discard{go("topics")}}){
            val baseChanged=old!=null && old.baseTopic!=base.trim()
            val updated=ZigbeeNetwork(if(baseChanged)id() else old?.id?:id(),name.trim(),base.trim())
            val candidate=p.copy(networks=if(old==null)p.networks+updated else p.networks.map{if(it.id==old.id)updated else it})
            val issues=candidate.validationIssues().filterNot{it.field==BrokerValidationField.BROKER || it.field==BrokerValidationField.CONSENT}
            if(issues.isNotEmpty()){showIssues(issues);return@formActions}
            fun save(){if(draft!=null){draft=candidate;dirty=true;go("topics")}else operate{network.saveProfile(candidate,reconnect=online()&&connectionTransportChanged(p,candidate));dirty=false;screen="topics"}}
            if(baseChanged)AlertDialog.Builder(activity).setTitle("Change MQTT base topic?").setMessage("Saved devices keep their previous source. Import devices from the new topic separately.").setNegativeButton("Keep editing",null).setPositiveButton(if(online())"Save and reconnect" else "Save topic"){_,_->save()}.show() else save()
        }
        update()
    }
    private fun credentials() {
        val p=current() ?: return
        val unavailable=network.hasCredentials(p)&&!network.credentialsAvailable(p)
        text(if(unavailable)"Saved credentials unavailable. Enter new credentials, or use no credentials." else "Existing credentials stay saved until you save.")
        var changeUsername=!network.hasCredentials(p)||unavailable
        val usernameSummary=column();text("Keep saved username",container=usernameSummary)
        val user=NativeUi.field(activity,"Username (optional)",input=NativeUi.Input.USERNAME).apply{isSaveEnabled=false;visibility=if(changeUsername)View.VISIBLE else View.GONE}
        val change=action("Change username",container=usernameSummary){changeUsername=true;user.visibility=View.VISIBLE;dirty=true;usernameSummary.visibility=View.GONE}
        if(changeUsername)usernameSummary.visibility=View.GONE
        add(usernameSummary);val userLabel=text("Username (optional)",secondary=false).apply{visibility=user.visibility};add(user)
        val userHelp=text("Leave blank to remove the username.").apply{visibility=user.visibility}
        text("New password",secondary=false)
        val pass=NativeUi.field(activity,"New password",input=NativeUi.Input.PASSWORD).apply{isSaveEnabled=false};add(pass)
        text(if(unavailable)"Enter a new password to replace unavailable credentials." else if(network.hasCredentials(p))"Leave blank to keep the saved password." else "Password is optional when no credentials are saved.")
        val options=column()
        val clear=CheckBox(activity).apply{text="Use no credentials";minHeight=dp(48);setTextColor(activity.getColor(R.color.ui_text))};add(clear,options)
        val empty=CheckBox(activity).apply{text="Use an empty password";minHeight=dp(48);setTextColor(activity.getColor(R.color.ui_text))};add(empty,options)
        add(NativeUi.disclosure(activity,"Sign-in options","Hide sign-in options",options).apply{gravity=Gravity.CENTER},gap=24);add(options,gap=12)
        val held=network.connectionInUse(p)
        if(held)text("Wait for the current update to finish.")
        val save=formActions(if(online())"Save and reconnect" else "Save credentials",false,{discard{dirty=false;go("detail")}}){
            val username=user.text.toString().ifEmpty{null};val password=if(empty.isChecked)charArrayOf() else pass.text.toString().takeIf{it.isNotEmpty()}?.toCharArray()
            val anonymous=clear.isChecked;val replaceUsername=changeUsername;user.text.clear();pass.text.clear()
            operate{try{network.editCredentials(p.id,replaceUsername,username,password,anonymous,online());dirty=false;screen="detail"}finally{password?.fill('\u0000')}}
        }
        fun update(){dirty=changeUsername||pass.text.isNotEmpty()||clear.isChecked||empty.isChecked;save.text=if(online())"Save and reconnect" else "Save credentials";save.isEnabled=dirty&&(!unavailable||pass.text.isNotEmpty()||clear.isChecked||empty.isChecked)&&!network.connectionInUse(p)&&!busy;user.isEnabled=!clear.isChecked;empty.isEnabled=!clear.isChecked;pass.isEnabled=!clear.isChecked&&!empty.isChecked}
        val watcher=object:TextWatcher{override fun beforeTextChanged(s:CharSequence?,start:Int,count:Int,after:Int){};override fun afterTextChanged(s:Editable?){update()};override fun onTextChanged(s:CharSequence?,start:Int,before:Int,count:Int){}}
        user.addTextChangedListener(watcher);pass.addTextChangedListener(watcher)
        change.setOnClickListener{changeUsername=true;user.visibility=View.VISIBLE;userLabel.visibility=View.VISIBLE;userHelp.visibility=View.VISIBLE;usernameSummary.visibility=View.GONE;update();user.requestFocus()}
        clear.setOnCheckedChangeListener{_,_->update()};empty.setOnCheckedChangeListener{_,_->update()}
        secretFields.addAll(listOf(user,pass));controls.addAll(listOf(user,pass,clear,empty));availabilityRefresh={update()};update()
    }
    private fun operate(connecting:Boolean=false,work:suspend()->Unit) {
        if(busy)return;busy=true;failure=null;controls.forEach{it.isEnabled=false}
        statusView?.text=if(connecting)"Connecting…" else "Saving…"
        if(connecting){headerState("Connecting",activity.getColor(R.color.ui_available));dock(NativeUi.button(activity,"Cancel connection"){task?.cancel()})}
        task=scope.launch {
            var connected=false
            try{withContext(Dispatchers.IO){work()};connected=connecting&&network.state.value.connected}
            catch(cancelled:CancellationException){failure="Connection stopped.";throw cancelled}
            catch(e:SavedConnectionReconnectException){profileId?.let{connectionErrors[it]="Reconnect failed"};dirty=false;draft=null;screen="detail";failure="Changes saved · Not connected. "+presentMqttFailure(e.cause?:e).let{"${it.message} ${it.nextAction}"}}
            catch(e:Exception){if(connecting)profileId?.let{connectionErrors[it]="Connection failed"};failure=if(connecting)presentMqttFailure(e).let{"${it.message} ${it.nextAction}"} else "Could not apply changes. Check the saved connection and try again."}
            finally{busy=false;draw();if(connected)onConnected()}
        }
    }
    fun updateAvailability(){if(!busy){if(screen in listOf("list","detail","topics"))draw() else availabilityRefresh?.invoke()}}
    fun updateState(){if(!busy)updateAvailability();statusView?.text=if(busy)"Connecting…" else if(online())"Connected" else "Not connected"}
    private fun discard(run:()->Unit){if(dirty)AlertDialog.Builder(activity).setTitle("Discard changes?").setNegativeButton("Keep editing",null).setPositiveButton("Discard"){_,_->dirty=false;run()}.show() else run()}
    fun confirmLeave(run:()->Unit):Boolean {if(!dirty)return false;discard{draft=null;screen="list";run()};return true}
    fun back():Boolean {
        if(busy)return true
        if(screen=="topics"&&returnFromTopics){returnFromTopics=false;screen="list";return false}
        when(screen){"list"->return false;"topics"->{go(if(draft!=null)"edit" else "detail")};"topic"->{discard{go("topics")}};"edit"->{discard{draft=null;go(if(current()==null)"list" else "detail")}};"credentials"->{discard{go("detail")}};else->{draft=null;go("list")}}
        return true
    }
    fun saveState()=Bundle().apply{putString("screen",if(screen=="credentials")"detail" else screen);putString("profile",profileId);putBoolean("returnFromTopics",returnFromTopics);putString("topic",topicId);putString("topicName",topicName);putString("topicBase",topicBase);draft?.let{p->putString("draftId",p.id);putString("name",p.label);putString("address",safeNetworkAddressDraft(p.serverUri));putBoolean("consent",p.allowInsecureLocal);putStringArrayList("topicIds",ArrayList(p.networks.map{it.id}));putStringArrayList("topicNames",ArrayList(p.networks.map{it.label}));putStringArrayList("topicBases",ArrayList(p.networks.map{it.baseTopic}))}}
    fun restoreState(saved:Bundle){returnFromTopics=saved.getBoolean("returnFromTopics");profileId=saved.getString("profile");topicId=saved.getString("topic");topicName=saved.getString("topicName","");topicBase=saved.getString("topicBase","");screen=saved.getString("screen","list");saved.getString("draftId")?.let{id->val ids=saved.getStringArrayList("topicIds").orEmpty();val names=saved.getStringArrayList("topicNames").orEmpty();val bases=saved.getStringArrayList("topicBases").orEmpty();draft=BrokerProfile(id,saved.getString("address", ""),ids.take(3).mapIndexedNotNull{i,n->if(i<names.size&&i<bases.size)ZigbeeNetwork(n,names[i],bases[i])else null},saved.getBoolean("consent"),saved.getString("name",""))};dirty=draft!=null}
    fun detach(){val retained=dirty;secretFields.forEach{it.text.clear()};secretFields.clear();dirty=retained;parent=null}
    fun close(){detach()}
}
