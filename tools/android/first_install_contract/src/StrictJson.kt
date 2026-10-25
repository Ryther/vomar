package org.openvimar.installer

import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction

/** Bounded integer-only JSON subset. Duplicate keys and malformed UTF8 fail. */
internal object StrictJson {
    fun text(bytes:ByteArray):String=Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
        .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(bytes)).toString()
    fun parse(bytes:ByteArray):Any? {
        require(bytes.size in 1..65536)
        val r=Reader(text(bytes));val value=r.value(0);r.space();require(r.atEnd()){ "Trailing JSON" };return value
    }
    fun canonical(value:Any?):String=when(value) {
        null->"null"
        is Boolean,is Long->value.toString()
        is String->"\""+buildString{value.forEach{c->append(when(c){
            '"'->"\\\"";'\\'->"\\\\";'\b'->"\\b";'\u000c'->"\\f";'\n'->"\\n";'\r'->"\\r";'\t'->"\\t"
            else->if(c.code<32||c.code>=127)"\\u%04x".format(c.code) else c.toString()
        })}}+"\""
        is List<*>->value.joinToString(",","[","]"){canonical(it)}
        is Map<*,*>->value.entries.sortedBy{it.key as String}.joinToString(",","{","}"){canonical(it.key)+":"+canonical(it.value)}
        else->error("Unsupported canonical JSON type")
    }
    private class Reader(private val s:String) {
        private var p=0
        fun atEnd()=p==s.length
        fun space(){while(p<s.length&&s[p] in " \n\r\t")p++}
        private fun ch():Char {require(p<s.length){"Truncated JSON"};return s[p++]}
        private fun expect(c:Char){space();require(ch()==c){"Invalid JSON delimiter"}}
        fun value(depth:Int):Any? {
            require(depth<=8){"JSON nesting too deep"};space();require(p<s.length)
            return when(s[p]) {
                '{'->{p++;space();val result=linkedMapOf<String,Any?>()
                    if(p<s.length&&s[p]=='}'){p++;result}else{
                        while(true){require(result.size<32);space();val key=string();require(key !in result){"Duplicate JSON key"};expect(':');result[key]=value(depth+1)
                            space();when(ch()){'}'->break;','->Unit;else->error("Invalid JSON object")}}
                        result}}
                '['->{p++;space();val result=mutableListOf<Any?>()
                    if(p<s.length&&s[p]==']'){p++;result}else{
                        while(true){require(result.size<64);result+=value(depth+1);space();when(ch()){']'->break;','->Unit;else->error("Invalid JSON array")}}
                        result}}
                '"'->string()
                't'->{literal("true");true};'f'->{literal("false");false};'n'->{literal("null");null}
                else->{val start=p;if(s[p]=='-')p++;require(p<s.length&&s[p].isDigit());if(s[p]=='0')p++ else {require(s[p] in '1'..'9');while(p<s.length&&s[p] in '0'..'9')p++}
                    require(p-start<=20);s.substring(start,p).toLong()}
            }
        }
        private fun literal(word:String){require(s.startsWith(word,p));p+=word.length}
        private fun string():String {
            require(ch()=='"');val out=StringBuilder()
            while(true){val c=ch();if(c=='"')break;require(c.code>=32)
                if(c!='\\')out.append(c)else out.append(when(val e=ch()){
                    '"','\\','/'->e;'b'->'\b';'f'->'\u000c';'n'->'\n';'r'->'\r';'t'->'\t'
                    'u'->{require(p<=s.length-4);val v=s.substring(p,p+4).toInt(16).toChar();p+=4;v}
                    else->error("Invalid JSON escape")})
                require(out.length<=4096)}
            var i=0;while(i<out.length){val c=out[i++];if(c.isHighSurrogate()){require(i<out.length&&out[i++].isLowSurrogate())}else require(!c.isLowSurrogate())}
            return out.toString()
        }
    }
}
@Suppress("UNCHECKED_CAST") internal fun obj(value:Any?):Map<String,Any?> {
    require(value is Map<*,*>);return value as Map<String,Any?>
}
internal fun exact(value:Any?,expected:Map<String,Any?>) {require(obj(value)==expected){"Unexpected JSON contract values"}}
internal fun keys(value:Any?,names:Set<String>):Map<String,Any?> = obj(value).also{require(it.keys==names){"Unexpected JSON fields"}}
