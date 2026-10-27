# Vomar interface system

Desktop extends the existing Android identity: anthracite #1B1E22, panel #252A30,
text #F0EEE9, secondary #BFC3C6, orange action #FFA15A with #331806 text, teal
#72C6BE. Light uses ivory #FAF8F3, panel #EFEEE8, text #25282C, secondary #565E65,
action #A64412 and #FFF8F2 button text. Status always includes words.

Use native system sans, 16 px body and 24 px destination titles; hash/address
values alone may use fixed-width type. Resizable device and activity rows provide
selection, full accessible names and keyboard actions. Minimum action height is
40 px on desktop; focus has a visible two-pixel outline. Long content scrolls.

Devices, Activity and Settings remain visible while an owned worker performs I/O.
Status and Stop remain visible. Tools sit under Settings. Confirmation interrupts
only to review a specific mutation; ordinary navigation and settings use inline
panels. Errors preserve entered values and name the next action. Transfer,
requested restart, verified readback and observed device return are distinct.

The inherited palette is established; the desktop rail/row composition is an
implementation assumption while the user is unavailable, not a new user approval.

The supplied Vomar concept 01 artwork lives in `assets/branding`; its manifest
pins the original image bytes. Use the banner in the README and documentation
home, the symbol in system icons, Settings app information on Android and the
desktop header. In-app symbols use a compact ivory #FAF8F3 backplate in either
theme. Preserve operational headings and visible status/Stop controls. Never
recolor or stretch the raster artwork. See the branding README for synchronization
and platform packaging.
