package org.openvimar.updater

object PermissionPolicy {
    fun required(api: Int): List<String> = if (api >= 31) {
        listOf("android.permission.BLUETOOTH_SCAN", "android.permission.BLUETOOTH_CONNECT")
    } else {
        listOf("android.permission.ACCESS_FINE_LOCATION")
    }
}

/** The service calls begin only in response to a visible Start/Resume action. */
class SessionPolicy(private var restored: Boolean = false) {
    var running = false
        private set
    val canReplace: Boolean get() = !running

    fun begin(resume: Boolean, uncertainReset: Boolean, confirmed: Boolean = false): Boolean {
        if (running || (restored && !resume) || (uncertainReset && !confirmed)) return false
        running = true
        restored = true
        return true
    }

    fun finish() { running = false }

    companion object {
        fun operatorOutcome(online: Boolean?): String = when (online) {
            true -> "tornato online"
            false -> "non tornato online"
            null -> "da confermare"
        }
    }
}
