package org.openvimar.updater.installer

import android.content.Context
import org.openvimar.installer.OriginalArchive
import org.openvimar.installer.TargetIdentity
import org.openvimar.installer.ObservedWatchdogProfile
import org.openvimar.updater.*

/** Existing read-only capability supplies the preview. Saved reports and
 * user-entered identity never grant capture authority. */
internal object AndroidInitialInstallIdentity {
    data class Inspection(val target:TargetIdentity,val watchdog:ObservedWatchdogProfile)
    fun inspect(context:Context,deviceName:String,cancelled:()->Boolean):Inspection {
        AndroidDkInstallUsbOwner.open(context,deviceName,"First-install read-only identity",cancelled).use{usb->
            val session=DkSwdJlinkSession(usb.channel,cancelled=cancelled)
            session.initialize{_,_->};val initial=session.identify{_,_->};val source=session.openBackupSource()
            require(source.currentIdentity()==initial);val ficr=ByteArray(4096)
            for(offset in ficr.indices step 512){if(cancelled())error("Identity inspection cancelled");source.readBlock(DkBackupRegion.FICR,offset,512).copyInto(ficr,offset)}
            require(source.currentIdentity()==initial)
            val identity=OriginalArchive.identityFromFicr(ficr).also{require(it.uid0==initial.uid0&&it.uid1==initial.uid1&&it.part==initial.part)}
            // Separate initial-install read capability; the original immutable
            // diagnostic/backup policy remains unchanged. No CPU control write.
            val channel=object:InstallBulkChannel{override fun write(bytes:ByteArray)=usb.channel.write(bytes);override fun read(maxBytes:Int)=usb.channel.read(maxBytes)}
            val wire=JlinkInstallWire(channel,usb::check);wire.initialize()
            fun number(bytes:ByteArray,offset:Int=0)=(0..3).fold(0L){v,i->v or ((bytes[offset+i].toLong() and 255) shl(i*8))}
            val uid=wire.readWords(0x10000060,8);require(number(uid)==identity.uid0&&number(uid,4)==identity.uid1)
            val run=number(wire.readWords(0x40010400,4));val fields=wire.readWords(0x40010504,12)
            require(number(wire.readWords(0x40010400,4))==run){"Watchdog changed during read-only inspection; inspect again"}
            return Inspection(identity,ObservedWatchdogProfile(run,number(fields,8),number(fields),number(fields,4)))
        }
    }
}
