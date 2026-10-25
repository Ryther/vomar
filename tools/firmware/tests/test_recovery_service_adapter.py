"""Real recovery adapter callbacks with deterministic host IO.

The C harness includes the production adapter to exercise its private callbacks;
the session, command gate, gesture, and LED policy are compiled unchanged.
Scheduler/locks are deterministic, not a threaded Zephyr simulation. Signature
verification and protection flushing are injected IO decisions: their own tests
cover their implementations.
"""
from local_inputs import local_input, sdk_root
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]

STUBS = {
    "zephyr/kernel.h": r"""
#ifndef TEST_KERNEL_H
#define TEST_KERNEL_H
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#define ARG_UNUSED(x) ((void)(x))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define BIT(n) (1u<<(n))
#define K_FOREVER (-1)
#define K_MSEC(n) (n)
#define K_THREAD_STACK_DEFINE(n,s) char n[s]
#define K_THREAD_STACK_SIZEOF(n) sizeof(n)
struct k_mutex {unsigned depth;};
#define K_MUTEX_DEFINE(n) struct k_mutex n
struct k_work {void (*handler)(struct k_work *);};
struct k_work_q {int unused;};
struct k_work_delayable {struct k_work work;};
extern uint64_t fake_now;
extern struct k_work *queued_exit;
static inline int k_mutex_lock(struct k_mutex *m,int t){(void)t;assert(!m->depth);m->depth++;return 0;}
static inline void k_mutex_unlock(struct k_mutex *m){assert(m->depth==1);m->depth--;}
static inline int64_t k_uptime_get(void){return (int64_t)fake_now;}
static inline uint32_t k_uptime_get_32(void){return (uint32_t)fake_now;}
static inline void k_work_init(struct k_work *w,void (*h)(struct k_work *)){w->handler=h;}
static inline void k_work_init_delayable(struct k_work_delayable *w,void (*h)(struct k_work *)){w->work.handler=h;}
static inline void k_work_queue_start(struct k_work_q *q,void *s,size_t n,int p,void *c){(void)q;(void)s;(void)n;(void)p;(void)c;}
static inline int k_work_submit_to_queue(struct k_work_q *q,struct k_work *w){(void)q;queued_exit=w;return 0;}
static inline int k_work_schedule(struct k_work_delayable *w,int t){(void)w;(void)t;return 0;}
static inline int k_work_reschedule(struct k_work_delayable *w,int t){(void)w;(void)t;return 0;}
#endif
""",
    "zephyr/drivers/gpio.h": r"""
#ifndef TEST_GPIO_H
#define TEST_GPIO_H
#include <stdbool.h>
#define DT_ALIAS(n) 0
#define GPIO_DT_SPEC_GET(n,p) {0}
#define GPIO_INPUT 0
struct gpio_dt_spec {int unused;};
static inline bool gpio_is_ready_dt(const struct gpio_dt_spec *p){(void)p;return true;}
static inline int gpio_pin_configure_dt(const struct gpio_dt_spec *p,int f){(void)p;(void)f;return 0;}
static inline int gpio_pin_get_dt(const struct gpio_dt_spec *p){(void)p;return 0;}
#endif
""",
    "zephyr/logging/log.h": r"""
#define LOG_MODULE_REGISTER(...)
#define LOG_WRN(...) ((void)0)
#define LOG_ERR(...) ((void)0)
""",
    "zephyr/mgmt/mcumgr/mgmt/callbacks.h": r"""
#ifndef TEST_CALLBACKS_H
#define TEST_CALLBACKS_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
enum mgmt_cb_return {MGMT_CB_OK,MGMT_CB_ERROR_RC};
typedef enum mgmt_cb_return (*mgmt_cb)(uint32_t,enum mgmt_cb_return,int32_t *,uint16_t *,bool *,void *,size_t);
struct mgmt_callback {mgmt_cb callback;uint32_t event_id;};
struct mgmt_evt_op_cmd_arg {uint16_t group;uint8_t id;union {uint8_t op;int err;int status;};};
#define MGMT_EVT_OP_CMD_RECV (1u<<0)
#define MGMT_EVT_OP_CMD_DONE (1u<<1)
#define MGMT_EVT_OP_IMG_MGMT_DFU_STARTED (1u<<2)
#define MGMT_EVT_OP_IMG_MGMT_DFU_STOPPED (1u<<3)
#define MGMT_EVT_OP_IMG_MGMT_DFU_PENDING (1u<<4)
#define MGMT_OP_READ 0
#define MGMT_OP_WRITE 2
#define MGMT_GROUP_ID_IMAGE 1
#define MGMT_ERR_EBUSY 10
#define MGMT_ERR_EINVAL 3
static inline void mgmt_callback_register(struct mgmt_callback *c){(void)c;}
#endif
""",
    "zephyr/mgmt/mcumgr/grp/img_mgmt/img_mgmt.h": r"""
#define IMG_MGMT_ID_UPLOAD 1
#define IMG_MGMT_ID_ERASE 5
""",
    "mgmt/mcumgr/grp/img_mgmt/img_mgmt_priv.h": r"""
void img_mgmt_take_lock(void);
void img_mgmt_release_lock(void);
""",
    "zephyr/retention/bootmode.h": "int bootmode_clear(void);\n",
    "zephyr/settings/settings.h": r"""
#include <stddef.h>
#include <sys/types.h>
ssize_t settings_load_one(const char *,void *,size_t);
int settings_save_one(const char *,const void *,size_t);
int settings_delete(const char *);
""",
    "zephyr/sys/reboot.h": "#define SYS_REBOOT_COLD 0\nvoid sys_reboot(int);\n",
}


