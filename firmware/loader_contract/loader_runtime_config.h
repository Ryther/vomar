/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_LOADER_RUNTIME_CONFIG_H
#define VIMAR_LOADER_RUNTIME_CONFIG_H
#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
#if !defined(CONFIG_SOC_NRF52840) || !defined(CONFIG_VIMAR_OTA_SPLIT_STAGING) || \
 !defined(CONFIG_PSA_WANT_ALG_SHA_256) || !defined(CONFIG_VIMAR_P031_PROTECTION)
#error "Typed loader runtime requires audited nRF52840 split/protection/SHA256 configuration"
#endif
#if CONFIG_MAIN_STACK_SIZE < 12288
#error "Typed loader runtime requires a12KiB main stack for nested pair verification"
#endif
#if defined(CONFIG_MCUMGR_TRANSPORT_BT) && \
 (!defined(CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN) || CONFIG_MCUMGR_TRANSPORT_WORKQUEUE_STACK_SIZE < 8192)
#error "Typed runtime identity requires authenticated Bluetooth and an8KiB SMP stack"
#endif
#if defined(CONFIG_MCUMGR_TRANSPORT_UART) || defined(CONFIG_MCUMGR_TRANSPORT_RAW_UART) || \
 defined(CONFIG_MCUMGR_TRANSPORT_UART_ASYNC) || defined(CONFIG_MCUMGR_TRANSPORT_UDP) || \
 defined(CONFIG_MCUMGR_TRANSPORT_SHELL) || defined(CONFIG_MCUMGR_TRANSPORT_LORAWAN) || \
 defined(CONFIG_MCUMGR_TRANSPORT_DUMMY) || defined(CONFIG_MCUMGR_TRANSPORT_RAW_DUMMY) || \
 defined(CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW) || defined(CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_ENCRYPT)
#error "Typed runtime identity forbids alternate unauthenticated SMP transports and weaker Bluetooth permissions"
#endif
#ifndef VIMAR_LOADER_CONTRACT_BINDINGS_HEADER
#error "Typed runtime requires an explicit finite generated loader-contract header"
#endif
#endif
#endif
