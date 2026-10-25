/* SPDX-License-Identifier: Apache-2.0 */
#ifndef VIMAR_COMMON_RESTORE_RAM_H
#define VIMAR_COMMON_RESTORE_RAM_H
#ifdef COMMON_RESTORE_HOST
#define COMMON_RESTORE_RAM
#else
#include <zephyr/toolchain.h>
#define COMMON_RESTORE_RAM __ramfunc
#endif
#endif
