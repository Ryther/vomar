package org.openvimar.installer.resume

import org.openvimar.installer.*

/** Historical proof of the initial successful same-document export/reopen.
 * Metadata only; neither parsing nor possession grants execution authority. */
class OriginalExportReceipt private constructor(val bindingId:String,val archiveSha256:String,val document:String) {
    fun encode():ByteArray=(StrictJson.canonical(mapOf("schemaVersion" to 1L,"bindingId" to bindingId,
        "archiveSha256" to archiveSha256,"document" to document))+"\n").toByteArray(Charsets.UTF_8)
    val sha256 get()=sha256(encode())
    companion object {
        fun fromVerifiedExport(original:OriginalMaterial,binding:InstallBinding):OriginalExportReceipt {
            require(binding.archiveSha256==original.archiveSha256&&binding.target==original.identity&&
                binding.anchorSha256==sha256(original.anchor())&&binding.tableSha256==sha256(original.table()))
            return checked(binding.id,original.archiveSha256,original.document)
        }
        private fun checked(binding:String,archive:String,document:String):OriginalExportReceipt {
            require(Regex("[0-9a-f]{64}").matches(binding)&&Regex("[0-9a-f]{64}").matches(archive)&&document.isNotBlank()&&document.length<=4096)
            return OriginalExportReceipt(binding,archive,document)
        }
        fun parse(bytes:ByteArray):OriginalExportReceipt {
            require(bytes.size in 1..32768)
            val m=keys(StrictJson.parse(bytes),setOf("schemaVersion","bindingId","archiveSha256","document"))
            require(m["schemaVersion"]==1L)
            val receipt=checked(m["bindingId"] as String,m["archiveSha256"] as String,m["document"] as String)
            require(receipt.encode().contentEquals(bytes)){"Noncanonical initial export receipt"};return receipt
        }
    }
}

class ReopenedResumeOriginal internal constructor(internal val material:OriginalMaterial,
    val initialReceipt:OriginalExportReceipt,val selectedDocument:String) {
    val identity get()=material.identity
    val archiveSha256 get()=material.archiveSha256
    /** Immutable original material derived only after the initial receipt and
     * fresh exact-copy reopen checks. It does not grant a hardware lease. */
    fun materialForPlan():OriginalMaterial=material
}

object ResumeOriginal {
    /** A cloud-moved copy may have a different URI; it must be the byte-exact
     * complete ZIP from the immutable initial receipt AND private original.
     * No create/export callback exists and no partial backup can be promoted. */
    fun reopen(protectedOriginal:VerifiedOriginal,initialReceipt:OriginalExportReceipt,selectedDocument:String,
        readExisting:(String)->ByteArray):ReopenedResumeOriginal {
        require(selectedDocument.isNotBlank()&&selectedDocument.length<=4096)
        require(protectedOriginal.archiveSha256==initialReceipt.archiveSha256){"Protected original differs from initial export receipt"}
        val selected=readExisting(selectedDocument).copyOf();require(selected.size in 22..OriginalArchive.MAX_ZIP)
        require(selected.contentEquals(protectedOriginal.archive())&&sha256(selected)==initialReceipt.archiveSha256){"Selected original is not the exact initially exported ZIP"}
        val reopened=OriginalArchive.verify(selected)
        require(reopened.identity==protectedOriginal.identity)
        return ReopenedResumeOriginal(ExportedOriginal(reopened,selectedDocument).deriveOriginal(),initialReceipt,selectedDocument)
    }
}
