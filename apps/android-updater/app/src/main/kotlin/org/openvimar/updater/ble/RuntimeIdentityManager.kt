package org.openvimar.updater.ble

import no.nordicsemi.android.mcumgr.*
import no.nordicsemi.android.mcumgr.response.McuMgrResponse
import org.openvimar.updater.core.RuntimeIdentity
import org.openvimar.updater.core.LoaderContract
import org.openvimar.updater.core.RuntimeIdentityLookup

/** Group0x8040 READ0: supported only by project firmware, over an authenticated bond. */
internal class RuntimeIdentityManager(transport:McuMgrTransport):McuManager(0x8040,transport) {
    fun read(callback:McuMgrCallback<RuntimeIdentityResponse>)=send(OP_READ,0,emptyMap<String,Any>(),RuntimeIdentityResponse::class.java,callback)
    fun readV2(callback:McuMgrCallback<RuntimeIdentityV2Response>)=send(OP_READ,1,emptyMap<String,Any>(),RuntimeIdentityV2Response::class.java,callback)
}
/** Public JVM fields are decoded by the Nordic library's existing CBOR mapper. */
internal open class RuntimeIdentityResponse:McuMgrResponse() {
    protected open val expectedCmd:Int=0
    @JvmField var protocol:Long?=null
    @JvmField var model:String?=null
    @JvmField var layout:Long?=null
    @JvmField var uid:List<Long>?=null
    @JvmField var loader_sha256:ByteArray?=null
    fun validateWire(){StrictSmpCbor.response(this,0x8040,1,expectedCmd)}
    fun rejection():Exception {
        val map=StrictSmpCbor.response(this,0x8040,1,expectedCmd)
        if("rc" in map)require(map["rc"] is Long){"SMP return code must be an unsigned integer"}
        return if(map.keys==setOf("rc")&&map["rc"]==8L)org.openvimar.updater.core.IdentityCommandUnavailable()
            else IllegalStateException("Bluetooth identity request rejected or unsupported response shape")
    }
    open fun identity():RuntimeIdentity {
        val map=StrictSmpCbor.response(this,0x8040,1,expectedCmd)
        require(map.keys==setOf("protocol","model","layout","uid","loader_sha256")&&map["protocol"]==1L&&map["model"]=="VIMAR30805"&&map["layout"]==2L){"Runtime identity protocol/model/layout missing or unsupported"}
        val words=map["uid"] as? List<*>;val loader=map["loader_sha256"] as? ByteArray
        require(words!=null&&words.size==2&&words.all{it is Long&&it in 0L..0xffffffffL}&&loader!=null&&loader.size==32){"Malformed runtime identity response"}
        return RuntimeIdentity(1,"VIMAR30805",2,words.map{"%08x".format(it as Long)},loader.joinToString(""){"%02x".format(it.toInt() and 255)})
    }
}
internal class RuntimeIdentityV2Response:RuntimeIdentityResponse() {
    override val expectedCmd:Int=1
    @JvmField var loader:Map<String,Any>?=null
    override fun identity():RuntimeIdentity {
        val map=StrictSmpCbor.response(this,0x8040,1,expectedCmd)
        require(map.keys==setOf("protocol","model","layout","uid","loader")&&map["protocol"]==2L&&map["model"]=="VIMAR30805"&&map["layout"]==2L){"Malformed typed runtime identity"}
        val uid=map["uid"] as? List<*>;val measured=map["loader"] as? Map<*,*>
        require(uid!=null&&uid.size==2&&uid.all{it is Long&&it in 0L..0xffffffffL}&&measured!=null)
        val kind=measured["kind"] as? String;val digest=measured["digest"] as? ByteArray
        require(kind in setOf(LoaderContract.COMMON,LoaderContract.LEGACY)&&digest?.size==32){"Unknown or malformed loader contract"}
        val anchor=measured["anchor_sha256"] as? ByteArray
        require(if(kind==LoaderContract.COMMON)measured.keys==setOf("kind","digest","anchor_sha256")&&anchor?.size==32 else measured.keys==setOf("kind","digest")){"Typed anchor contract mismatch"}
        fun ByteArray.hex()=joinToString(""){"%02x".format(it.toInt() and 255)}
        return RuntimeIdentity(2,"VIMAR30805",2,uid.map{"%08x".format(it as Long)},"",LoaderContract(requireNotNull(kind),requireNotNull(digest).hex()),anchor?.hex()).also(RuntimeIdentityLookup::validate)
    }
}
