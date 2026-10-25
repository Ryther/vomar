package org.openvimar.updater.core

/** Optional purpose-specific command, separate from ordinary MAIN-only reset. */
interface MigrationBootTransport { suspend fun bootMigration(expectedHash:String):ResetAck }
/** Only an authenticated SMP response with global MGMT_ERR_ENOTSUP may create it. */
class MigrationBootCommandUnavailable:Exception("Purpose-specific migration boot command unsupported")
object MigrationBoot {
    suspend fun request(transport:BleTransport,expectedHash:String,sourceRecoveryHash:String?,legacyRecoveryHashes:List<String>):ResetAck {
        require(Regex("[0-9a-f]{64}").matches(expectedHash)){"Invalid expected MIGRATION hash"}
        val explicit=transport as? MigrationBootTransport ?: error("Transport does not implement the purpose-specific migration command")
        return try {explicit.bootMigration(expectedHash)}
        catch(unsupported:MigrationBootCommandUnavailable) {
            require(sourceRecoveryHash!=null&&sourceRecoveryHash in legacyRecoveryHashes){"Ordinary reset fallback is not authorized for this recovery"}
            // A future modern source REC can also appear in a signed migration
            // allowlist. Its presence must not turn MAIN-only reset into a
            // migration purpose. Fresh unsupported identity proves legacy API.
            try {transport.identity();error("Identity-capable recovery cannot use legacy OS reset for MIGRATION")}
            catch(_:IdentityCommandUnavailable) {transport.reset()}
        }
    }
}
