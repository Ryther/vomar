package org.openvimar.updater.core

import java.security.PublicKey
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.*
import org.openvimar.installer.CandidateRelease

/** A review is an ephemeral one-use grant, never a restorable executable package. */
class BleTrialReview internal constructor(internal val owner:BleTrialCandidate,
    internal val snapshot:TrialSnapshot,val address:String,val digest:String,
    val version:String,val currentVersion:String?,val legacy:Boolean,val resumable:Boolean,
    val resetRetryRequired:Boolean,val identitySummary:String,val expectedUid:List<String>?=null):AutoCloseable {
    private val available=AtomicBoolean(true)
    internal fun consume(candidate:BleTrialCandidate){
        require(candidate===owner){"Review belongs to another candidate"}
        check(available.compareAndSet(true,false)){"Review already used or revoked; inspect this dimmer again"}
    }
    override fun close(){available.set(false)}
}
internal data class TrialSnapshot(val identity:RuntimeIdentity?,val images:RemoteImages,
    val bootstrap:BootstrapCheckpoint?,val checkpoint:Checkpoint?)

/** Deliberately exposes no ValidatedCommonPackage, image bytes or fleet reference. */
class BleTrialCandidate private constructor(private val common:ValidatedCommonPackage) {
    val digest get()=common.bundleDigest
    val version get()=common.manifest.main.version
    val recoveryVersion get()=requireNotNull(common.manifest.recovery).version
    val familySha256 get()=common.manifest.loaderContracts.single{it.kind==LoaderContract.COMMON}.sha256
    companion object {
        fun inspect(bytes:ByteArray,key:PublicKey,appVersion:String):BleTrialCandidate=inspectMode(bytes,key,appVersion,false)
        fun inspectLocal(bytes:ByteArray,key:PublicKey,appVersion:String):BleTrialCandidate=inspectMode(bytes,key,appVersion,true)
        private fun inspectMode(bytes:ByteArray,key:PublicKey,appVersion:String,local:Boolean):BleTrialCandidate {
            require(bytes.size in 1..PackageReader.MAX_ZIP){"Candidate exceeds supported ZIP size"}
            val frozen=bytes.copyOf()
            val inspected=if(local)CandidateRelease.inspectLocal(frozen,key,appVersion) else CandidateRelease.inspect(frozen,key,appVersion)
            val limits=mapOf("manifest.json" to 65536,"manifest.sig" to 80,"first-install.json" to 16384,"first-install.sig" to 80,
                "loader.bin" to 0xc000,"main.signed.bin" to 0xa2000,"recovery.signed.bin" to 0x34000,
                "migration.signed.bin" to 0xa2000,"stock-restore.signed.bin" to 0x3f000,"stock-bootstrap.signed.bin" to 0xa2000,
                "main.ota" to ZigbeeCarrierValidator.MAX_CARRIER,"qualification.json" to 65536)
            val entries=org.openvimar.installer.StrictZip.read(frozen,limits,PackageReader.MAX_ZIP,
                if(local)setOf("manifest.json","main.signed.bin","recovery.signed.bin") else setOf("manifest.json","manifest.sig","main.signed.bin","recovery.signed.bin","qualification.json"),PackageReader.MAX_ZIP)
            require(sha256(frozen)==inspected.releaseSha256){"Inspected candidate bytes changed"}
            // CandidateRelease authenticates the ORIGINAL manifest, components and
            // all pending flags first. Omit only its purpose field when mapping
            // the already authenticated metadata into the shared engine model.
            val tree=Json.parseToJsonElement(entries.getValue("manifest.json").toString(Charsets.UTF_8)).jsonObject
            require(tree["purpose"]==null&&local||tree["purpose"]==JsonPrimitive("qualification-candidate"))
            val metadata=Json.decodeFromJsonElement<CommonManifest>(JsonObject(tree.filterKeys{it!="purpose"}))
            return BleTrialCandidate(ValidatedCommonPackage(metadata,entries.getValue("main.signed.bin").copyOf(),inspected.releaseSha256,
                entries["recovery.signed.bin"]?.copyOf(),entries["migration.signed.bin"]?.copyOf(),entries["main.ota"]?.copyOf()))
        }
    }
    private fun frozen(identity:RuntimeIdentity)=identity.copy(uid=java.util.Collections.unmodifiableList(identity.uid.toList()))
    private fun frozen(c:Checkpoint)=c.copy(targetUid=c.targetUid?.let{java.util.Collections.unmodifiableList(it.toList())},runtimeIdentity=c.runtimeIdentity?.let(::frozen))
    private fun frozen(c:BootstrapCheckpoint)=c.copy(observedUid=c.observedUid?.let{java.util.Collections.unmodifiableList(it.toList())},observedIdentity=c.observedIdentity?.let(::frozen))
    private suspend fun observe(address:String,transport:BleTransport,bootstrap:BootstrapStore,store:SessionStore):TrialSnapshot {
        require(Regex("([0-9A-F]{2}:){5}[0-9A-F]{2}").matches(address)){"Choose a valid Bluetooth target"}
        try {
            transport.connect(address)
            val identity=try{frozen(RuntimeIdentityLookup.forRelease(transport,common.manifest))}catch(_:IdentityCommandUnavailable){null}
            val images=transport.images()
            val bridge=bootstrap.load(digest,address)?.let(::frozen)
            require(bridge==null||CommonBootstrapCoordinator.matches(common,address,bridge)){"Recovery preparation checkpoint changed or is incompatible"}
            val checkpoint=if(identity==null){
                require(CommonBootstrapCoordinator.eligible(common,address,images,bridge)){"Legacy recovery or source image is not authorized for this candidate"}
                null
            }else{
                require(bridge?.observedUid==null||bridge.observedUid==identity.uid){"Previously adopted UID changed"}
                require(bridge?.observedIdentity==null||bridge.observedIdentity==identity){"Previously adopted loader or anchor changed"}
                val bound=common.bind(identity,address)
                val saved=store.load(digest,address,bound.targetUid)?.let(::frozen)
                require(saved==null||UpdatePlanner.matches(bound,saved)){"Saved progress is incompatible with this dimmer and candidate"}
                require(UpdatePlanner.next(bound,images,saved)!=Decision.Reject){"Installed images or checkpoint do not match this candidate"}
                saved
            }
            require(transport.images()==images){"Images changed while inspecting the dimmer"}
            return TrialSnapshot(identity,images,bridge,checkpoint)
        }finally{withContext(NonCancellable){transport.close()}}
    }
    suspend fun review(address:String,transport:BleTransport,bootstrap:BootstrapStore,store:SessionStore,expectedUid:List<String>?=null):BleTrialReview {
        val state=observe(address,transport,bootstrap,store)
        if(expectedUid!=null){require(expectedUid.size==2);state.identity?.let{require(it.uid==expectedUid){"The Bluetooth UID does not match the selected device"}}}
        val retry=(state.identity==null&&state.bootstrap?.phase==BootstrapPhase.RESET_INTENT)||
            state.checkpoint?.let{it.phase==Phase.MIGRATION_RESET_INTENT||it.phase in setOf(Phase.FINAL_RESET_INTENT,Phase.AWAIT_OPERATOR)&&!it.resetAcknowledged}==true
        return BleTrialReview(this,state,address,digest,version,state.images.primary?.version,state.identity==null,
            state.bootstrap!=null||state.checkpoint!=null,retry,
            state.identity?.let{"UID ${it.uid.joinToString(":")} · authenticated ${it.typedLoader?.kind ?: LoaderContract.LEGACY}"}
                ?: "Legacy recovery: exact images checked; UID will be verified after preparation",expectedUid?.let{java.util.Collections.unmodifiableList(it.toList())})
    }
    suspend fun run(review:BleTrialReview,factory:(String)->BleTransport,bootstrap:BootstrapStore,
        store:SessionStore,allowResetRetry:Boolean=false,onEvent:suspend(UpdateEvent)->Unit) {
        review.consume(this)
        require(!allowResetRetry||review.resetRetryRequired){"Reset retry requires the reviewed uncertain stage"}
        val actual=observe(review.address,factory(review.address),bootstrap,store)
        require(actual==review.snapshot){"Dimmer identity, images or saved progress changed; inspect and review again"}
        actual.identity?.let{if(review.expectedUid!=null)require(it.uid==review.expectedUid){"Selected device UID changed"}}
        var identity=actual.identity
        if(identity==null){
            CommonBootstrapCoordinator().run(common,review.address,factory(review.address),bootstrap,
                onBound={identity=frozen(it)},allowResetRetry=allowResetRetry,validateIdentity={if(review.expectedUid!=null)require(it.uid==review.expectedUid){"Prepared device UID does not match the selected device"}},onEvent=onEvent)
            if(identity==null)return
        }
        val bound=common.bind(requireNotNull(identity),review.address)
        // Bootstrap confirmation can never authorize a later final reset retry.
        UpdateCoordinator().run(bound,factory(review.address),store,
            allowResetRetry=allowResetRetry&&actual.identity!=null,onEvent=onEvent)
    }
}
