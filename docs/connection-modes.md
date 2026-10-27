# Choose Zigbee pairing or Bluetooth

This connection selector is implemented on the feature branch and needs matching
MAIN, recovery and Android components. It is not a claim that a published package
or installed 1.0.0 firmware supports it. Host checks and native compilation do not
qualify the physical buttons, radio, LED colour order or power-cut behavior.

## Use the wall buttons

1. Hold **both buttons for five seconds**. The status LED alternates **violet and
   green**. This selector stays open for **30 seconds**.
2. Release **both** buttons fully before choosing a mode.
3. Press **Up** to forget the previous Zigbee network and start pairing. The LED
   alternates **blue and violet** for up to **two minutes**. Enable permit join on
   the intended coordinator. Dimmer configuration, light state, Bluetooth bonds
   and original backups are preserved. The old coordinator may retain its device
   entry; changing network does not remove that remote entry.
4. Alternatively, press **Down** for ordinary Bluetooth service. The LED
   alternates **blue and green**. An idle ordinary service returns to validated
   MAIN after 60 seconds; an active transfer or incomplete update prevents exit.

Without a selection, the selector closes after 30 seconds. Selection presses do
not toggle or dim the light. A key held at startup must be released before it can
open the selector. The selector also works in supporting recovery, but cannot
exit an incomplete update or bypass signed-image validation. Exceptional recovery
retains its blue/red indication and does not become an ordinary timed session
merely because Down is pressed. Protection indications have priority over these
colours.

When Zigbee association is confirmed within the window, the LED flashes **yellow
rapidly for three seconds**, then restores the configured LED behavior. This
confirms stack association, not completion of a Zigbee2MQTT interview or successful
lamp operation. Without association, the two-minute window closes and automatic
retry scheduling is stopped. Local lighting continues. Choose pairing again to
start another explicit window.

On first installation, the device starts the same two-minute window automatically.
An uncommissioned device that already used its initial window does not start an
unbounded search after every reboot. A device with a saved network normally
reconnects to that network; only an explicit pairing selection forgets it.

## Start Zigbee pairing from Android Bluetooth

1. Put the dimmer in ordinary Bluetooth service and keep it powered nearby.
2. Open **Devices → device → Zigbee pairing**, then **Inspect for Zigbee pairing**.
   For a device without a saved Bluetooth address, select it in the explicit
   Bluetooth picker. No firmware package is required.
3. Inspection authenticates the connection, checks live identity and reads pairing
   capabilities. Unsupported recovery reports pairing unavailable; there is no
   ordinary-reset fallback. Inspection does not change the network.
4. Enable permit join on the intended coordinator. Tap **Review Zigbee pairing**,
   verify the target and read the warning that the old network will be forgotten.
   Confirm **Start Zigbee pairing** once.
5. The device acknowledges the request before leaving Bluetooth for validated
   MAIN and its two-minute window. Observe blue/violet and, on association, three
   seconds of yellow flashing.

An acknowledgment is acceptance of the request, not proof of Zigbee association.
If the acknowledgment is lost or Stop interrupts submission, the app reports an
uncertain outcome and does not retry automatically. Check the device and obtain
fresh inspection/review before another request. Opening a screen, selecting a
saved device, restarting the app or reading a report never authorizes pairing.
The desktop client does not yet expose this new pairing command.
