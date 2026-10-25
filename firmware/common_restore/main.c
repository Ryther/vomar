/* SPDX-License-Identifier: Apache-2.0
 * Optional authenticated stock-restore service. No MCUmgr, settings backend,
 * per-unit image, host-supplied identity or arbitrary memory access.
 */
#include "config_guard.h"
#include "platform_zephyr.h"
#include "protocol.h"
#include "radio_identity.h"
#include "link.h"
#include <errno.h>
#include <string.h>
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/bluetooth/conn.h>
#include <zephyr/bluetooth/gatt.h>
#include <zephyr/random/random.h>
#include <zephyr/sys/atomic.h>
#include <zephyr/sys/byteorder.h>
#include <hal/nrf_ficr.h>
#if defined(CONFIG_VIMAR_COMMON_RESTORE_BOOTSTRAP)
#define SERVICE_UUID BT_UUID_128_ENCODE(0xfde30805,0xc003,0x4a40,0x8d00,0x308050000030)
#define COMMAND_UUID BT_UUID_128_ENCODE(0xfde30805,0xc003,0x4a40,0x8d00,0x308050000031)
#else
#define SERVICE_UUID BT_UUID_128_ENCODE(0xfde30805,0xc004,0x4a40,0x8d00,0x308050000040)
#define COMMAND_UUID BT_UUID_128_ENCODE(0xfde30805,0xc004,0x4a40,0x8d00,0x308050000041)
#endif
static struct bt_uuid_128 service_uuid=BT_UUID_INIT_128(SERVICE_UUID),command_uuid=BT_UUID_INIT_128(COMMAND_UUID);
static uint8_t response[COMMON_RESTORE_STATUS_SIZE],pending[COMMON_RESTORE_WIRE_HEADER+COMMON_RESTORE_WIRE_CHUNK];
static uint8_t read_response[COMMON_RESTORE_STATUS_SIZE];
static size_t pending_size;
static uint32_t pending_owner;
static struct bt_conn *connection;
static struct common_restore_link link;
static struct k_spinlock radio_lock;
K_MUTEX_DEFINE(engine_lock);
static struct k_work_q restore_queue;
K_THREAD_STACK_DEFINE(restore_stack,12288);
static struct k_work command_work,open_work,cancel_work,advertise_work;
static atomic_t disconnected_owner;

