/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_COMMON_RESTORE_CONFIG_GUARD_H
#define VIMAR_COMMON_RESTORE_CONFIG_GUARD_H
#if !defined(CONFIG_VIMAR_COMMON_RESTORE_EXPERIMENTAL) || !defined(CONFIG_SOC_NRF52840) || \
 !defined(CONFIG_ARM) || !defined(CONFIG_ARCH_HAS_RAMFUNC_SUPPORT) || !defined(CONFIG_CODE_DATA_RELOCATION) || \
 !defined(CONFIG_NRF_RTC_TIMER) || !defined(CONFIG_BT) || !defined(CONFIG_BT_PERIPHERAL) || \
 !defined(CONFIG_BT_SMP) || !defined(CONFIG_BT_FIXED_PASSKEY) || !defined(CONFIG_GPIO) || \
 !defined(CONFIG_FLASH) || !defined(CONFIG_PSA_CRYPTO) || !defined(CONFIG_PSA_WANT_ALG_SHA_256) || \
 !defined(CONFIG_MPU_ALLOW_FLASH_WRITE) || CONFIG_BT_MAX_CONN != 1
#error "Common RESTORE requires its explicit isolated nRF52840 authenticated/RAM/crypto configuration"
#endif
#if defined(CONFIG_SETTINGS) || defined(CONFIG_NVS) || defined(CONFIG_BT_SETTINGS) || \
 defined(CONFIG_MCUMGR) || defined(CONFIG_WATCHDOG) || defined(CONFIG_COUNTER_RTC2) || \
 defined(CONFIG_NRFX_RTC2) || defined(CONFIG_UART_CONSOLE) || defined(CONFIG_SHELL) || \
 defined(CONFIG_USB_DEVICE_STACK) || defined(CONFIG_DISABLE_FLASH_PATCH)
#error "Common RESTORE forbids background storage, alternate writers, watchdogs and conflicting RTC2 ownership"
#endif
#endif