@pytest.fixture(scope="module")
def adapter(tmp_path_factory):
    directory = tmp_path_factory.mktemp("recovery_service_adapter")
    for name, source in STUBS.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source)
    executable = directory / "adapter"
    subprocess.run([
        "cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-fsanitize=undefined",
        "-DCONFIG_VIMAR_RECOVERY_SERVICE_MODE=1", "-DCONFIG_VIMAR_P031_PROTECTION=1",
        "-DCONFIG_VIMAR_RECOVERY_MIGRATION_EXEC=1", "-DCONFIG_VIMAR_RECOVERY_BUTTON_EXIT=1",
        "-DCONFIG_MCUMGR_TRANSPORT_BT=1", "-DCONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN=1",
        "-DCONFIG_MCUMGR_SMP_COMMAND_STATUS_HOOKS=1", "-DCONFIG_MCUMGR_GRP_IMG_MUTEX=1",
        "-DCONFIG_VIMAR_OTA_INSTALLER=1", "-DCONFIG_MCUMGR_MGMT_NOTIFICATION_HOOKS=1",
        "-DCONFIG_MCUMGR_GRP_IMG_STATUS_HOOKS=1", "-DCONFIG_MCUMGR_GRP_OS_RESET_HOOK=1",
        "-I", str(local_input(sdk_root() / 'modules/lib/zcbor/include')),
        "-I", str(directory), "-I", str(ROOT / "firmware/recovery/src"),
        "-I", str(ROOT / "firmware/src"),
        str(Path(__file__).with_name("recovery_service_adapter_test.c")),
        str(ROOT / "firmware/recovery/src/recovery_session.c"),
        str(ROOT / "firmware/recovery/src/recovery_exit.c"),
        str(ROOT / "firmware/recovery/src/recovery_exit_control.c"),
        str(ROOT / "firmware/src/wireless_status_led.c"),
        "-o", str(executable),
    ], check=True)
    return executable


@pytest.mark.parametrize("scenario", [
    "disconnect", "stopped_retry", "early_error_retry", "stale_timeout",
    "partial_gate", "invalid_main_gate", "history_activity",
    "migration_upload", "migration_ack", "migration_output_error", "migration_disconnect",
    "migration_recheck", "migration_preflight", "sdk_reset", "sdk_reset_migration",
    "sdk_reset_partial", "sdk_reset_fault",
    "admission_store_failure",
])
def test_real_recovery_adapter_callbacks(adapter, scenario):
    subprocess.run([str(adapter), scenario], check=True)
