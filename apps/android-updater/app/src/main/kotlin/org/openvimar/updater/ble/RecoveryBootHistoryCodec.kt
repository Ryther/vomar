package org.openvimar.updater.ble

import org.openvimar.updater.core.*

internal object RecoveryBootHistoryCodec {
 fun decode(bytes:ByteArray)=fromMap(StrictSmpCbor.decode(bytes,allowSignedIntegers=true))
 fun fromMap(map:Map<String,Any>):RecoveryBootHistory {
  require(map.keys==setOf("protocol","record_size","capacity","current_image","sequence","pending_reason","state","entries")){"Unsupported recovery boot-history fields"}
  fun Map<*,*>.number(key:String,min:Long=0,max:Long=0xffffffffL):Long {
   val value=this[key];require(value is Long&&value in min..max){"Boot-history $key must be an exact bounded integer"};return value
  }
  fun Map<*,*>.bool(key:String):Boolean {val value=this[key];require(value is Boolean){"Boot-history $key must be a CBOR boolean"};return value}
  val state=map["state"] as? Map<*,*> ?: error("Boot-history state is missing")
  require(state.keys==setOf("initialized","loaded_valid","storage_valid","load_rc","decode_rc","save_rc","view_rc")){"Unsupported boot-history state"}
  val entries=map["entries"] as? List<*> ?: error("Boot-history entries are missing")
  require(entries.size<=6){"Boot-history entry bound exceeded"}
  fun rc(key:String)=state.number(key,Int.MIN_VALUE.toLong(),Int.MAX_VALUE.toLong()).toInt()
  return RecoveryBootHistory(map.number("protocol",1,1).toInt(),map.number("record_size",88,88).toInt(),map.number("capacity",6,6).toInt(),map.number("current_image",1,1).toInt(),
   map.number("sequence"),map.number("pending_reason",0,7).toInt(),BootHistoryState(state.bool("initialized"),state.bool("loaded_valid"),state.bool("storage_valid"),rc("load_rc"),rc("decode_rc"),rc("save_rc"),rc("view_rc")),
   entries.map {raw->val entry=raw as? Map<*,*> ?: error("Invalid boot-history entry")
    require(entry.keys==setOf("seq","image","reason","raw_reset_flags")){"Unsupported boot-history entry"}
    BootHistoryEntry(entry.number("seq"),entry.number("image",0,1).toInt(),entry.number("reason",0,7).toInt(),entry.number("raw_reset_flags"))}).also{it.validate()}
 }
}
