package org.openvimar.updater

/** One process-wide owner of J-Link/AP state. Every USB caller must hold this
 * token for its entire physical operation, including suspended export/review.
 * Close the USB connection and drain its worker before releasing this token.
 * A token never transfers to another connection or survives process death. */
internal object DkUsbOperationGate {
    private var current:Lease?=null
    private var nextGeneration=0L
    @Synchronized fun acquire(owner:String):Lease? {
        require(owner.isNotBlank()&&owner.length<=128)
        if(current!=null)return null
        check(nextGeneration<Long.MAX_VALUE)
        return Lease(owner,++nextGeneration).also{current=it}
    }
    class Lease internal constructor(val owner:String,val generation:Long):AutoCloseable {
        fun checkCurrent()=synchronized(DkUsbOperationGate){check(current===this){"USB operation lease is no longer current"}}
        override fun close() {synchronized(DkUsbOperationGate){if(current===this)current=null}}
    }
}

/** Presence inspection is bounded on an already-open, non-reconnectable USB
 * handle. Token/closed checks and bulk-transfer failures remain per I/O. */
internal class DkUsbPresenceGuard(private val now:()->Long=System::nanoTime,private val verify:()->Unit){
    private var checkedAt:Long?=null;private var failed=false
    fun check(){
        check(!failed){"USB presence was lost; reconnect is prohibited"}
        val time=now();val previous=checkedAt
        if(previous==null||time-previous>=250_000_000L||time-previous<0){
            try{verify();checkedAt=time}catch(error:Exception){failed=true;throw error}
        }
    }
}
