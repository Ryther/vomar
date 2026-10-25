package org.openvimar.updater

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.bluetooth.BluetoothManager
import android.bluetooth.le.*
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.ParcelUuid
import android.widget.*

/** Discovery is a hint only. The service queries authenticated runtime identity
 * after selection; no advertised name/address authorises a firmware write. */
internal class BluetoothCandidatePicker(private val activity: Activity) {
    private val handler = Handler(Looper.getMainLooper())
    private var dialog: AlertDialog? = null
    private var stopScan: (() -> Unit)? = null
    private val project = ParcelUuid.fromString("7b2f3080-5c91-4a6d-9f22-4e8c6d300805")
    private val smp = ParcelUuid.fromString("8d53dc1d-1db7-4cd3-868b-8a527460aa84")

    @SuppressLint("MissingPermission") // Checked before scan; revocation races are handled below.
    fun show(allowLegacy:Boolean=false,onSelected: (String) -> Unit) {
        close()
        if (PermissionPolicy.required(Build.VERSION.SDK_INT).any {
                activity.checkSelfPermission(it) != PackageManager.PERMISSION_GRANTED }) {
            message("Allow Bluetooth access before searching."); return
        }
        val adapter = activity.getSystemService(BluetoothManager::class.java)?.adapter
        if (adapter == null || !adapter.isEnabled) {
            message("Turn on Bluetooth in Android, then search again."); return
        }
        val scanner = adapter.bluetoothLeScanner ?: run { message("Bluetooth scanning is unavailable."); return }
        val rows = linkedMapOf<String, String>()
        val list = ListView(activity)
        val labels = ArrayAdapter<String>(activity, android.R.layout.simple_list_item_1)
        list.adapter = labels
        val status = TextView(activity).apply {
            text = "Searching nearby custom-firmware dimmers…"; setPadding(24, 20, 24, 20)
            accessibilityLiveRegion = android.view.View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        val body = LinearLayout(activity).apply { orientation = LinearLayout.VERTICAL; addView(status); addView(list) }
        val shown = AlertDialog.Builder(activity).setTitle("Choose Bluetooth dimmer")
            .setView(body).setNegativeButton("Cancel", null).create()
        dialog = shown
        var scanning = true
        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                activity.runOnUiThread {
                    val services=result.scanRecord?.serviceUuids ?: emptyList()
                    val projectClaim=project in services
                    if (dialog !== shown || !scanning || (!projectClaim&&!(allowLegacy&&smp in services))) return@runOnUiThread
                    val address = result.device.address
                    if (!rows.containsKey(address) && rows.size >= 32) return@runOnUiThread
                    val name = result.scanRecord?.deviceName?.takeIf { it.isNotBlank() } ?: "Vimar 30805"
                    rows[address] = "$name\n$address · ${result.rssi} dBm"+
                        if(projectClaim) "" else "\nLegacy recovery candidate · compatibility not yet checked"
                    labels.clear(); labels.addAll(rows.values); labels.notifyDataSetChanged()
                    status.text = "Select a dimmer to verify its live identity. No firmware is sent by this search."
                }
            }
            override fun onScanFailed(errorCode: Int) {
                activity.runOnUiThread {
                    if (dialog === shown) { stopScan?.invoke(); status.text = "Bluetooth search failed ($errorCode). Close and retry." }
                }
            }
        }
        val timeout = Runnable {
            if (dialog === shown) {
                stopScan?.invoke()
                status.text = if (rows.isEmpty()) "No compatible dimmer found. Enable its Bluetooth mode and search again. Older recovery firmware may need migration first."
                    else "Search finished. Select a dimmer to verify its identity."
            }
        }
        stopScan = {
            if (scanning) {
                scanning = false
                try { scanner.stopScan(callback) } catch (_: SecurityException) { /* Permission revoked. */ }
                handler.removeCallbacks(timeout)
            }
        }
        shown.setOnDismissListener { if (dialog === shown) { stopScan?.invoke(); stopScan = null; dialog = null } }
        list.setOnItemClickListener { _, _, position, _ ->
            rows.keys.elementAtOrNull(position)?.let { address -> close(); onSelected(address) }
        }
        shown.show()
        try {
            val filters=mutableListOf(ScanFilter.Builder().setServiceUuid(project).build())
            if(allowLegacy)filters+=ScanFilter.Builder().setServiceUuid(smp).build()
            scanner.startScan(filters,
                ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), callback)
            handler.postDelayed(timeout, 20000)
        } catch (failure: Exception) {
            stopScan?.invoke(); status.text = "Bluetooth search could not start: ${failure.message}"
        }
    }
    fun close() { stopScan?.invoke(); stopScan = null; dialog?.dismiss(); dialog = null }
    private fun message(value: String) { AlertDialog.Builder(activity).setMessage(value).setPositiveButton("Close", null).show() }
}
