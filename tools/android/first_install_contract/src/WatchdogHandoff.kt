package org.openvimar.installer

/** Not a user flag: only a verified signed descriptor can construct this
 * authority. It is specific to its exact release/template family and live UID
 * plus non-reconnectable lease generation. It is not execution approval. */
class WatchdogHandoffAuthority private constructor(val policy:String,val releaseSha256:String,val familySha256:String,
    private val target:TargetIdentity,private val generation:Long) {
    fun requireTarget(target:TargetIdentity,generation:Long){require(this.target==target&&this.generation==generation){"Watchdog handoff authority belongs to another target/lease"}}
    fun requireBinding(binding:InstallBinding,generation:Long){requireTarget(binding.target,generation)
        require(binding.releaseSha256==releaseSha256&&binding.familySha256==familySha256){"Watchdog handoff authority belongs to another signed release/loader"}}
    internal companion object {
        const val POLICY="paused-reset-before-main-v1"
        fun fromSignedDescriptor(policy:String,release:String,family:String,target:TargetIdentity,generation:Long):WatchdogHandoffAuthority {
            require(policy==POLICY&&generation>0&&target.part==0x52840L&&target.variant in 1..0xfffffffeL&&target.uid0 in 0..0xffffffffL&&target.uid1 in 0..0xffffffffL&&
                target.flashSize==0x100000&&target.pageSize==4096&&target.ramSize==0x40000&&target.uicrSize==4096)
            return WatchdogHandoffAuthority(policy,release,family,target,generation)
        }
    }
}

/** Live observation or producer-reported backup metadata, never permission. */
data class ObservedWatchdogProfile(val runStatus:Long,val config:Long,val crv:Long,val rren:Long) {
    init{require(runStatus in 0..1&&config in 0..0xffffffffL&&config and 9L.inv()==0L&&crv in 0..0xffffffffL&&rren in 0..255)}
    val active get()=runStatus==1L
    val pausesOnHalt get()=config and 8L==0L
    fun requireAcquisitionShape(){if(active)require(pausesOnHalt&&rren!=0L&&crv+1<=60L*32768){"Active watchdog is not a bounded paused profile"}}
    fun requireSupported(authority:WatchdogHandoffAuthority?){
        if(active){requireNotNull(authority){"Active watchdog requires a signed paused-reset-before-main-v1 loader"};requireAcquisitionShape()}
    }
    fun asContract():Map<String,Any?> = mapOf("runStatus" to runStatus,"config" to config,"crv" to crv,"rren" to rren)
    companion object {
        fun fromContract(value:Any?):ObservedWatchdogProfile {
            val m=keys(value,setOf("runStatus","config","crv","rren"))
            require(m.values.all{it is Long})
            return ObservedWatchdogProfile(m.getValue("runStatus") as Long,m.getValue("config") as Long,m.getValue("crv") as Long,m.getValue("rren") as Long).also{it.requireAcquisitionShape()}
        }
    }
}
