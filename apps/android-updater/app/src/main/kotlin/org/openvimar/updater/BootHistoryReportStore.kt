package org.openvimar.updater

import org.openvimar.updater.core.*
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

/** App-private parsed metadata. A failed new attempt replaces the previous success. */
internal class BootHistoryReportStore(directory:File) {
 private val report=File(directory,"diagnostics/recovery-boot-history.json")
 private val selection=File(directory,"diagnostics/recovery-boot-history.selected")
 private fun hash(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString(""){"%02x".format(it.toInt() and 255)}
 private fun write(file:File,bytes:ByteArray) {
  check(file.parentFile!!.mkdirs()||file.parentFile!!.isDirectory)
  val temporary=File(file.path+".tmp")
  temporary.outputStream().use{it.write(bytes);it.fd.sync()}
  Files.move(temporary.toPath(),file.toPath(),StandardCopyOption.ATOMIC_MOVE,StandardCopyOption.REPLACE_EXISTING)
 }
 @Synchronized fun save(value:BootHistoryDiagnosticReport) {
  val bytes=BootHistoryReports.encode(value)
  if(value.state!=BootHistoryReadState.READING)check(latest()?.attemptId==value.attemptId){"A newer diagnostic owns the report"}
  write(report,bytes);write(selection,hash(bytes).toByteArray(Charsets.US_ASCII))
  check(latest()==value){"Boot-history report could not be verified after saving"}
 }
 @Synchronized fun latest():BootHistoryDiagnosticReport? {
  if(!report.exists())return null
  require(report.length() in 1..BootHistoryReports.MAX_BYTES.toLong())
  return BootHistoryReports.decode(report.readBytes())
 }
 @Synchronized fun selectedBytes():ByteArray? {
  if(!selection.exists())return null
  require(selection.length()==64L&&report.length() in 1..BootHistoryReports.MAX_BYTES.toLong())
  val bytes=report.readBytes();require(hash(bytes)==selection.readText(Charsets.US_ASCII)){"Boot-history report selection is stale"}
  BootHistoryReports.decode(bytes);return bytes.copyOf()
 }
 @Synchronized fun selectedFile():File? {selectedBytes() ?: return null;return report}
 @Synchronized fun deselect(){check(!selection.exists()||selection.delete()){"Diagnostic report selection could not be cleared"}}
}
