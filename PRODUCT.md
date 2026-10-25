# Product

<!-- impeccable:product-schema 1 -->

## Platform

adaptive

## Users and purpose

Vomar helps owners of compatible Vimar 30805 dimmers install and manage the
project firmware from Android, Linux, macOS and Windows. Device organization is
optional. A signed package, authenticated live identity and operation-specific
review govern updates. A radio name or saved room never grants permission.

## Stack

Existing nRF52840 firmware and native Android application; desktop Python engine
shared by Qt Widgets and CLI, packaged natively with no end-user SDK requirement.

## Constraints

Physical qualification is separate from software checks. Current firmware 1.0.0
is a qualification candidate with thirteen physical checks false. A completed
transfer or acknowledged start does not establish working lights or radio.
First installation preserves a double-read original, exact export/reopen and
UICR, commits the anchor last, and ends halted before a separately reviewed start.
Private originals, account state, household data and signer keys stay out of OSS.

## Established interface

Devices, Activity and Settings retain the existing Android vocabulary and the
approved anthracite, orange and teal identity. English is the source language;
user names and rooms remain user data. Native keyboard and accessibility behavior
matter more than decoration. The desktop extends this established product.

## Open decisions

The user requested unattended implementation and deferred questions. Desktop
layout uses native resizable rows and a persistent navigation rail, inferred
from the approved three-destination plan and existing Android design. Native
BLE/USB behavior and physical firmware operation require separate qualification.
