package org.openvimar.updater

import java.io.IOException

internal interface DkBulkChannel {
    fun write(bytes: ByteArray): Int
    fun read(maxBytes: Int): ByteArray
}

internal data class DkProbeResult(val firmware: String, val targetMillivolts: Int)

/** Protocol observations only: firmware version and hardware status. No target
 * interface selection, pin writes, target power, SWD, reset or flash commands.
 * Reference: libjaylink device.c, CMD_GET_VERSION and CMD_GET_HW_STATUS.
 */
internal object DkJlinkReadOnly {
    fun probe(channel: DkBulkChannel): DkProbeResult {
        fun command(value: Int) {
            if (channel.write(byteArrayOf(value.toByte())) != 1)
                throw IOException("J-Link USB command was not accepted")
        }
        fun readExact(size: Int): ByteArray {
            val result = ByteArray(size)
            var offset = 0
            while (offset < size) {
                val part = channel.read(size - offset)
                if (part.isEmpty() || part.size > size - offset)
                    throw IOException("J-Link USB reply was incomplete")
                part.copyInto(result, offset)
                offset += part.size
            }
            return result
        }
        fun u16(bytes: ByteArray) = (bytes[0].toInt() and 255) or
            ((bytes[1].toInt() and 255) shl 8)

        command(0x01)
        val length = u16(readExact(2))
        if (length > 1024) throw IOException("Unexpected J-Link version length: $length")
        val firmware = if (length == 0) "Not reported" else
            readExact(length).toString(Charsets.UTF_8).trimEnd('\u0000', '\n', '\r')
                .map { if (it.isISOControl()) ' ' else it }.joinToString("")
        command(0x07)
        val status = readExact(8)
        return DkProbeResult(firmware, u16(status))
    }
}
