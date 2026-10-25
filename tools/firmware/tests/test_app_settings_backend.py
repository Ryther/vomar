import subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
class BackendTests(unittest.TestCase):
 def test_state_only_save_preserves_initial_and_loaded_configuration(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Path(tmp);(d/'zephyr/settings').mkdir(parents=True)
   (d/'zephyr/settings/settings.h').write_text('''#include <stddef.h>
#include <sys/types.h>
#define ARG_UNUSED(x) (void)(x)
typedef ssize_t (*settings_read_cb)(void *,void *,size_t);
int settings_save_one(const char *,const void *,size_t);
int settings_delete(const char *);
#define SETTINGS_STATIC_HANDLER_DEFINE(name,tree,get,set,commit,export) static void *name __attribute__((used))=(void *)(set)
''')
   (d/'main.c').write_text('''#include <assert.h>
#include <string.h>
#include "app_settings_backend.h"
#include "settings_record.h"
static uint8_t saved[SETTINGS_RECORD_MAX_SIZE];static size_t count;static int save_error;static unsigned saves;
int settings_save_one(const char *key,const void *data,size_t n){(void)key;++saves;if(save_error)return save_error;memcpy(saved,data,n);count=n;return 0;}
int settings_delete(const char *key){(void)key;return 0;}
int main(void){
 struct dimmer_config initial=dimmer_config_defaults();initial.long_press_ms=500;initial.level_step_period_ms=50;
 app_settings_init();app_settings_seed(&initial,true,73);app_settings_schedule_state(false,73,0);app_settings_tick(30000);
 struct dimmer_config loaded;bool on;uint8_t level;
 assert(count>0);assert(settings_record_decode(saved,count,&loaded,&on,&level)==SETTINGS_RECORD_OK);
 assert(loaded.long_press_ms==500&&loaded.level_step_period_ms==50&&!on&&level==73);
 loaded.long_press_ms=700;loaded.level_step_period_ms=80;
 app_settings_init();app_settings_seed(&loaded,false,73);app_settings_schedule_state(true,88,0);app_settings_tick(30000);
 assert(settings_record_decode(saved,count,&loaded,&on,&level)==SETTINGS_RECORD_OK);
 assert(loaded.long_press_ms==700&&loaded.level_step_period_ms==80&&on&&level==88);
 /* Flush changes inside both deferred-save windows, using current state. */
 loaded.long_press_ms=900;
 app_settings_schedule_config(&loaded,1000);
 app_settings_schedule_state(false,64,1000);
 assert(app_settings_flush_current(&loaded,false,64)==0);
 assert(settings_record_decode(saved,count,&loaded,&on,&level)==SETTINGS_RECORD_OK);
 assert(!on&&level==64&&loaded.long_press_ms==900);
 unsigned flushed=saves;app_settings_tick(60000);assert(saves==flushed);
 /* Failed writes propagate and can be retried; invalid records never save. */
 save_error=-5;assert(app_settings_flush_current(&loaded,true,88)==-5);
 save_error=0;assert(app_settings_flush_current(&loaded,true,88)==0);
 assert(settings_record_decode(saved,count,&loaded,&on,&level)==SETTINGS_RECORD_OK);
 assert(on&&level==88);
 loaded.long_press_ms=0;flushed=saves;
 assert(app_settings_flush_current(&loaded,false,64)<0&&saves==flushed);
 return 0;}
''')
   cmd=['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(d),'-I',str(ROOT/'firmware/src'),str(d/'main.c')]+[str(ROOT/'firmware/src'/n) for n in ['app_settings_backend.c','settings_store.c','settings_record.c','dimmer_config.c']]+['-o',str(d/'test')]
   subprocess.run(cmd,check=True);subprocess.run([str(d/'test')],check=True)
