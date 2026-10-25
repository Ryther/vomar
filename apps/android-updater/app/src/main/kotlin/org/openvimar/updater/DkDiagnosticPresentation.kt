package org.openvimar.updater

/** Optional report sections are decoded by the Activity without required JSON casts. */
internal data class DkDiagnosticReportView(val type: String,val raw: String,val success: Boolean?=null,
    val probeFirmware: String?=null,val targetVoltage: String?=null,val targetChip: String?=null,val uid: String?=null,
    val backupPhase: String?=null,val backupOutcome: String?=null,val backupMessage: String?=null,val error: String?=null)

internal object DkDiagnosticPresentation {
    fun format(report: DkDiagnosticReportView): String {
        if(report.type=="dk-backup-request") {
            val heading=report.backupMessage ?: when(report.success) {
                true->"Verified backup ready to save"
                false->"Backup did not complete"
                null->"Backup pending"
            }
            return buildString {
                append(heading)
                report.backupPhase?.let {append("\nPhase: ").append(it)}
                report.backupOutcome?.let {append("\nOutcome: ").append(it)}
                report.error?.takeIf {it!=heading}?.let {append("\n").append(it)}
                append("\n\n").append(report.raw)
            }
        }
        if(report.success!=true || report.probeFirmware==null && report.targetVoltage==null)return report.raw
        val conclusion=when(report.type) {
            "dk-swd-read-only"->{
                if(report.targetChip==null || report.uid==null)return report.raw
                "Target chip: ${report.targetChip}\nFICR UID: ${report.uid}\n\nThe chip may be on the DK or an attached board. FICR identifies the silicon; it does not confirm a Vimar commercial model. No backup was made."
            }
            "dk-usb-read-only"->"USB communication verified. This does not establish an SWD connection or identify a connected Vimar."
            else->return report.raw
        }
        return "J-Link: ${report.probeFirmware ?: "Not reported"}\nReference voltage: ${report.targetVoltage ?: "Not reported"}\n\n$conclusion\n\n${report.raw}"
    }
}
