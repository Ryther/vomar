package org.openvimar.updater

import java.io.IOException
import java.util.Locale

/** Diagnostic metadata only; acquired blocks are not retained in this error. */
internal class DkBackupChangedException(val region:DkBackupRegion,offset:Int,first:ByteArray,second:ByteArray):
    IOException("${region.name} changed between backup passes at ${address(region.start+offset+firstDifference(first,second))}; no archive is available") {
    init {require(offset>=0 && offset%4==0 && offset.toLong()+first.size<=region.size)}
    val blockAddress=region.start+offset
    val firstChangedAddress=blockAddress+firstDifference(first,second)
    val changedBytesInBlock=first.indices.count {first[it]!=second[it]}
    val firstPassBlockSha256=DkBackupArchive.sha256(first)
    val secondPassBlockSha256=DkBackupArchive.sha256(second)
    companion object {
        private fun firstDifference(first:ByteArray,second:ByteArray):Int {
            require(first.size in 4..512 && first.size==second.size)
            return first.indices.firstOrNull {first[it]!=second[it]} ?: throw IllegalArgumentException("Blocks are identical")
        }
        fun address(value:Long)=String.format(Locale.ROOT,"0x%08x",value)
    }
}

internal interface DkBackupSource {
    val identity: DkBackupIdentity
    fun currentIdentity(): DkBackupIdentity
    fun readBlock(region: DkBackupRegion,offset: Int,length: Int): ByteArray
}
internal data class DkBackupProgress(val pass: Int,val region: DkBackupRegion,val completedBytes: Long,val totalBytes: Long)
internal data class DkBackupCaptured(val identity: DkBackupIdentity,val first: DkBackupPass,val second: DkBackupPass)
internal class DkBackupCollector {
    private val regions=DkBackupRegion.entries.associateWith { ByteArray(it.size) }
    private val next=DkBackupRegion.entries.associateWith { 0 }.toMutableMap()
    fun accept(region: DkBackupRegion,offset: Int,bytes: ByteArray) {
        if(offset!=next.getValue(region) || offset%4!=0 || bytes.size !in 4..512 || bytes.size%4!=0 ||
            offset.toLong()+bytes.size>region.size || offset%1024+bytes.size>1024)
            throw IOException("Backup block is duplicated, missing, misaligned or outside its region")
        bytes.copyInto(regions.getValue(region),offset)
        next[region]=offset+bytes.size
    }
    fun finish(before: DkBackupIdentity,after: DkBackupIdentity): DkBackupPass {
        if(next.any { (region,offset) -> offset!=region.size }) throw IOException("Backup pass is incomplete")
        if(before!=after) throw IOException("Target identity changed during backup")
        return DkBackupPass(before,after,regions.mapValues { it.value.copyOf() })
    }
}
internal object DkBackupCapture {
    fun read(source: DkBackupSource,cancelled: () -> Boolean = {false},progress: (DkBackupProgress)->Unit = {}): DkBackupCaptured {
        fun checkCancelled() { if(cancelled()) throw IOException("Backup cancelled; no partial archive is available") }
        val total=2L*DkBackupRegion.entries.sumOf { it.size }
        var completed=0L
        val passes=mutableListOf<DkBackupPass>()
        repeat(2) { pass ->
            checkCancelled()
            val before=source.currentIdentity()
            if(before!=source.identity) throw IOException("Target identity changed before backup")
            val collector=DkBackupCollector()
            for(region in DkBackupRegion.entries) {
                var offset=0
                while(offset<region.size) {
                    checkCancelled()
                    val length=minOf(512,region.size-offset,1024-offset%1024)
                    val block=source.readBlock(region,offset,length)
                    checkCancelled()
                    if(pass==1) {
                        val first=passes[0].regions.getValue(region).copyOfRange(offset,offset+length)
                        if(block.size==length && !block.contentEquals(first))
                            throw DkBackupChangedException(region,offset,first,block)
                    }
                    collector.accept(region,offset,block)
                    offset+=length;completed+=length
                    progress(DkBackupProgress(pass+1,region,completed,total))
                }
            }
            checkCancelled()
            val after=source.currentIdentity()
            if(after!=source.identity) throw IOException("Target identity changed after backup")
            passes+=collector.finish(before,after)
        }
        checkCancelled()
        return DkBackupCaptured(source.identity,passes[0],passes[1])
    }
}
