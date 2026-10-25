#include "recovery_boot_history.h"
#include <zephyr/mgmt/mcumgr/mgmt/mgmt.h>
#include <zephyr/mgmt/mcumgr/smp/smp.h>

static int read_history(struct smp_streamer *stream)
{
 struct boot_trace_history history;
 /* One full mutex snapshot. This read path never loads/saves/deletes settings,
  * changes a boot request, clears RESETREAS, erases flash or requests a reset. */
 vimar_boot_trace_history_snapshot(&history);
 return recovery_boot_history_encode(stream->writer->zs,&history)?MGMT_ERR_EOK:MGMT_ERR_EMSGSIZE;
}
static const struct mgmt_handler handlers[]={{.mh_read=read_history}};
static struct mgmt_group group={.mg_handlers=handlers,.mg_handlers_count=1,.mg_group_id=VIMAR_BOOT_HISTORY_GROUP};
void recovery_boot_history_register(void){mgmt_register_group(&group);}
