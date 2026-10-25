/* Local read-only preflight. Never consumes GPREGRET2 or writes handoff/settings. */
#include "research_handoff.h"
#include <errno.h>
#include <zephyr/drivers/retained_mem.h>
#include <zephyr/settings/settings.h>
static const struct device *marker_device=DEVICE_DT_GET(DT_NODELABEL(gpregret2));
static int load_handoff(void *ctx,uint8_t *record,size_t size)
{
 (void)ctx;
 ssize_t n=settings_load_one("vimar/handoff",record,size);
 return n==(ssize_t)size?0:n<0?(int)n:-EINVAL;
}
static int read_marker(void *ctx,uint8_t *marker)
{
 (void)ctx;
 if(!device_is_ready(marker_device))return-ENODEV;
 return retained_mem_read(marker_device,0,marker,1);
}
int recovery_migration_preflight(void)
{
 uint8_t journal;
 ssize_t n=settings_load_one("vimar/ota",&journal,sizeof(journal));
 if(n>0)return-EBUSY;
 if(n<0&&n!=-ENOENT)return(int)n;
 const struct research_handoff_io io={.load=load_handoff,.get_marker=read_marker};
 struct research_protected_handoff handoff;
 int rc=research_handoff_peek_protected(&io,&handoff);
 return rc<0?rc:0;
}
