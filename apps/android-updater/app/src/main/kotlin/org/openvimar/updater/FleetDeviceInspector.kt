package org.openvimar.updater

import kotlinx.coroutines.*
import org.openvimar.updater.core.*

/** Reported custom identity and installed-slot version, never a model attestation. */
internal class FleetDeviceInspector(private val transportFactory:(String)->BleTransport,
    private val now:()->Long={System.currentTimeMillis()}) {
    suspend fun inspect(record:DeviceRecord,checkSubmission:()->Unit={}):DeviceRecord {
        val address=requireNotNull(record.address){"Select this device's Bluetooth address first"}
        val transport=transportFactory(address)
        try {
            currentCoroutineContext().ensureActive();checkSubmission();transport.connect(address)
            currentCoroutineContext().ensureActive();checkSubmission();val identity=RuntimeIdentityLookup.inspect(transport)
            require(record.uid.isEmpty()||record.uid==identity.uid){"Connected runtime UID differs from the selected device"}
            currentCoroutineContext().ensureActive();checkSubmission();val images=transport.images()
            currentCoroutineContext().ensureActive();checkSubmission();require(RuntimeIdentityLookup.inspect(transport)==identity){"Runtime identity changed during inspection"}
            val main=requireNotNull(images.primary){"No installed primary image was reported"}
            require(main.bootable&&main.hash!=null){"Installed primary image is not bootable"}
            val version=main.version?.takeIf{it.length<=128&&Regex("[0-9]+\\.[0-9]+\\.[0-9]+(?:[+.][0-9]+)?").matches(it)} ?: error("Installed image version was not reported in a recognised format")
            return record.copy(uid=identity.uid.toList(),installedVersion=version,firmwareKind=FirmwareKind.CUSTOM,
                observedAt=now(),observationSource="authenticated BLE reported identity and SMP image version; not hardware attestation",
                capabilities=record.capabilities+"ble_update")
        } finally {withContext(NonCancellable){transport.close()}}
    }
}
