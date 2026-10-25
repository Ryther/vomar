package org.openvimar.installer

import java.io.ByteArrayOutputStream
import java.time.Instant
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

data class QuiescentProvenance(val appVersion:String,val probeFirmware:String,val targetMillivolts:Int,
    val usbVendorId:Int,val usbProductId:Int,val interfaceId:Int,val inputEndpoint:Int,val outputEndpoint:Int)

/** Produces only the NEW truthful halted-acquisition contract. The caller must
 * retain its exclusive halted connection through capture/export/install. This
 * data encoder cannot independently attest that acquisition provenance. */
object QuiescentArchive {
    fun create(first:Map<String,ByteArray>,second:Map<String,ByteArray>,provenance:QuiescentProvenance,
        startedAt:Instant,verifiedAt:Instant,originalCpuControl:Int,resetCatch:Boolean,watchdog:ObservedWatchdogProfile?=null):ByteArray {
        val sizes=linkedMapOf("flash.bin" to 0x100000,"ficr.bin" to 4096,"uicr.bin" to 4096)
        require(first.keys==sizes.keys&&second.keys==sizes.keys&&originalCpuControl in setOf(0,1,3))
        val frozen=sizes.mapValues{(file,size)->
            val a=first.getValue(file).copyOf();val b=second.getValue(file).copyOf()
            require(a.size==size&&b.size==size&&a.contentEquals(b)){"Incomplete or changed quiescent original passes"};a}
        val p=provenance
        val manifest=mapOf("schema" to 1L,"type" to "nrf52840-quiescent-first-install-backup",
            "target" to OriginalArchive.targetFor(frozen.getValue("flash.bin"),frozen.getValue("ficr.bin")),
            "byteExactDoubleRead" to true,"startedAt" to startedAt.toString(),"verifiedAt" to verifiedAt.toString(),"snapshotAtomic" to false,
            "protocol" to mapOf("id" to "jlink-raw-swd-ap0-halted-backup-v1","swdClockKhz" to 100L,"maxBlockBytes" to 512L,"tarBoundaryBytes" to 1024L,"independentBlockSentinels" to true),
            "scope" to mapOf("haltAttempted" to true,"resetAttempted" to resetCatch,"eraseAttempted" to false,"memoryWrite" to true,"flashWrite" to false,"uicrWrite" to false,
                "flashed" to false,"targetSupplyChanged" to false,"debugPortConfigured" to true,"restorationVerified" to false),
            "acquisition" to (mapOf("cpuHalted" to true,"method" to if(resetCatch)"reset-vector-catch" else "debug-halt","originalCpuControl" to originalCpuControl.toLong())+
                (if(watchdog==null)emptyMap() else mapOf("watchdog" to watchdog.asContract()))),
            "provenance" to mapOf("appVersion" to p.appVersion,"probeFirmware" to p.probeFirmware,"usbVendorId" to p.usbVendorId.toLong(),"usbProductId" to p.usbProductId.toLong(),
                "interfaceId" to p.interfaceId.toLong(),"inputEndpoint" to p.inputEndpoint.toLong(),"outputEndpoint" to p.outputEndpoint.toLong(),"targetMillivolts" to p.targetMillivolts.toLong()),
            "regions" to sizes.keys.map{file->mapOf("file" to file,"start" to when(file){"flash.bin"->"0x00000000";"ficr.bin"->"0x10000000";else->"0x10001000"},
                "size" to sizes.getValue(file).toLong(),"sha256" to sha256(frozen.getValue(file)),"verifiedCopies" to 2L)})
        val files=frozen+mapOf("manifest.json" to (StrictJson.canonical(manifest)+"\n").toByteArray(Charsets.UTF_8),
            "README.txt" to ("Verified original FLASH/FICR/UICR, two byte-equal passes while CPU halted.\n"+
                "Debug-control writes and optional reset are recorded in manifest.json. No FLASH/UICR write or erase occurred during this acquisition.\n"+
                "Acquisition provenance is producer-reported. This archive alone does not qualify hardware or prove BLE restoration.\n").toByteArray(Charsets.UTF_8))
        val output=ByteArrayOutputStream()
        ZipOutputStream(output).use{zip->files.forEach{(file,bytes)->zip.putNextEntry(ZipEntry(file).apply{time=0});zip.write(bytes);zip.closeEntry()}}
        return output.toByteArray().also{OriginalArchive.verify(it)}
    }
}
