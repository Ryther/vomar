package org.openvimar.updater.installer

import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean

/** Process-only admission. Construction never restores execution from disk. */
internal class FirstInstallHostPolicy {
    private var active:Ticket?=null;private var destroyed=false
    class Ticket internal constructor(val requestId:String) {
        private val stopped=AtomicBoolean(false)
        val cancelled get()=stopped.get()
        fun checkActive(){check(!cancelled){"First-install request cancelled"}}
        internal fun cancel(){stopped.set(true)}
    }
    @Synchronized fun admit(requestId:String):Ticket? {
        require(UUID.fromString(requestId).toString()==requestId)
        if(destroyed||active!=null)return null
        return Ticket(requestId).also{active=it}
    }
    @Synchronized fun current()=active
    @Synchronized fun cancel(){active?.cancel()}
    @Synchronized fun finished(ticket:Ticket){if(active===ticket)active=null}
    @Synchronized fun destroy(){destroyed=true;active?.cancel()}
}
