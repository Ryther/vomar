#include "recovery_identity.h"
#include "ota_image.h"
#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
#include "loader_runtime_config.h"
#include "loader_runtime_zephyr.h"
#include "loader_runtime_cbor.h"
#include <zcbor_decode.h>
#if !defined(CONFIG_MCUMGR_TRANSPORT_BT) || !defined(CONFIG_MCUMGR_TRANSPORT_BT_PERM_RW_AUTHEN)
#error "Typed recovery identity requires authenticated Bluetooth"
#endif
#endif
#include <hal/nrf_ficr.h>
#include <zephyr/drivers/flash.h>
#include <zephyr/mgmt/mcumgr/mgmt/mgmt.h>
#include <zephyr/mgmt/mcumgr/smp/smp.h>
#include <zephyr/bluetooth/gatt.h>

static const struct device *flash_device=DEVICE_DT_GET(DT_CHOSEN(zephyr_flash_controller));
static int read_loader(void *context,uint32_t offset,uint8_t *data,size_t size)
{
 ARG_UNUSED(context);
 return flash_read(flash_device,offset,data,size);
}

static int read_identity(struct smp_streamer *stream)
{
 if(!device_is_ready(flash_device))return MGMT_ERR_EUNKNOWN;
 const struct ota_reader loader={.size=0xc000,.read=read_loader};
 uint8_t digest[32];
 if(ota_image_reader_sha256(&loader,0,loader.size,digest))return MGMT_ERR_EUNKNOWN;
 uint32_t uid[]={nrf_ficr_deviceid_get(NRF_FICR,0),nrf_ficr_deviceid_get(NRF_FICR,1)};
 return recovery_identity_encode(stream->writer->zs,uid,digest)?MGMT_ERR_EOK:MGMT_ERR_EMSGSIZE;
}

#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
static int read_identity_v2(struct smp_streamer *stream)
{
 /* Host-supplied anchors, approval lists and ranges have no place in this
  * read-only request. Only a complete empty map is accepted. */
 zcbor_state_t *reader=stream->reader->zs;
 if(!zcbor_map_start_decode(reader)||!zcbor_map_end_decode(reader)||!zcbor_payload_at_end(reader))return MGMT_ERR_EINVAL;
 struct loader_runtime_identity identity;
 if(loader_runtime_zephyr_snapshot(&identity))return MGMT_ERR_EACCESSDENIED;
 return loader_runtime_identity_encode(stream->writer->zs,&identity)?MGMT_ERR_EOK:MGMT_ERR_EMSGSIZE;
}
#endif
static const struct mgmt_handler handlers[]={
 {.mh_read=read_identity},
#if defined(CONFIG_VIMAR_LOADER_RUNTIME_V2)
 {.mh_read=read_identity_v2},
#endif
};
static struct mgmt_group group={.mg_handlers=handlers,.mg_handlers_count=sizeof(handlers)/sizeof(handlers[0]),.mg_group_id=VIMAR_IDENTITY_GROUP};
void recovery_identity_register(void){mgmt_register_group(&group);}

/* The advertised project service exposes protocol/layout capabilities only.
 * Actual runtime identity is queried using authenticated SMP on the same link. */
static const struct bt_uuid_128 project_service=BT_UUID_INIT_128(
 BT_UUID_128_ENCODE(0x7b2f3080,0x5c91,0x4a6d,0x9f22,0x4e8c6d300805));
static const struct bt_uuid_128 capabilities=BT_UUID_INIT_128(
 BT_UUID_128_ENCODE(0x7b2f3081,0x5c91,0x4a6d,0x9f22,0x4e8c6d300805));
static ssize_t read_capabilities(struct bt_conn *connection,const struct bt_gatt_attr *attr,
 void *buffer,uint16_t length,uint16_t offset)
{
 static const uint8_t value[]={1,2};
 return bt_gatt_attr_read(connection,attr,buffer,length,offset,value,sizeof(value));
}
BT_GATT_SERVICE_DEFINE(vimar_identity_service,
 BT_GATT_PRIMARY_SERVICE(&project_service),
 BT_GATT_CHARACTERISTIC(&capabilities.uuid,BT_GATT_CHRC_READ,BT_GATT_PERM_READ_AUTHEN,
  read_capabilities,NULL,NULL));
