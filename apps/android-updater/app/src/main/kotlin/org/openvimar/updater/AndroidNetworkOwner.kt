package org.openvimar.updater

import android.content.Context
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Shared failure exit for the process-local connection attempt. */
internal suspend fun finishFailedMqttConnection(error:Exception,disconnect:suspend ()->Unit,publishState:(NetworkBackendState)->Unit):Nothing {
    withContext(NonCancellable) {
        try { disconnect() }
        catch(cleanup:Exception) { if(cleanup!==error)error.addSuppressed(cleanup) }
        val status=if(error is CancellationException)"Connection stopped." else {
            val failure=presentMqttFailure(error)
            "${failure.message} ${failure.nextAction}"
        }
        publishState(NetworkBackendState(status=status,connectionError=error !is CancellationException))
    }
    throw error
}

internal class SavedConnectionReconnectException(cause:Throwable):Exception("Changes saved; reconnect failed",cause)

/** Restore only the explicitly activated broker; firmware operations retain their own admission. */
internal class AndroidNetworkOwner(
    context:Context,
    private val scope:CoroutineScope=CoroutineScope(SupervisorJob()+Dispatchers.IO),
    private val connection:()->MqttConnection={PahoMqttConnection()},
    private val connectTimeoutMs:Long=30000
) {
    private val application=context.applicationContext
    private val settings=BrokerProfileStore(application)
    private val secrets=BrokerSecretStore(application)
    private val lifecycle=Mutex()
    private val changes=Mutex()
    private val mutable=MutableStateFlow(NetworkBackendState())
    val state:StateFlow<NetworkBackendState> = mutable.asStateFlow()
    @Volatile private var active:ZigbeeBridge?=null
    private var forwarding:Job?=null
    private var lastFailure:Exception?=null
    @Volatile var activeProfileId:String?=runCatching { settings.activatedId() }.getOrNull(); private set
    private val reconnect=MqttReconnectLoop(scope,state,{
        lifecycle.withLock {
            val saved=requireNotNull(activeProfileId?.let(::profile)) { "Connection is no longer saved" }
            disconnectLocked()
            connectLocked(saved)
        }
    },{ delayMs->mutable.update { it.copy(reconnecting=true,status="Reconnecting in ${delayMs/1000}s") } })
    private val fleetExecutor=ZigbeeFleetExecutor(::bridge,{ ref -> AndroidFleetReleases(application).load(ref) })
    val executor=FleetJobExecutor { context,emit -> lifecycle.withLock { fleetExecutor.execute(context,emit) } }
    init { require(connectTimeoutMs>0);if(activeProfileId!=null)reconnect.start(connectImmediately=true) }
    fun loadProfiles():List<BrokerProfile> = settings.loadAll()
    fun loadProfile():BrokerProfile?=loadProfiles().firstOrNull { it.id==activeProfileId } ?: settings.load()
    fun profile(id:String):BrokerProfile?=loadProfiles().firstOrNull { it.id==id }
    fun hasCredentials(profile:BrokerProfile?=loadProfile()):Boolean=profile?.let(secrets::has) ?: false
    fun credentialsAvailable(profile:BrokerProfile):Boolean=try{secrets.load(profile).use{it!=null}}catch(_:Exception){false}
    fun connectionInUse(profile:BrokerProfile?):Boolean=connectionHasPendingUpdates(profile,AndroidFleetOwner.get(application).queue.groups.value)
    private fun ensureIdle(profile:BrokerProfile?) { check(!connectionInUse(profile)) { "Wait for the current update to finish" } }
    private suspend fun <T> changeConnection(work:suspend ()->T):T=changes.withLock {
        try {
            // A stalled connect/subscription holds lifecycle; cancel it before waiting for that lock.
            reconnect.stopAndJoin()
            lifecycle.withLock { work() }
        } finally {
            if(activeProfileId!=null)reconnect.start(
                connectImmediately=!state.value.connected && !state.value.connectionError,
                initialFailure=lastFailure)
        }
    }
    suspend fun saveProfile(profile:BrokerProfile,credentials:BrokerCredentials?=null,clearCredentials:Boolean=false,reconnect:Boolean=false,disconnectAfterSave:Boolean=false)=changeConnection {
        saveLocked(profile,credentials,clearCredentials,reconnect,disconnectAfterSave)
    }
    private suspend fun saveLocked(profile:BrokerProfile,credentials:BrokerCredentials?,clearCredentials:Boolean,reconnect:Boolean,disconnectAfterSave:Boolean=false) {
        val canonical=profile.validated();val previous=profile(canonical.id)
        BrokerProfileStore.replaceInCatalog(loadProfiles(),canonical)
        val changed=connectionTransportChanged(previous,canonical)
        val endpointChanged=previous!=null && previous.validated().serverUri!=canonical.serverUri
        require(!endpointChanged || credentials!=null || clearCredentials) { "Enter credentials for the new broker, or choose Use no credentials" }
        if(changed || credentials!=null || clearCredentials)ensureIdle(previous)
        val isActive=activeProfileId==canonical.id
        check(!isActive || !changed && credentials==null && !clearCredentials || reconnect || disconnectAfterSave) { "Save and reconnect to apply these changes" }
        // Encrypt before the single metadata+secret commit. Failed encryption cannot mutate the old pair.
        val encrypted=credentials?.let { secrets.encrypt(canonical,it) }
        settings.save(canonical,encrypted,credentials!=null || clearCredentials)
        if(isActive && disconnectAfterSave)deactivateLocked()
        else if(isActive && reconnect){try{activateLocked(canonical)}catch(cancelled:CancellationException){throw cancelled}catch(e:Exception){throw SavedConnectionReconnectException(e)}}
    }
    suspend fun editCredentials(id:String,changeUsername:Boolean,username:String?,newPassword:CharArray?,clear:Boolean,reconnect:Boolean)=changeConnection {
        val profile=requireNotNull(profile(id)) { "Connection is no longer saved" }
        if(clear)saveLocked(profile,null,true,reconnect)
        else {
            (if(changeUsername && newPassword!=null)null else secrets.load(profile)).use { old ->
                val next=BrokerCredentials(if(changeUsername)username else old?.username,(newPassword ?: old?.password ?: charArrayOf()).copyOf())
                next.use { saveLocked(profile,it,false,reconnect) }
            }
        }
    }
    suspend fun removeProfile(id:String)=changeConnection {
        val profile=profile(id) ?: return@changeConnection;ensureIdle(profile)
        settings.remove(id)
        if(activeProfileId==id)deactivateLocked()
    }
    suspend fun clearCredentials() { loadProfile()?.let { editCredentials(it.id,false,null,null,true,activeProfileId==it.id) } }
    suspend fun connect(profile:BrokerProfile=requireNotNull(loadProfile()) { "Configure a broker first" })=changeConnection {
        ensureIdle(loadProfiles().firstOrNull { it.id==activeProfileId });val saved=requireNotNull(this.profile(profile.id)) { "Connection is no longer saved" };require(saved==profile.validated()) { "Connection settings changed; select it again" };activateLocked(saved)
    }
    private suspend fun activateLocked(profile:BrokerProfile) {
        settings.activate(profile.id)
        activeProfileId=profile.id
        reconnect.stop()
        try { disconnectLocked();connectLocked(profile) }
        catch(cancelled:CancellationException) {
            withContext(NonCancellable) { deactivateLocked() }
            throw cancelled
        }
    }
    private suspend fun connectLocked(profile:BrokerProfile) {
        activeProfileId=profile.id
        mutable.value=NetworkBackendState(status="Connecting",reconnecting=true)
        val candidate=ZigbeeBridge(connection(),scope)
        try {
            val connected=withTimeoutOrNull(connectTimeoutMs) {
                secrets.load(profile).use { credentials -> candidate.connect(profile,credentials) }
                true
            }
            if(connected!=true)throw java.net.SocketTimeoutException()
            lastFailure=null
            active=candidate
            forwarding=scope.launch(start=CoroutineStart.UNDISPATCHED) { candidate.state.collect { mutable.value=it } }
        } catch(e:Exception) {
            if(e !is CancellationException)lastFailure=e
            finishFailedMqttConnection(e,{ candidate.disconnect() },{ mutable.value=it })
        }
    }
    suspend fun disconnect()=changeConnection { ensureIdle(loadProfiles().firstOrNull { it.id==activeProfileId });deactivateLocked() }
    private suspend fun deactivateLocked() {
        settings.activate(null)
        activeProfileId=null
        lastFailure=null
        reconnect.stop()
        disconnectLocked()
    }
    private suspend fun disconnectLocked() {
        forwarding?.cancelAndJoin();forwarding=null
        val previous=active;active=null
        previous?.disconnect()
        mutable.value=NetworkBackendState(status="Not connected")
    }
    suspend fun refreshInventory()=lifecycle.withLock { bridge().refreshInventory() }
    suspend fun check(networkId:String,ieee:String):OtaAvailability {
        val result=bridge().check(networkId,ieee)
        val selected=AndroidFleetReleases(application).selected()
        if(selected?.zigbeeOta!=null)refreshCompatibility(networkId,ieee,selected)
        return result
    }
    suspend fun refreshCompatibility(networkId:String,ieee:String,release:FleetReleaseRef) {
        val pkg=AndroidFleetReleases(application).load(release)
        require(pkg.manifest.zigbeeOta!=null) { "This release has no Zigbee carrier; use Bluetooth" }
        bridge().verifyRecoveryPair(networkId,ieee,pkg.manifest.targetRecoverySignedHash)
    }
    suspend fun prepareBluetooth(networkId:String,ieee:String):BluetoothPreparation=bridge().prepareBluetooth(networkId,ieee)
    suspend fun reconcile(context:FleetExecutionContext):FleetExecutionResult=lifecycle.withLock { fleetExecutor.reconcile(context) }
    private fun bridge()=checkNotNull(active) { "Connect to the selected broker first" }
    companion object {
        @Volatile private var instance:AndroidNetworkOwner?=null
        fun get(context:Context):AndroidNetworkOwner=instance ?: synchronized(this) { instance ?: AndroidNetworkOwner(context).also { instance=it } }
    }
}
