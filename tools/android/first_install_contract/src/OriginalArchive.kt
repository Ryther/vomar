package org.openvimar.installer

import java.time.Instant

/** Trusted future SAF adapter: create returns a token only after successful
 * complete export; reopen must open that exact returned document. */
interface ArchiveExport {
    fun create(bytes:ByteArray):String?
    fun reopen(document:String):ByteArray
}
data class TargetIdentity(val uid0:Long,val uid1:Long,val variant:Long,val part:Long=0x52840,
    val flashSize:Int=0x100000,val pageSize:Int=4096,val ramSize:Int=0x40000,val uicrSize:Int=4096)
class VerifiedOriginal internal constructor(archiveBytes:ByteArray,flash:ByteArray,
    ficr:ByteArray,uicr:ByteArray,val identity:TargetIdentity) {
    private val frozenArchive=archiveBytes.copyOf();private val frozenFlash=flash.copyOf()
    private val frozenFicr=ficr.copyOf();private val frozenUicr=uicr.copyOf()
    val archiveSha256=sha256(frozenArchive)
    internal fun archive()=frozenArchive.copyOf()
    internal fun flash()=frozenFlash.copyOf()
    internal fun ficr()=frozenFicr.copyOf()
    internal fun uicr()=frozenUicr.copyOf()
    /** Read-only preflight, deliberately before any SAF export. It does not
     * derive the page table/anchor or grant installation authority. */
    fun requireFirstInstallCompatible(){
        require((0xb0000 until 0xef000).all{frozenFlash[it]==0xff.toByte()}){"Original scratch is not erased; do not export this as a fresh stock original"}
        require(!frozenFlash.copyOfRange(0xb000,0xb004).contentEquals("VAR1".toByteArray(Charsets.US_ASCII))){"Project anchor marker already exists; reuse the protected original with explicit resume/repair"}
    }
}
class ExportedOriginal internal constructor(private val original:VerifiedOriginal,val document:String) {
    fun deriveOriginal():OriginalMaterial {
        original.requireFirstInstallCompatible()
        val flash=original.flash();val table=AnchorV1.table(flash)
        val i=original.identity
        val anchor=AnchorV1.encode(i.variant,i.uid0,i.uid1,sha256(flash),sha256(original.uicr()),sha256(table))
        return OriginalMaterial(original,table,anchor,document)
    }
}
class OriginalMaterial internal constructor(internal val original:VerifiedOriginal,table:ByteArray,anchor:ByteArray,val document:String) {
    private val frozenTable=table.copyOf();private val frozenAnchor=anchor.copyOf()
    val identity get()=original.identity
    val archiveSha256 get()=original.archiveSha256
    val ficrSha256 get()=sha256(original.ficr())
    val uicrSha256 get()=sha256(original.uicr())
    fun table()=frozenTable.copyOf()
    fun anchor()=frozenAnchor.copyOf()
}
object OriginalArchive {
    const val MAX_ZIP=2*1024*1024
    private val limits=linkedMapOf("flash.bin" to 0x100000,"ficr.bin" to 4096,"uicr.bin" to 4096,
        "manifest.json" to 65536,"README.txt" to 8192)
    fun exportAndReopen(original:VerifiedOriginal,port:ArchiveExport):ExportedOriginal {
        val document=requireNotNull(port.create(original.archive())){"Export cancelled or failed"}
        require(document.isNotBlank()&&document.length<=4096)
        val reopened=verify(port.reopen(document))
        require(reopened.archive().contentEquals(original.archive())){"Reopened export differs from verified original ZIP"}
        return ExportedOriginal(reopened,document)
    }
    fun verify(input:ByteArray):VerifiedOriginal {
        require(input.size in 22..MAX_ZIP);val bytes=input.copyOf();val entries=StrictZip.read(bytes,limits,MAX_ZIP)
        val raw=obj(StrictJson.parse(entries.getValue("manifest.json")))
        if(raw["schema"]==2L)return verifyOpenOcd(bytes,entries,raw)
        val halted=raw["type"]=="nrf52840-quiescent-first-install-backup"
        val m=keys(raw,setOf("schema","type","target","byteExactDoubleRead","startedAt","verifiedAt","snapshotAtomic","protocol","scope","provenance","regions")+(if(halted)setOf("acquisition") else emptySet()))
        require(m["schema"]==1L&&(halted||m["type"]=="nrf52840-read-only-double-backup")&&m["byteExactDoubleRead"]==true&&m["snapshotAtomic"]==false)
        fun time(v:Any?):Instant {require(v is String&&Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,9})?Z").matches(v));return Instant.parse(v)}
        require(time(m["verifiedAt"])>=time(m["startedAt"]))
        var resetCatch=false
        if(halted){val acquisition=obj(m["acquisition"]);val acquisitionFields=setOf("cpuHalted","method","originalCpuControl")
            require(acquisition.keys.containsAll(acquisitionFields)&&(acquisition.keys-acquisitionFields).all{it=="watchdog"})
            require(acquisition["cpuHalted"]==true&&acquisition["method"] in setOf("debug-halt","reset-vector-catch")&&acquisition["originalCpuControl"] in setOf(0L,1L,3L))
            if("watchdog" in acquisition)ObservedWatchdogProfile.fromContract(acquisition["watchdog"])
            resetCatch=acquisition["method"]=="reset-vector-catch"}
        exact(m["protocol"],mapOf("id" to if(halted)"jlink-raw-swd-ap0-halted-backup-v1" else "jlink-raw-swd-ap0-read-v1","swdClockKhz" to 100L,"maxBlockBytes" to 512L,"tarBoundaryBytes" to 1024L,"independentBlockSentinels" to true))
        exact(m["scope"],mapOf("haltAttempted" to halted,"resetAttempted" to resetCatch,"eraseAttempted" to false,"memoryWrite" to halted,"flashed" to false,"targetSupplyChanged" to false,"debugPortConfigured" to true,"restorationVerified" to false)+(if(halted)mapOf("flashWrite" to false,"uicrWrite" to false) else emptyMap()))
        val provenance=keys(m["provenance"],setOf("appVersion","probeFirmware","usbVendorId","usbProductId","interfaceId","inputEndpoint","outputEndpoint","targetMillivolts"))
        for((name,limit) in listOf("appVersion" to 128,"probeFirmware" to 1024)){val value=provenance[name];require(value is String&&value.isNotBlank()&&value.length<=limit)}
        require(provenance["usbVendorId"]==0x1366L&&provenance["usbProductId"]==0x1060L)
        require((provenance["interfaceId"] as? Long)?.let{it in 0..Int.MAX_VALUE.toLong()}==true&&
            (provenance["inputEndpoint"] as? Long) in 0x81L..0x8fL&&(provenance["outputEndpoint"] as? Long) in 1L..15L&&
            (provenance["targetMillivolts"] as? Long) in 1700L..3600L)
        require(StrictJson.text(entries.getValue("README.txt")).isNotBlank())
        val regions=m["regions"] as? List<*>;require(regions!=null&&regions.size==3)
        listOf("flash.bin" to 0L,"ficr.bin" to 0x10000000L,"uicr.bin" to 0x10001000L).forEachIndexed{i,(name,start)->
            exact(regions[i],mapOf("file" to name,"start" to "0x%08x".format(start),"size" to limits.getValue(name).toLong(),"sha256" to sha256(entries.getValue(name)),"verifiedCopies" to 2L))
            require(entries.getValue(name).size==limits.getValue(name))}
        val f=entries.getValue("ficr.bin");val flash=entries.getValue("flash.bin");val uicr=entries.getValue("uicr.bin")
        val i=identityFromFicr(f)
        val stack=word(flash,0);val reset=word(flash,4)
        require(stack>0x20000000L&&stack<=0x20040000L&&stack%8==0L&&reset and 1L==1L&&(reset and 0xfffffffeL) in 8L until 0x100000L)
        exact(m["target"],targetFor(flash,f))
        return VerifiedOriginal(bytes,flash,f,uicr,i)
    }
    /** Truthful OpenOCD provenance; never labels this as raw J-Link USB. */
    private fun verifyOpenOcd(bytes:ByteArray,e:Map<String,ByteArray>,raw:Map<String,Any?>):VerifiedOriginal {
        val m=keys(raw,setOf("schema","type","target","regions","startedAt","verifiedAt","acquisition","provenance"))
        require(m["schema"]==2L&&m["type"]=="nrf52840-openocd-halted-backup-v1")
        val f=e.getValue("ficr.bin");val flash=e.getValue("flash.bin");val uicr=e.getValue("uicr.bin")
        require(f.size==4096&&flash.size==0x100000&&uicr.size==4096&&e.getValue("README.txt").toString(Charsets.UTF_8).isNotBlank())
        val i=identityFromFicr(f)
        exact(m["target"],mapOf("uid" to listOf("%08x".format(i.uid0),"%08x".format(i.uid1)),"variant" to i.variant,"part" to 0x52840L,"commercialModelVerified" to false))
        val a=keys(m["acquisition"],setOf("cpuHalted","byteExactDoubleRead","flashWrite","uicrWrite","watchdog"))
        require(a["cpuHalted"]==true&&a["byteExactDoubleRead"]==true&&a["flashWrite"]==false&&a["uicrWrite"]==false)
        ObservedWatchdogProfile.fromContract(a["watchdog"])
        val p=keys(m["provenance"],setOf("transport","version","serial"));require(p["transport"]=="openocd")
        listOf("version","serial").forEach{val v=p[it];require(v is String&&v.isNotBlank()&&v.length<=1024)}
        val start=Instant.parse(m["startedAt"] as String);val end=Instant.parse(m["verifiedAt"] as String);require(end>=start)
        val regions=m["regions"] as? List<*>;require(regions?.size==3)
        listOf("flash.bin" to 0L,"ficr.bin" to 0x10000000L,"uicr.bin" to 0x10001000L).forEachIndexed{n,(file,at)->
            exact(requireNotNull(regions)[n],mapOf("file" to file,"start" to "0x%08x".format(at),"size" to e.getValue(file).size.toLong(),"sha256" to sha256(e.getValue(file)),"verifiedCopies" to 2L))}
        val stack=word(flash,0);val reset=word(flash,4)
        require(stack>0x20000000L&&stack<=0x20040000L&&stack%8==0L&&reset and 1L==1L&&(reset and 0xfffffffeL) in 8L until 0x100000L)
        return VerifiedOriginal(bytes,flash,f,uicr,i)
    }
    fun identityFromFicr(ficr:ByteArray):TargetIdentity {
        require(ficr.size==4096&&listOf(0x10 to 4096L,0x14 to 256L,0x100 to 0x52840L,0x10c to 256L,0x110 to 1024L).all{word(ficr,it.first)==it.second})
        return TargetIdentity(word(ficr,0x60),word(ficr,0x64),word(ficr,0x104)).also{require(it.variant in 1..0xfffffffeL)}
    }
    internal fun targetFor(flash:ByteArray,ficr:ByteArray):Map<String,Any?> {
        val recognized=stock.filter{sha256(flash.copyOfRange((it.getValue("offset") as Long).toInt(),((it.getValue("offset") as Long)+(it.getValue("size") as Long)).toInt()))==it["sha256"]}
        val target=linkedMapOf<String,Any?>("chip" to "nRF52840","part" to "0x00052840","uid" to listOf("0x%08x".format(word(ficr,0x60)),"0x%08x".format(word(ficr,0x64))),"identitySource" to "live FICR before/after both passes","commercialModelVerified" to false,
            "model" to if(recognized.isEmpty())"unknown nRF52840 device" else "stock application recognized; hardware model unverified")
        if(recognized.isNotEmpty()){target["applicationDigestMatched"]=true;target["firmwareModel"]=recognized.map{it["model"]}.distinct().joinToString(",");target["recognizedApplications"]=recognized}
        return target
    }
    private val stock=listOf(
        mapOf("id" to "vimar-30805-mesh","model" to "VIMAR30805","radio" to "mesh","offset" to 0x26000L,"size" to 213012L,"sha256" to "8c0408c49fe3e35758a69e511faa154c2f1237512e1c1bfdf1061221db53f927"),
        mapOf("id" to "vimar-30805-zigbee","model" to "VIMAR30805","radio" to "zigbee","offset" to 0x26000L,"size" to 343988L,"sha256" to "710f788a02eca3985d5826efacf47cef8d8fa29dde4684815c25c8c9a79690d5"))
}
