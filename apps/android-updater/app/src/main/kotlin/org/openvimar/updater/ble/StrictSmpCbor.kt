package org.openvimar.updater.ble

import io.runtime.mcumgr.response.McuMgrResponse
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction

/** Small bounded CBOR subset for project identity/boot responses. The Nordic
 * mapper is intentionally not used for authority-bearing scalar types: it
 * coerces strings/floats into integers and strings/numbers into booleans. */
internal object StrictSmpCbor {
    fun response(response:McuMgrResponse,group:Int,operation:Int,expectedCmd:Int=0,allowSignedIntegers:Boolean=false):Map<String,Any> {
        val payload=requireNotNull(response.payload){"Original SMP payload is missing"}
        val header=requireNotNull(response.header){"Original SMP header is missing"}
        require(header.len==payload.size&&header.groupId==group&&header.commandId==expectedCmd&&header.op==operation&&header.version in 0..1&&header.flags==0){"SMP response header mismatch"}
        return decode(payload,allowSignedIntegers)
    }
    fun decode(bytes:ByteArray,allowSignedIntegers:Boolean=false):Map<String,Any> {
        require(bytes.size in 1..1024){"SMP response exceeds project contract"}
        val reader=Reader(bytes,allowSignedIntegers);val value=reader.item(0)
        require(reader.offset==bytes.size&&value is Map<*,*>){"SMP response must be exactly one map"}
        @Suppress("UNCHECKED_CAST") return value as Map<String,Any>
    }
    private class Reader(val bytes:ByteArray,val allowSignedIntegers:Boolean) {
        var offset=0
        private fun byte():Int {require(offset<bytes.size){"Truncated CBOR"};return bytes[offset++].toInt() and 255}
        private fun number(extra:Int):Long=when(extra) {
            in 0..23->extra.toLong()
            24->byte().toLong()
            25->(byte().toLong() shl 8) or byte().toLong()
            26->{var n=0L;repeat(4){n=(n shl 8) or byte().toLong()};n}
            else->throw IllegalArgumentException("Unsupported CBOR length/integer width")
        }
        fun item(depth:Int):Any {
            require(depth<=3){"CBOR nesting exceeds project contract"}
            val head=byte();val major=head shr 5;val extra=head and 31
            return when(major) {
                0->number(extra)
                1->{require(allowSignedIntegers){"Signed CBOR integer is unsupported in this response"};-1L-number(extra)}
                2,3->{val length=number(extra);require(length<=256&&length<=bytes.size-offset){"Invalid CBOR string size"}
                    val data=bytes.copyOfRange(offset,offset+length.toInt());offset+=length.toInt()
                    if(major==2)data else Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                        .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(data)).toString()}
                4,5->{val indefinite=extra==31;val count=if(indefinite)0 else number(extra).toInt().also{require(it in 0..8)}
                    val list=mutableListOf<Any>();val map=linkedMapOf<String,Any>();var n=0
                    while(if(indefinite){require(offset<bytes.size);(bytes[offset].toInt() and 255)!=255} else n<count) {
                        require(n<8){"CBOR container too large"}
                        if(major==4)list+=item(depth+1)
                        else {val key=item(depth+1);require(key is String&&key !in map){"Duplicate or non-text CBOR key"};map[key]=item(depth+1)}
                        n++
                    }
                    if(indefinite)byte()
                    if(major==4)list else map}
                7->when(extra){20->false;21->true;else->throw IllegalArgumentException("Only CBOR booleans are accepted")}
                else->throw IllegalArgumentException("Unsupported CBOR scalar")
            }
        }
    }
}
