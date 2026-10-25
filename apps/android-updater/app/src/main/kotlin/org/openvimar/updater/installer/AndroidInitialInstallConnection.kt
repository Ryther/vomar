package org.openvimar.updater.installer

import android.content.Context
import org.openvimar.installer.WatchdogHandoffAuthority
import org.openvimar.installer.resume.ResumeHardwareAuthority

/** Only an already verified/reviewed capture or receipt operation opens this
 * writer capability; neither service creation nor UI binding calls it. */
internal object AndroidInitialInstallConnection {
    fun open(context:Context,request:InstallCaptureRequest,cancelled:()->Boolean,
        handoff:(Long)->WatchdogHandoffAuthority?={null},resume:((Long)->ResumeHardwareAuthority)?=null,verifiedStart:InitialInstallReceipt?=null):InitialInstallConnection {
        val usb=AndroidDkInstallUsbOwner.open(context,request.deviceName,"First installation ${request.requestId}",cancelled)
        val channel=object:InstallBulkChannel{override fun write(bytes:ByteArray)=usb.channel.write(bytes);override fun read(maxBytes:Int)=usb.channel.read(maxBytes)}
        val lease=NrfInitialInstallLease(JlinkInstallWire(channel,usb::check),usb.token,cancelled)
        try {
            require(!request.allowResetCatch){"Pre-backup reset is unsupported; hardware watchdog must be inactive"}
            val capability=handoff(usb.token.generation)
            require(resume==null||verifiedStart==null)
            if(resume!=null)lease.openForResume(request.target,resume(usb.token.generation),capability)
            else if(verifiedStart!=null)lease.openForVerifiedStart(request.target,verifiedStart,capability)
            else lease.open(request.target,watchdogHandoff=capability)
            return object:InitialInstallConnection{override val lease=lease;override val provenance=usb.provenance;override fun close()=usb.close()}
        }catch(error:Exception){
            var cleanup:Exception?=null
            try{lease.finish()}catch(failure:Exception){cleanup=failure}
            try{usb.close()}catch(failure:Exception){cleanup=failure}
            if(cleanup!=null){error.addSuppressed(cleanup);throw InitialInstallConnectionException("CPU state uncertain; no reconnect/resume attempted",error,lease.resetCatchUsed,lease.debugStateUncertain,lease.watchdogProfile,lease.watchdogHandoff)}
            val disposition=if((lease.haltRetentionRequired||resume!=null||verifiedStart!=null)&&!lease.haltConfirmed)"Prior FLASH/debug uncertainty retained; CPU HALT was not confirmed; no automatic release attempted"
                else if(lease.haltRetentionRequired)"CPU halt confirmed and retained; no automatic release attempted"
                else "Pre-write original CPU control restoration completed; no NVMC operation requested"
            throw InitialInstallConnectionException(disposition,error,lease.resetCatchUsed,lease.debugStateUncertain,lease.watchdogProfile,lease.watchdogHandoff)
        }
    }
}