static void publish(unsigned op,uint32_t seq,int rc)
{
 uint8_t snapshot[COMMON_RESTORE_STATUS_SIZE];
 common_restore_status(&common_restore_state,common_restore_platform_role(),common_restore_platform_flags(),op,seq,snapshot,sizeof(snapshot));
 sys_put_le32((uint32_t)rc,snapshot+4);
 if(!common_restore_state.owner){sys_put_le32(NRF_FICR->DEVICEID[0],snapshot+36);sys_put_le32(NRF_FICR->DEVICEID[1],snapshot+40);}
 k_spinlock_key_t key=k_spin_lock(&radio_lock);memcpy(response,snapshot,sizeof(snapshot));common_restore_link_publish(&link,(uint32_t)common_restore_state.owner);k_spin_unlock(&radio_lock,key);
}
static void open_session(struct k_work *work)
{
 ARG_UNUSED(work);uint32_t owner;bool alive;
 k_spinlock_key_t key=k_spin_lock(&radio_lock);owner=link.owner;alive=connection!=NULL;k_spin_unlock(&radio_lock,key);
 if(!owner||!alive||common_restore_platform_quiescing())return;
 k_mutex_lock(&engine_lock,K_FOREVER);
 if(common_restore_state.owner==owner){k_mutex_unlock(&engine_lock);return;} /* stale queued READ must not replace an active epoch */
 if(common_restore_state.owner)common_restore_cancel(&common_restore_state,common_restore_state.owner);
 uint32_t epoch=0;int rc=sys_csrand_get(&epoch,sizeof(epoch));if(!epoch&&!rc)rc=-EIO;
 common_restore_platform_operation(owner);size_t count;const struct loader_contract_record *records=common_restore_platform_records(&count);
 if(!rc)rc=common_restore_open(&common_restore_state,common_restore_platform_io(),records,count,owner,epoch);
 key=k_spin_lock(&radio_lock);alive=connection!=NULL&&link.owner==owner;k_spin_unlock(&radio_lock,key);
 if(!alive){common_restore_cancel(&common_restore_state,owner);rc=-ECANCELED;}
 publish(0,0,rc);k_mutex_unlock(&engine_lock);
}
static void cancel_session(struct k_work *work)
{
 ARG_UNUSED(work);if(common_restore_platform_quiescing())return;
 k_mutex_lock(&engine_lock,K_FOREVER);common_restore_cancel(&common_restore_state,(uint32_t)atomic_get(&disconnected_owner));publish(8,0,-ECANCELED);k_mutex_unlock(&engine_lock);
}
static void execute_command(struct k_work *work)
{
 ARG_UNUSED(work);uint8_t frame[sizeof(pending)];size_t size;uint32_t owner;
 k_spinlock_key_t key=k_spin_lock(&radio_lock);size=pending_size;owner=pending_owner;memcpy(frame,pending,size);k_spin_unlock(&radio_lock,key);
 k_mutex_lock(&engine_lock,K_FOREVER);common_restore_platform_operation(owner);
 const uint8_t *blob;size_t blob_size;common_restore_platform_blob(&blob,&blob_size);
 int rc=common_restore_dispatch(&common_restore_state,owner,frame,size,blob,blob_size);
 publish(frame[1],sys_get_le32(frame+8),rc);
 if(!rc&&frame[1]==6) {
  rc=common_restore_finalize_execute(&common_restore_state,owner,sys_get_le32(frame+4));
  publish(frame[1],sys_get_le32(frame+8),rc); /* Only a refused finalization returns. */
 }
 k_mutex_unlock(&engine_lock);
 key=k_spin_lock(&radio_lock);(void)common_restore_link_finish(&link,owner);k_spin_unlock(&radio_lock,key);
}
static ssize_t read_status(struct bt_conn *peer,const struct bt_gatt_attr *attr,void *buffer,uint16_t length,uint16_t offset)
{
 uint8_t snapshot[sizeof(response)];bool open;
 k_spinlock_key_t key=k_spin_lock(&radio_lock);
 open=connection==peer&&common_restore_link_needs_open(&link,common_restore_platform_quiescing());
 /* One coherent status across ATT Read Blob fragments, even if a worker
  * publishes its result between fragments. A new offset0 starts a new read. */
 if(!offset)memcpy(read_response,response,sizeof(read_response));
 memcpy(snapshot,read_response,sizeof(snapshot));k_spin_unlock(&radio_lock,key);
 if(open&&!common_restore_platform_quiescing())k_work_submit_to_queue(&restore_queue,&open_work);
 return bt_gatt_attr_read(peer,attr,buffer,length,offset,snapshot,sizeof(snapshot));
}
static ssize_t write_command(struct bt_conn *peer,const struct bt_gatt_attr *attr,const void *buffer,uint16_t length,uint16_t offset,uint8_t flags)
{
 ARG_UNUSED(attr);
 if(offset||flags||length<COMMON_RESTORE_WIRE_HEADER||length>sizeof(pending))return BT_GATT_ERR(BT_ATT_ERR_INVALID_ATTRIBUTE_LEN);
 k_spinlock_key_t key=k_spin_lock(&radio_lock);
 if(connection!=peer||!common_restore_link_submit(&link,link.owner,common_restore_platform_quiescing())){
  k_spin_unlock(&radio_lock,key);return BT_GATT_ERR(BT_ATT_ERR_PROCEDURE_IN_PROGRESS);
 }
 memcpy(pending,buffer,length);pending_size=length;pending_owner=link.owner;k_spin_unlock(&radio_lock,key);
 if(k_work_submit_to_queue(&restore_queue,&command_work)<0){key=k_spin_lock(&radio_lock);(void)common_restore_link_finish(&link,pending_owner);k_spin_unlock(&radio_lock,key);return BT_GATT_ERR(BT_ATT_ERR_UNLIKELY);}
 return length; /* Queued only: client must read nonce/sequence/status, not assume completion. */
}
BT_GATT_SERVICE_DEFINE(restore_service,BT_GATT_PRIMARY_SERVICE(&service_uuid),
 BT_GATT_CHARACTERISTIC(&command_uuid.uuid,BT_GATT_CHRC_READ|BT_GATT_CHRC_WRITE,
 BT_GATT_PERM_READ_AUTHEN|BT_GATT_PERM_WRITE_AUTHEN,read_status,write_command,NULL));
