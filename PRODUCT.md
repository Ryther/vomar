# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

## Users and purpose

Vomar helps owners of compatible Vimar 30805 dimmers install and manage project
firmware from Android, Linux, macOS and Windows. Device names and rooms are
optional organization. Signed package validation, authenticated live identity and
fresh review govern each device operation.

## Stack

nRF52840 firmware, a native Android application and a desktop Python engine
shared by Qt Widgets and CLI. End users install native packages without an SDK.

## Constraints

Source implementation, software checks, signing, publication and physical
qualification are separate claims. Use the exact release manifest and acceptance
record for shipped versions and limitations; use native version owners for a
checkout. APS-105-5241 remains unresolved in this source.

First installation requires a reviewed HALT, two equal original captures,
verified archive save/reopen, bounded FLASH writes and anchor commit last.
Verified installation ends halted; starting the new firmware requires separate
review. Android performs the required save/reopen in private app storage;
desktop requires explicit export/reopen. Export Android originals externally
before uninstalling or clearing app data. Ordinary app installation, scanning
and package import grant no device-write authority.

Keep originals, journals, credentials, household data and signing keys private.
A completed transfer or acknowledged start does not prove working lights, radio,
electrical protection or power-cut recovery.

## Established interface

Devices, Activity and Settings share the Android vocabulary and the anthracite,
orange and teal identity. English is the source language; names and rooms remain
user data. Native keyboard, accessibility, readable identity, progress and Stop
controls must remain usable at supported sizes and text scales. See
[the interface system](DESIGN.md) and [UX evidence](docs/ux-evidence.md).

## Qualification work

Native BLE/USB, platform permissions and drivers, interruption recovery and
physical firmware behavior need evidence for the exact artifact and target.
Pending checks remain visible; earlier trials cannot qualify later images.
