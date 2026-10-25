package org.openvimar.updater

internal enum class PrimaryAction { NONE, IMPORT, PERMISSIONS, START, RESUME, CONFIRM_ONLINE, EXPORT }

internal data class UiActions(
    val primary: PrimaryAction = PrimaryAction.NONE,
    val canImport: Boolean = false,
    val canProbe: Boolean = false,
    val canResume: Boolean = false,
    val canConfirm: Boolean = false,
    val canExport: Boolean = false,
    val canStop: Boolean = false,
    val canRequestResumePermission: Boolean = false,
    val canRequestProbePermission: Boolean = false
)

/** Presentation constraints only; backend generation, identity and reset checks remain authoritative. */
internal object UiPolicy {
    fun actions(state: SessionPresentation, permitted: Boolean, bound: Boolean): UiActions {
        if (!bound) return UiActions()
        if (state.busy) return UiActions(canStop = state.operation in listOf(SessionOperation.UPDATE, SessionOperation.PROBE, SessionOperation.IMPORT))
        if (!state.inspected) return UiActions()
        val ready = state.loaded && state.packageSummary != null
        val confirm = ready && state.imagesVerified
        val resume = ready && permitted && state.hasCheckpoint && state.operatorOnline != true
        val export = state.reportAvailable
        val primary = when {
            !ready -> PrimaryAction.IMPORT
            confirm && state.operatorOnline == true -> if (export) PrimaryAction.EXPORT else PrimaryAction.NONE
            confirm -> PrimaryAction.CONFIRM_ONLINE
            !permitted -> PrimaryAction.PERMISSIONS
            resume -> PrimaryAction.RESUME
            else -> PrimaryAction.START
        }
        return UiActions(primary, canImport=true,
            canProbe=ready && permitted && state.operatorOnline != true,
            canResume=resume, canConfirm=confirm, canExport=export,
            canRequestResumePermission=ready && state.imagesVerified && state.hasCheckpoint && !state.resetAcknowledged && state.operatorOnline != true && !permitted,
            canRequestProbePermission=ready && state.imagesVerified && state.operatorOnline == false && !permitted)
    }
}