static const struct bt_data advertising[]={BT_DATA_BYTES(BT_DATA_FLAGS,BT_LE_AD_GENERAL|BT_LE_AD_NO_BREDR),BT_DATA_BYTES(BT_DATA_UUID128_ALL,SERVICE_UUID)};
static uint8_t identity_hint[26]={SERVICE_UUID,COMMON_RESTORE_PROTOCOL,0};
static void advertise(struct k_work *work)
{
 ARG_UNUSED(work);if(common_restore_platform_quiescing())return;
 const struct bt_data scan[]={BT_DATA(BT_DATA_SVC_DATA128,identity_hint,sizeof(identity_hint))};
 (void)bt_le_adv_start(BT_LE_ADV_CONN_FAST_1,advertising,ARRAY_SIZE(advertising),scan,ARRAY_SIZE(scan));
}
static void connected_callback(struct bt_conn *peer,uint8_t error)
{
 if(error)return;
 k_spinlock_key_t key=k_spin_lock(&radio_lock);
 if(connection){k_spin_unlock(&radio_lock,key);(void)bt_conn_disconnect(peer,BT_HCI_ERR_CONN_LIMIT_EXCEEDED);return;}
 uint32_t owner=common_restore_link_connect(&link);memset(read_response,0,sizeof(read_response));connection=bt_conn_ref(peer);k_spin_unlock(&radio_lock,key);
 common_restore_platform_peer(owner,true);
}
static void disconnected_callback(struct bt_conn *peer,uint8_t reason)
{
 ARG_UNUSED(reason);uint32_t owner=0;struct bt_conn *old=NULL;
 k_spinlock_key_t key=k_spin_lock(&radio_lock);
 if(connection==peer){old=connection;connection=NULL;owner=link.owner;(void)common_restore_link_disconnect(&link,owner);}
 k_spin_unlock(&radio_lock,key);
 if(!old)return;
 common_restore_platform_peer(owner,false);bt_conn_unref(old);
 if(!common_restore_platform_quiescing()){atomic_set(&disconnected_owner,(atomic_val_t)owner);k_work_submit_to_queue(&restore_queue,&cancel_work);}
}
static void recycled(void){if(!common_restore_platform_quiescing())k_work_submit(&advertise_work);}
BT_CONN_CB_DEFINE(callbacks)={.connected=connected_callback,.disconnected=disconnected_callback,.recycled=recycled};
int main(void)
{
 int rc=common_restore_platform_init();if(rc)return 0;
 k_work_init(&command_work,execute_command);k_work_init(&open_work,open_session);k_work_init(&cancel_work,cancel_session);k_work_init(&advertise_work,advertise);
 k_work_queue_start(&restore_queue,restore_stack,K_THREAD_STACK_SIZEOF(restore_stack),5,NULL);
 publish(0,0,0);
 uint8_t nonce[16],address_bytes[6];const uint32_t uid[2]={NRF_FICR->DEVICEID[0],NRF_FICR->DEVICEID[1]};
 rc=sys_csrand_get(nonce,sizeof(nonce));
 if(!rc)rc=common_restore_radio_address(uid,nonce,common_restore_platform_role(),&common_restore_platform_io()->hash,address_bytes);
 if(rc)return 0;
 bt_addr_le_t address={.type=BT_ADDR_LE_RANDOM};memcpy(address.a.val,address_bytes,6);
 if(bt_id_create(&address,NULL)<0||bt_passkey_set(824005)||bt_enable(NULL))return 0;
 identity_hint[17]=(uint8_t)common_restore_platform_role();sys_put_le32(uid[0],identity_hint+18);sys_put_le32(uid[1],identity_hint+22);
 k_work_submit(&advertise_work);return 0;
}
