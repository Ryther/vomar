package org.openvimar.updater.installer

import android.content.Context
import android.hardware.usb.UsbManager
import org.openvimar.installer.QuiescentProvenance
import org.openvimar.updater.*
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean

/** One connection shared by a single explicit inspection OR entire writer
 * operation. Its owner token is released only after physical close completes. */
internal class AndroidDkInstallUsbOwner private constructor(val token:DkUsbOperationGate.Lease,
    val channel:DkBulkChannel,val provenance:QuiescentProvenance,
    private val checkConnection:()->Unit,private val closeConnection:()->Unit):AutoCloseable {
    fun check()=checkConnection()
    override fun close()=closeConnection()
    companion object {
        fun open(context:Context,deviceName:String,owner:String,cancelled:()->Boolean):AndroidDkInstallUsbOwner {
            val token=DkUsbOperationGate.acquire(owner)?:throw IOException("Another DK USB operation owns the probe")
            var closer:(()->Unit)?=null
            try{
                val manager=context.getSystemService(Context.USB_SERVICE) as UsbManager
                val device=manager.deviceList.values.singleOrNull{it.deviceName==deviceName}?:throw IOException("Selected USB probe is disconnected")
                require(manager.hasPermission(device)){"USB owner permission is required"}
                val descriptors=(0 until device.interfaceCount).map{index->val p=device.getInterface(index)
                    DkUsbInterfaceDescriptor(index,p.id,p.alternateSetting,p.interfaceClass,p.interfaceSubclass,p.interfaceProtocol,p.name,
                        (0 until p.endpointCount).map{p.getEndpoint(it).let{e->DkUsbEndpointDescriptor(e.address,e.attributes,e.maxPacketSize,e.interval)}})}
                val selected=DkJlinkInterfaceSelector.select(device.vendorId,device.productId,descriptors)
                val descriptor=selected.port?:throw IOException(selected.error)
                val port=device.getInterface(descriptor.index);val endpoints=(0 until port.endpointCount).map(port::getEndpoint)
                val input=endpoints.single{it.address==selected.input?.address};val output=endpoints.single{it.address==selected.output?.address}
                val connection=manager.openDevice(device)?:throw IOException("Android could not open the selected J-Link")
                val closed=AtomicBoolean(false);var claimed=false
                closer={if(closed.compareAndSet(false,true)){
                    try{if(claimed)connection.releaseInterface(port)}finally{connection.close();token.close()}
                }}
                val presence=DkUsbPresenceGuard{require(manager.deviceList.values.any{it.deviceName==device.deviceName&&it.deviceId==device.deviceId}){"USB generation disconnected; reconnect is prohibited"}}
                fun transport(){token.checkCurrent();check(!closed.get()){ "USB connection already closed" };presence.check()}
                if(cancelled())throw IOException("USB operation cancelled before claim")
                claimed=connection.claimInterface(port,false);require(claimed){"J-Link interface is busy"}
                val buffered=DkSwdBufferedChannel(object:DkBulkChannel {
                    override fun write(bytes:ByteArray):Int {transport();return connection.bulkTransfer(output,bytes,bytes.size,2000).also{transport()}}
                    override fun read(maxBytes:Int):ByteArray {transport();val bytes=ByteArray(maxBytes);val n=connection.bulkTransfer(input,bytes,bytes.size,2000);transport()
                        if(n<=0)throw IOException("USB read timed out/disconnected");return bytes.copyOf(n)}
                })
                val probe=DkJlinkReadOnly.probe(buffered)
                require(probe.targetMillivolts in 1700..3600){"Target reference voltage is outside 1.7..3.6V"}
                if(cancelled())throw IOException("USB operation cancelled after probe check")
                @Suppress("DEPRECATION") val version=context.packageManager.getPackageInfo(context.packageName,0).versionName?:throw IOException("App version unavailable")
                return AndroidDkInstallUsbOwner(token,buffered,QuiescentProvenance(version,probe.firmware,probe.targetMillivolts,
                    device.vendorId,device.productId,port.id,input.address,output.address),::transport,checkNotNull(closer))
            }catch(error:Exception){try{closer?.invoke()?:token.close()}catch(close:Exception){error.addSuppressed(close)};throw error}
        }
    }
}
