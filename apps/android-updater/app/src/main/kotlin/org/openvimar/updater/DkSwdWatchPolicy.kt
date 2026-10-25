package org.openvimar.updater

import java.util.UUID

internal enum class DkSwdWatchKind { STOPPED, SEARCHING, DK_ABSENT, PERMISSION, DK_PRESENT, USB_BUSY, VOLTAGE, PROBE_ONLY, SWD_PARTIAL, IDENTITY }
internal data class DkSwdWatchToken(val generation:Long,val attempt:Int)
internal data class DkSwdWatchAttempt(val number:Int,val observations:Map<String,Any>,val error:String?,val cancelled:Boolean)
internal data class DkSwdWatchSnapshot(val running:Boolean,val inFlight:Boolean,val kind:DkSwdWatchKind,val message:String,
    val stableCount:Int,val uid:List<String>?,val recent:List<DkSwdWatchAttempt>,val totalAttempts:Int)

/** Metadata-only admission and observation state. Completion releases a USB attempt
 * even after Stop; a later session cannot start while that attempt is draining. */
internal class DkSwdWatchPolicy(private val now:()->Long={System.nanoTime()/1_000_000},private val recentLimit:Int=40) {
    init {require(recentLimit in 1..100)}
    private var running=false
    private var generation=0L
    private var lease:DkSwdWatchToken?=null
    private var due=0L
    private var total=0
    private var sessionId=""
    private var stableCount=0
    private var stableUid:List<String>?=null
    private var current=linkedMapOf<String,Any>()
    private val recent=ArrayDeque<DkSwdWatchAttempt>()
    private var kind=DkSwdWatchKind.STOPPED
    private var message="Monitor stopped. Tap Start SWD monitor to look for a target."
    @Synchronized fun start():Boolean {
        if(running||lease!=null)return false
        generation++;running=true;sessionId=UUID.randomUUID().toString();total=0;recent.clear();current.clear()
        stableCount=0;stableUid=null;due=now();kind=DkSwdWatchKind.SEARCHING;message="Looking for the DK and a target…"
        return true
    }
    @Synchronized fun accepts(token:DkSwdWatchToken)=active(token)
    @Synchronized fun beginAttempt():DkSwdWatchToken? {
        if(!running||lease!=null||now()<due)return null
        return DkSwdWatchToken(generation,++total).also{lease=it;current=linkedMapOf()}
    }
    @Synchronized fun observe(token:DkSwdWatchToken,key:String,value:Any):Boolean {
        if(!active(token)||key.length !in 1..64||current.size>=64&&key !in current)return false
        val safe:Any=when(value) {
            is String->value.take(512)
            is Int,is Long,is Boolean->value
            is List<*>->if(value.size<=4&&value.all{it is String})value.map{(it as String).take(64)} else return false
            else->return false
        }
        current[key]=safe
        if(kind!=DkSwdWatchKind.IDENTITY || key=="usbOperationBusy"&&safe==true || key=="dkPresent"&&safe==false || key=="usbPermissionGranted"&&safe==false || key=="targetMillivolts"&&safe is Int&&safe !in 1700..3600)classify(false)
        return true
    }
    @Synchronized fun complete(token:DkSwdWatchToken,error:String?=null):Boolean {
        if(lease!=token)return false
        lease=null
        if(!running||token.generation!=generation){current.clear();kind=DkSwdWatchKind.STOPPED;message="Monitor stopped. Tap Start SWD monitor to try again.";return false}
        val uid=verifiedUid().takeIf{error==null}
        if(uid!=null){stableCount=if(uid==stableUid)stableCount+1 else 1;stableUid=uid}
        else{stableCount=0;stableUid=null}
        append(DkSwdWatchAttempt(token.attempt,current.toMap(),error?.take(512),false));classify(uid!=null)
        due=now()+1000;return true
    }
    @Synchronized fun stop():Boolean {
        if(!running)return false
        running=false;generation++;stableCount=0;stableUid=null
        lease?.let{append(DkSwdWatchAttempt(it.attempt,current.toMap(),"Stopped by user or screen lifecycle",true))}
        kind=DkSwdWatchKind.STOPPED;message=if(lease!=null)"Stopping SWD monitor…" else "Monitor stopped. Tap Start SWD monitor to try again."
        return true
    }
    @Synchronized fun snapshot()=DkSwdWatchSnapshot(running,lease!=null,kind,message,stableCount,stableUid?.toList(),recent.toList(),total)
    @Synchronized fun reportFields():Map<String,Any> = linkedMapOf("schema" to 1,"type" to "dk-swd-watch-read-only","sessionId" to sessionId,
        "running" to running,"attemptInFlight" to (lease!=null),"totalAttempts" to total,"recentLimit" to recentLimit,
        "stableConsecutiveReads" to stableCount,"recentAttempts" to recent.map{row->linkedMapOf<String,Any>("attempt" to row.number,
            "observations" to row.observations,"cancelled" to row.cancelled).apply{row.error?.let{put("error",it)}}},
        "haltAttempted" to false,"resetAttempted" to false,"memoryWrite" to false,"eraseAttempted" to false,"flashed" to false,
        "commercialModelVerified" to false,"targetSupplyChanged" to false)
    private fun active(token:DkSwdWatchToken)=running&&lease==token&&token.generation==generation
    private fun append(attempt:DkSwdWatchAttempt){recent.addLast(attempt);while(recent.size>recentLimit)recent.removeFirst()}
    private fun number(key:String)=when(val value=current[key]){is String->value.removePrefix("0x").toLongOrNull(16);is Number->value.toLong();else->null}
    private fun verifiedUid():List<String>? {
        if(current["identityReadVerified"]!=true||number("dpidr")!=0x2ba01477L||number("part")!=0x52840L)return null
        val words=current["uid"] as? List<*> ?: return null
        if(words.size!=2)return null
        return words.map{word->val value=(word as? String)?.removePrefix("0x")?.toLongOrNull(16) ?: return null
            if(value !in 0L..0xffffffffL)return null
            "%08x".format(java.util.Locale.ROOT,value)}
    }
    private fun classify(full:Boolean) {
        val mv=current["targetMillivolts"] as? Int
        kind=when {
            current["usbOperationBusy"]==true->DkSwdWatchKind.USB_BUSY
            full->DkSwdWatchKind.IDENTITY
            number("dpidr")==0x2ba01477L->DkSwdWatchKind.SWD_PARTIAL
            current["dkPresent"]==false->DkSwdWatchKind.DK_ABSENT
            current["usbPermissionGranted"]==false->DkSwdWatchKind.PERMISSION
            mv!=null&&mv !in 1700..3600->DkSwdWatchKind.VOLTAGE
            current.containsKey("probeFirmware")->DkSwdWatchKind.PROBE_ONLY
            current["dkPresent"]==true->DkSwdWatchKind.DK_PRESENT
            else->DkSwdWatchKind.SEARCHING
        }
        message=when(kind) {
            DkSwdWatchKind.USB_BUSY->"The DK is in use by another operation. Wait for it to finish or stop it first."
            DkSwdWatchKind.IDENTITY->"nRF52840 detected — UID ${stableUid!!.joinToString("/")} — $stableCount matching reads"
            DkSwdWatchKind.SWD_PARTIAL->"SWD responds; full chip identity is not readable yet. Adjust the contacts and wait."
            DkSwdWatchKind.DK_ABSENT->"DK not found. Check the USB data cable and OTG connection."
            DkSwdWatchKind.PERMISSION->if(current["usbPermissionDenied"]==true)"USB access was denied. Stop and start the monitor to try again." else "Allow USB access in Android to continue monitoring."
            DkSwdWatchKind.DK_PRESENT->if(current["ambiguousDk"]==true)"More than one DK found. Connect one DK to monitor." else "DK connected; checking the probe and target."
            DkSwdWatchKind.VOLTAGE->"Target reference is ${"%.3f".format(java.util.Locale.ROOT,(mv ?: 0)/1000.0)} V. Check target power."
            DkSwdWatchKind.PROBE_ONLY->"J-Link connected; SWD identity is not readable. Adjust the contacts and wait."
            else->"Looking for the DK and a target…"
        }
    }
}
