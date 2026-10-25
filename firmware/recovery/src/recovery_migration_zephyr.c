#include "recovery_migration.h"
#include "recovery_migration_config.h"
#include "recovery_exit_zephyr.h"
#include <errno.h>
#include <zephyr/mgmt/mcumgr/mgmt/mgmt.h>
#include <zephyr/mgmt/mcumgr/smp/smp.h>
static int write_migration(struct smp_streamer *stream)
{
 uint8_t hash[32];
 if(!recovery_migration_decode(stream->reader->zs,hash))return MGMT_ERR_EINVAL;
 /* Do not reserve a transition if even the response body cannot fit. A later
  * framework map/output error cancels through CMD_DONE before execution. */
 if(!recovery_migration_encode_accepted(stream->writer->zs))return MGMT_ERR_EMSGSIZE;
 int rc=recovery_exit_zephyr_migration_request(hash);
 return !rc?MGMT_ERR_EOK:rc==-EBUSY?MGMT_ERR_EBUSY:MGMT_ERR_EACCESSDENIED;
}
static const struct mgmt_handler handlers[]={{.mh_write=write_migration}};
static struct mgmt_group group={.mg_handlers=handlers,.mg_handlers_count=1,.mg_group_id=VIMAR_MIGRATION_GROUP};
void recovery_migration_register(void){mgmt_register_group(&group);}
