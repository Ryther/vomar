package org.openvimar.updater.installer

/** Read-only private evidence summary for a freshly inspected live UID. No
 * field restores an approval, USB lease, or execution permission. */
internal data class InitialInstallResumeOption(val bindingId:String,val releaseSha256:String,val archiveSha256:String,
    val initialExportDocument:String,val originalAvailable:Boolean,val journalHeadSha256:String,
    val frontierPage:Int,val commitPossible:Boolean,val classification:String)
internal data class ResumeOwnerReview(val requestId:String,val bindingId:String,val reviewedReleaseSha256:String,val journalHeadSha256:String)
