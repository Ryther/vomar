#ifndef OTA_TRANSPORT_FAKE_H
#define OTA_TRANSPORT_FAKE_H
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
typedef uint8_t zb_uint8_t;
typedef uint8_t zb_bufid_t;
typedef int zb_zcl_attr_t;
typedef struct {uint8_t upgrade_server[8];uint32_t file_offset,file_version,downloaded_file_ver,image_stamp;uint16_t stack_version,downloaded_stack_ver,manufacturer,image_type,min_block_reque,server_addr;uint8_t image_status,server_ep;} zb_zcl_ota_upgrade_attrs_t;
typedef struct {uint8_t upgrade_status;union {struct{uint16_t manufacturer,image_type;uint32_t file_version,file_length;} start;struct{uint32_t file_offset;uint8_t data_length;const uint8_t *block_data;} receive;} upgrade;} zb_zcl_ota_upgrade_value_param_t;
typedef struct {int status;struct{zb_zcl_ota_upgrade_value_param_t ota_value_param;}cb_param;} zb_zcl_device_callback_param_t;
extern zb_zcl_device_callback_param_t fake_param;
#define ZB_BUF_GET_PARAM(b,t) ((t*)&fake_param)
enum{ZB_ZCL_OTA_UPGRADE_STATUS_START,ZB_ZCL_OTA_UPGRADE_STATUS_APPLY,ZB_ZCL_OTA_UPGRADE_STATUS_RECEIVE,ZB_ZCL_OTA_UPGRADE_STATUS_FINISH,ZB_ZCL_OTA_UPGRADE_STATUS_ABORT,ZB_ZCL_OTA_UPGRADE_STATUS_CHECK,ZB_ZCL_OTA_UPGRADE_STATUS_OK,ZB_ZCL_OTA_UPGRADE_STATUS_ERROR,ZB_ZCL_OTA_UPGRADE_STATUS_REQUIRE_MORE_IMAGE,ZB_ZCL_OTA_UPGRADE_STATUS_BUSY};
#define ZB_ZCL_DECLARE_OTA_UPGRADE_ATTRIB_LIST(name,...) zb_zcl_attr_t name[16]
#define RET_OK 0
#define RET_NOT_IMPLEMENTED -1
#define ZB_MILLISECONDS_TO_BEACON_INTERVAL(n) (n)
int fake_schedule(void(*cb)(uint8_t),uint8_t value);
int fake_alarm(void(*cb)(uint8_t),uint8_t value,unsigned delay);
#define ZB_SCHEDULE_APP_CALLBACK(cb,b) fake_schedule(cb,b)
#define ZB_SCHEDULE_APP_ALARM(cb,b,d) fake_alarm(cb,b,d)
void zb_zcl_ota_upgrade_resume_client(uint8_t,uint8_t);
void zb_zcl_ota_upgrade_init_client(uint8_t);
int zb_buf_get_out_delayed(void(*cb)(uint8_t));
#define APP_VERSION_MAJOR 0
#define APP_VERSION_MINOR 5
#define APP_PATCHLEVEL 1
#define APP_TWEAK 0
#define LOG_MODULE_REGISTER(...)
#define LOG_ERR(...) ((void)0)
#define LOG_INF(...) ((void)0)
#define LOG_LEVEL_INF 3
#define BUILD_ASSERT(x) _Static_assert(x,"buildassert")
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define MIN(a,b) ((a)<(b)?(a):(b))
#define ARG_UNUSED(x) (void)(x)
#define __aligned(x) __attribute__((aligned(x)))
struct device{int unused;};
extern const struct device fake_device;
#define DEVICE_DT_GET(...) (&fake_device)
#define DT_CHOSEN(...) 0
int flash_erase(const struct device*,uint32_t,size_t);
int flash_write(const struct device*,uint32_t,const void*,size_t);
struct k_work{void(*handler)(struct k_work*);};
struct k_work_q{int unused;};
#define K_THREAD_STACK_DEFINE(n,s) uint8_t n[s]
#define K_THREAD_STACK_SIZEOF(n) sizeof(n)
#define K_MSEC(n) (n)
static inline void k_sleep(int n){(void)n;}
static inline void k_work_init(struct k_work*w,void(*fn)(struct k_work*)){w->handler=fn;}
static inline void k_work_queue_start(struct k_work_q*q,void*s,size_t n,int p,void*c){(void)q;(void)s;(void)n;(void)p;(void)c;}
int k_work_submit_to_queue(struct k_work_q*,struct k_work*);
#endif
