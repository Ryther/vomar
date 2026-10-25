package org.openvimar.updater

internal object DkSwdBackup {
    const val DEADLINE_MILLIS=20L*60*1000
    fun open(channel: DkBulkChannel,cancelled: () -> Boolean = {false},now: () -> Long = System::nanoTime): DkBackupSource {
        val session=DkSwdJlinkSession(channel,now,DEADLINE_MILLIS,cancelled)
        session.initialize {_,_->}
        session.identify()
        return session.openBackupSource()
    }
}
