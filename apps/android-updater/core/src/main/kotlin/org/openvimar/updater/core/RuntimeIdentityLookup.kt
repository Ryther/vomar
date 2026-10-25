package org.openvimar.updater.core

/** Never promotes READ0 full48KiB into a common code-family measurement. */
object RuntimeIdentityLookup {
    private val hash=Regex("[0-9a-f]{64}")
    fun validate(identity:RuntimeIdentity) {
        require(identity.model=="VIMAR30805"&&identity.layoutVersion==2&&identity.uid.size==2&&identity.uid.all{Regex("[0-9a-f]{8}").matches(it)}){"Unsupported reported runtime identity"}
        when(identity.protocol) {
            1->require(hash.matches(identity.loaderSha256)&&identity.typedLoader==null&&identity.anchorSha256==null)
            2->{val loader=requireNotNull(identity.typedLoader)
                require(identity.loaderSha256.isEmpty()&&hash.matches(loader.sha256))
                when(loader.kind) {
                    LoaderContract.COMMON->require(identity.anchorSha256?.let(hash::matches)==true){"Common identity requires an anchor measurement"}
                    LoaderContract.LEGACY->require(identity.anchorSha256==null){"Legacy identity cannot claim an anchor"}
                    else->require(false){"Unknown typed loader contract"}
                }
            }
            else->require(false){"Unsupported identity protocol"}
        }
    }
    suspend fun forRelease(transport:BleTransport,manifest:CommonManifest):RuntimeIdentity {
        val observed=if(manifest.schemaVersion==3)try{transport.identityV2().also{require(it.protocol==2){"READ1 must report protocol2"}}}catch(unsupported:IdentityCommandUnavailable){
            require(manifest.loaderContracts.any{it.kind==LoaderContract.LEGACY}){"READ1 is required: this release approves no exact legacy loader"}
            transport.identity().also{require(it.protocol==1){"READ0 must retain protocol1"}}
        }else transport.identity()
        CommonPackageValidator.compatibleIdentity(manifest,observed);return observed
    }
    /** Read-only discovery carries no release compatibility or mutation grant. */
    suspend fun inspect(transport:BleTransport):RuntimeIdentity {
        val result=try{transport.identityV2()}catch(_:IdentityCommandUnavailable){transport.identity()}
        validate(result);return result
    }
}
