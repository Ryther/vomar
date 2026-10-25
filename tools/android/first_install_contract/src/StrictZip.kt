package org.openvimar.installer

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.zip.CRC32
import java.util.zip.ZipInputStream

/** Fixed caller-owned entry limits; no extraction or path-based IO. */
internal object StrictZip {
    private data class Member(val size:Int,val compressed:Int,val crc:Long,val offset:Int,val flags:Int,val method:Int)
    fun read(bytes:ByteArray,limits:Map<String,Int>,maximum:Int,required:Set<String> = limits.keys,expandedLimit:Int=limits.values.sum()):Map<String,ByteArray> {
        require(bytes.size in 22..maximum)
        fun u16(o:Int):Int {require(o>=0&&o<=bytes.size-2);return (bytes[o].toInt() and 255) or ((bytes[o+1].toInt() and 255) shl 8)}
        fun n32(o:Int):Int=word(bytes,o).also{require(it<=Int.MAX_VALUE)}.toInt()
        val end=bytes.size-22;require(word(bytes,0)==0x04034b50L&&word(bytes,end)==0x06054b50L)
        require(u16(end+4)==0&&u16(end+6)==0&&u16(end+8)==u16(end+10)&&u16(end+10) in 1..limits.size&&u16(end+20)==0)
        val central=n32(end+16);require(central.toLong()+n32(end+12)==end.toLong())
        val members=linkedMapOf<String,Member>();var pos=central;var expanded=0L
        val count=u16(end+10)
        repeat(count){
            require(word(bytes,pos)==0x02014b50L&&pos<=end-46)
            val flags=u16(pos+8);val method=u16(pos+10);val length=u16(pos+28);val extra=u16(pos+30);val comment=u16(pos+32)
            require(flags and 1==0&&method in setOf(0,8)&&u16(pos+34)==0)
            val external=word(bytes,pos+38);val mode=(external ushr 16).toInt() and 0xf000
            require(mode in setOf(0,0x8000)&&external and 0x10L==0L)
            require(pos+46L+length+extra+comment<=end)
            val name=StrictJson.text(bytes.copyOfRange(pos+46,pos+46+length));require(name in limits&&name !in members)
            val size=n32(pos+24);val compressed=n32(pos+20);val offset=n32(pos+42)
            require(size in 1..limits.getValue(name)&&offset<central&&word(bytes,offset)==0x04034b50L)
            expanded+=size;require(expanded<=expandedLimit)
            require(u16(offset+6)==flags&&u16(offset+8)==method)
            val localName=u16(offset+26);val localExtra=u16(offset+28)
            require(localName==length&&offset+30L+localName+localExtra+compressed<=central&&
                bytes.copyOfRange(offset+30,offset+30+localName).contentEquals(name.toByteArray(Charsets.UTF_8)))
            members[name]=Member(size,compressed,word(bytes,pos+16),offset,flags,method)
            pos+=46+length+extra+comment
        }
        require(pos==end&&members.keys.containsAll(required)&&members.values.map{it.offset}.distinct().size==count)
        val result=linkedMapOf<String,ByteArray>()
        ZipInputStream(ByteArrayInputStream(bytes)).use{zip->
            while(true){val entry=zip.nextEntry?:break;val expected=members[entry.name]
                require(expected!=null&&entry.name !in result&&!entry.isDirectory&&result.size<count)
                val out=ByteArrayOutputStream();val buffer=ByteArray(4096);val limit=limits.getValue(entry.name)
                while(true){val count=zip.read(buffer,0,minOf(buffer.size,limit+1-out.size()));if(count<0)break;out.write(buffer,0,count);require(out.size()<=limit)}
                val data=out.toByteArray();require(data.size==expected.size&&CRC32().apply{update(data)}.value==expected.crc&&entry.compressedSize==expected.compressed.toLong())
                result[entry.name]=data;zip.closeEntry()
            }}
        require(result.keys==members.keys);return result
    }
}
