#include <assert.h>
#include "application_controller.h"
static unsigned requests, events, system_events; static bool requested_on; static uint8_t requested_level;
static enum application_system_event last_system_event;
static void request(void *ctx,uint32_t op,bool on,uint8_t level){struct application_controller *c=ctx;requests++;requested_on=on;requested_level=level;application_controller_feedback(c,op,on,level);}
static void event(void *ctx,const struct gesture_event *e){(void)ctx;(void)e;events++;}
static void system_event(void *ctx,enum application_system_event e,uint16_t data){(void)ctx;(void)data;system_events++;last_system_event=e;}
static void test_hold_repeats_internal_level_steps(void)
{
 struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
 struct application_callbacks cb={.secondary_request=request,.gesture_event=event,.system_event=system_event};
 requests=0;events=0;application_controller_init(&c,&cfg,true,100,&cb,&c,0);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,1000);
 application_controller_tick(&c,1250);assert(requests==1&&requested_level==110);
 application_controller_tick(&c,1349);assert(requests==1);
 application_controller_tick(&c,1350);assert(requests==2&&requested_level==120);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,false,1400);
 application_controller_tick(&c,1500);assert(requests==2);
}

static void initialize(struct application_controller *c, struct dimmer_config *cfg,
    bool on, uint64_t now)
{
    const struct application_callbacks cb = {.secondary_request=request,
        .gesture_event=event,.system_event=system_event};
    requests=0;events=0;system_events=0;
    application_controller_init(c,cfg,on,100,&cb,c,now);
}

static void test_front_holds_leave_off_lamp_unchanged(void)
{
 for(enum gesture_side side=GESTURE_SIDE_UP;side<GESTURE_SIDE_COUNT;side++) {
  struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
  initialize(&c,&cfg,false,0);
  uint32_t operation=c.model.state.operation_id;
  application_controller_button_edge(&c,side,true,1000);
  application_controller_tick(&c,1250);
  assert(events==2 && requests==0 && !c.model.state.on && !c.output_on);
  application_controller_tick(&c,1350);
  application_controller_tick(&c,1550);
  application_controller_button_edge(&c,side,false,1600);
  application_controller_tick(&c,2000);
  assert(events==3 && requests==0 && !c.model.state.on && !c.model.state.target_on);
  assert(c.model.state.operation_id==operation && c.model.state.level==100);
  assert(c.model.state.target_level==100 && c.model.previous_level==100);
 }
}

static void test_front_holds_dim_on_lamp_in_each_direction(void)
{
 const uint8_t first[]={110,90},second[]={120,80};
 for(enum gesture_side side=GESTURE_SIDE_UP;side<GESTURE_SIDE_COUNT;side++) {
  struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
  initialize(&c,&cfg,true,0);
  application_controller_button_edge(&c,side,true,1000);
  application_controller_tick(&c,1250);
  assert(events==2 && requests==1 && requested_on && requested_level==first[side]);
  application_controller_tick(&c,1350);
  assert(requests==2 && requested_level==second[side]);
  application_controller_button_edge(&c,side,false,1400);
  application_controller_tick(&c,2000);
  assert(events==3 && requests==2 && c.model.state.on);
 }
}

static void test_front_holds_do_not_bypass_pending_on_delay(void)
{
 for(enum gesture_side side=GESTURE_SIDE_UP;side<GESTURE_SIDE_COUNT;side++) {
  struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
  cfg.initial_on_delay_ms=1000;cfg.rise_transition_ms=1000;
  initialize(&c,&cfg,false,0);
  application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,0);
  uint32_t operation=c.model.state.operation_id;
  assert(c.model.state.on && !c.output_on);
  application_controller_button_edge(&c,side,true,100);
  application_controller_tick(&c,350);
  application_controller_tick(&c,500);
  assert(events==2 && requests==0 && !c.output_on && c.output_start_ms==1000);
  assert(c.model.state.operation_id==operation && c.model.state.level==100);
  application_controller_tick(&c,2000);
  assert(requests==1 && requested_on && requested_level==100);
  application_controller_tick(&c,2200);
  application_controller_button_edge(&c,side,false,2300);
  application_controller_tick(&c,2500);
  assert(events==3 && requests==1 && c.model.previous_level==100);
 }
}

static void test_front_hold_stops_when_accepted_state_turns_off(void)
{
 for(enum gesture_side side=GESTURE_SIDE_UP;side<GESTURE_SIDE_COUNT;side++) {
  for(unsigned remote=0;remote<2;remote++) {
   struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
   cfg.fall_transition_ms=1000;
   initialize(&c,&cfg,true,0);
   application_controller_button_edge(&c,side,true,100);
   application_controller_tick(&c,350);
   assert(requests==1 && requested_on);
   application_controller_command(&c,false,c.model.state.level,
       remote?DIMMER_SOURCE_ZIGBEE:DIMMER_SOURCE_PHYSICAL,400);
   uint32_t operation=c.model.state.operation_id;
   uint8_t remembered=c.model.previous_level;
   assert(!c.model.state.on && c.output_on);
   application_controller_tick(&c,500);
   assert(!c.model.state.on && !c.model.state.target_on);
   assert(c.model.state.operation_id==operation && c.model.previous_level==remembered);
   application_controller_tick(&c,1400);
   assert(!c.output_on && !c.hold_active[side]);
   unsigned before=requests;
   application_controller_button_edge(&c,side,false,1500);
   application_controller_tick(&c,2000);
   assert(requests==before && !c.model.state.on);
  }
 }
}

static void test_automatic_off_sources_and_bypass(void)
{
    struct application_controller c; struct dimmer_config cfg=dimmer_config_defaults();
    cfg.short_press_mode=DIMMER_SHORT_CUSTOM;
    cfg.auto_off_mode=DIMMER_AUTO_OFF_EVERY_ON; cfg.auto_off_duration_s=30;
    initialize(&c,&cfg,false,0);
    application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,1000);
    assert(application_controller_state(&c)->off_timer_active);
    assert(dimmer_model_timer_remaining_s(&c.model,1001)==30);
    application_controller_bypass_on(&c,2000);
    assert(application_controller_state(&c)->on);
    assert(application_controller_state(&c)->auto_off_bypassed);
    assert(!application_controller_state(&c)->off_timer_active);
    application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,3000);
    assert(!application_controller_state(&c)->off_timer_active);
    application_controller_command(&c,false,100,DIMMER_SOURCE_ZIGBEE,4000);
    assert(!application_controller_state(&c)->auto_off_bypassed);

    cfg.auto_off_mode=DIMMER_AUTO_OFF_PHYSICAL_ON_ONLY;
    initialize(&c,&cfg,false,0);
    application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,1000);
    assert(!application_controller_state(&c)->off_timer_active);
    application_controller_command(&c,false,100,DIMMER_SOURCE_ZIGBEE,1100);
    application_controller_button_edge(&c,GESTURE_SIDE_UP,true,2000);
    application_controller_button_edge(&c,GESTURE_SIDE_UP,false,2010);
    application_controller_tick(&c,2160);
    assert(application_controller_state(&c)->off_timer_active);
}

static void press_twice(struct application_controller *c, enum gesture_side side,
    uint64_t now)
{
    application_controller_button_edge(c,side,true,now);
    application_controller_button_edge(c,side,false,now+10);
    application_controller_button_edge(c,side,true,now+20);
    application_controller_button_edge(c,side,false,now+30);
}

static void test_single_timer_double_bypass_and_inverse(void)
{
    struct application_controller c; struct dimmer_config cfg=dimmer_config_defaults();
    cfg.short_press_mode=DIMMER_SHORT_CUSTOM;
    cfg.single_up_action=DIMMER_ACTION_TIMED_ON;
    cfg.double_up_action=DIMMER_ACTION_BYPASS_ON;
    initialize(&c,&cfg,false,0);
    application_controller_button_edge(&c,GESTURE_SIDE_UP,true,10);
    application_controller_button_edge(&c,GESTURE_SIDE_UP,false,20);
    application_controller_tick(&c,170);
    assert(application_controller_state(&c)->off_timer_active);
    press_twice(&c,GESTURE_SIDE_UP,200);
    assert(application_controller_state(&c)->auto_off_bypassed);
    assert(!application_controller_state(&c)->off_timer_active);

    cfg.single_up_action=DIMMER_ACTION_BYPASS_ON;
    cfg.double_up_action=DIMMER_ACTION_TIMED_ON;
    initialize(&c,&cfg,false,0);
    application_controller_button_edge(&c,GESTURE_SIDE_UP,true,10);
    application_controller_button_edge(&c,GESTURE_SIDE_UP,false,20);
    application_controller_tick(&c,170);
    assert(application_controller_state(&c)->auto_off_bypassed);
    press_twice(&c,GESTURE_SIDE_UP,200);
    assert(!application_controller_state(&c)->auto_off_bypassed);
    assert(application_controller_state(&c)->off_timer_active);
}
static void test_nonadjustable_holds_emit_events_without_output(void)
{
    struct application_controller c; struct dimmer_config cfg=dimmer_config_defaults();
    for (unsigned mode=DIMMER_OUTPUT_FIXED_LEVEL;mode<=DIMMER_OUTPUT_STOCK_SWITCH;mode++) {
        cfg.output_mode=(enum dimmer_output_mode)mode;
        for (unsigned on=0;on<2;on++) {
            initialize(&c,&cfg,on,0);
            application_controller_button_edge(&c,GESTURE_SIDE_UP,true,1000);
            application_controller_tick(&c,1250);
            application_controller_tick(&c,1500);
            application_controller_button_edge(&c,GESTURE_SIDE_UP,false,1600);
            assert(events==3); /* press, long, release */
            assert(requests==0 && application_controller_state(&c)->on==(bool)on);
            assert(application_controller_state(&c)->level==100);
        }
    }
    cfg.output_mode=DIMMER_OUTPUT_DIMMABLE;
    initialize(&c,&cfg,true,0);
    application_controller_button_edge(&c,GESTURE_SIDE_DOWN,true,1000);
    application_controller_tick(&c,1250);assert(requests==1);
    c.model.config.output_mode=DIMMER_OUTPUT_FIXED_LEVEL;
    application_controller_tick_input(&c,1300,false);
    assert(!c.hold_active[GESTURE_SIDE_DOWN]);
    c.model.config.output_mode=DIMMER_OUTPUT_DIMMABLE;
    application_controller_tick(&c,1500);assert(requests==1);
}

static unsigned accepted;
static void state_changed(void *ctx){(void)ctx;accepted++;}
static void test_delay_ramps_and_command_replacement(void)
{
    struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
    cfg.initial_on_delay_ms=100;cfg.rise_transition_ms=1000;cfg.fall_transition_ms=500;
    cfg.min_level=10;cfg.max_level=200;
    initialize(&c,&cfg,false,0);c.callbacks.state_changed=state_changed;accepted=0;
    application_controller_command(&c,true,250,DIMMER_SOURCE_ZIGBEE,0);
    assert(accepted==1 && c.model.state.on && c.model.state.level==200 && requests==0);
    application_controller_command(&c,true,250,DIMMER_SOURCE_ZIGBEE,50);
    assert(c.output_start_ms==100);
    application_controller_tick(&c,99);assert(requests==0);
    application_controller_tick(&c,110);assert(requests==1 && requested_on && requested_level==2);
    application_controller_tick(&c,600);assert(requests==2 && requested_on && requested_level==100);
    assert(c.model.state.on && c.model.state.level==200);
    application_controller_command(&c,false,200,DIMMER_SOURCE_ZIGBEE,600);
    assert(!c.model.state.on && accepted==3);
    application_controller_tick(&c,850);assert(requested_level==50);
    application_controller_tick(&c,1100);assert(!requested_on);
    unsigned saved=requests;application_controller_tick(&c,2000);assert(requests==saved);
    application_controller_command(&c,true,1,DIMMER_SOURCE_ZIGBEE_LEVEL,2100);
    assert(requested_on && requested_level==10 && c.model.state.level==10);
    application_controller_command(&c,true,200,DIMMER_SOURCE_ZIGBEE,2200);
    application_controller_tick(&c,2700);assert(requested_level==105);
    application_controller_command(&c,true,40,DIMMER_SOURCE_ZIGBEE_LEVEL,2701);
    saved=requests;application_controller_tick(&c,5000);
    assert(requests==saved && requested_level==40 && c.model.state.level==40);
}

static void reject_output(void *ctx,uint32_t op,bool on,uint8_t level)
{(void)on;(void)level;requests++;application_controller_output_failed(ctx,op,DIMMER_FAULT_SECONDARY_REJECTED);}
static void test_delayed_failure_and_off_cancel(void)
{
    struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
    cfg.initial_on_delay_ms=100;cfg.rise_transition_ms=1000;
    initialize(&c,&cfg,false,0);c.callbacks.secondary_request=reject_output;
    application_controller_command(&c,true,200,DIMMER_SOURCE_ZIGBEE,0);
    assert(c.model.state.on && requests==0);
    application_controller_tick(&c,600);
    assert(!c.model.state.on && c.model.state.fault.active && !c.output_pending);
    unsigned saved=requests;application_controller_tick(&c,2000);assert(requests==saved);
    initialize(&c,&cfg,false,0);
    application_controller_command(&c,true,200,DIMMER_SOURCE_ZIGBEE,0);
    application_controller_command(&c,false,200,DIMMER_SOURCE_ZIGBEE,50);
    application_controller_tick(&c,2000);assert(!requested_on && !c.output_pending && !c.model.state.on);
    /* Long dimming owns its discrete steps; defaults cannot restart a delay every tick. */
    initialize(&c,&cfg,true,0);
    application_controller_button_edge(&c,GESTURE_SIDE_UP,true,1000);
    application_controller_tick(&c,1250);assert(requests==1 && requested_on);
    application_controller_tick(&c,1350);assert(requests==2);
    application_controller_button_edge(&c,GESTURE_SIDE_UP,false,1400);
    application_controller_tick(&c,2500);assert(requests==2);
}

static void click(struct application_controller *c, enum gesture_side side, uint64_t now)
{
 application_controller_button_edge(c,side,true,now);
 application_controller_button_edge(c,side,false,now+10);
 application_controller_tick(c,now+160);
}
static void test_disabled_suppresses_events(void)
{
 struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
 cfg.short_press_mode=DIMMER_SHORT_CUSTOM;cfg.single_up_action=DIMMER_ACTION_DISABLED;
 initialize(&c,&cfg,false,0);click(&c,GESTURE_SIDE_UP,10);
 assert(events==0 && requests==0 && !c.model.state.on);
 cfg.single_up_action=DIMMER_ACTION_EVENT_ONLY;
 initialize(&c,&cfg,false,0);click(&c,GESTURE_SIDE_UP,10);
 assert(events==2 && requests==0);
 cfg.double_up_action=DIMMER_ACTION_DISABLED;
 initialize(&c,&cfg,false,0);press_twice(&c,GESTURE_SIDE_UP,10);
 assert(events==0 && requests==0);
 /* An expired single must not flush the next, ultimately disabled double. */
 initialize(&c,&cfg,false,0);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,0);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,false,20);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,180);
 application_controller_tick(&c,180);
 assert(events==2);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,false,200);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,250);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,false,270);
 assert(events==2 && requests==0);
 /* Disabling clicks must not suppress an independent long-press gesture. */
 initialize(&c,&cfg,true,0);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,10);
 application_controller_tick(&c,300);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,false,310);
 assert(events==3 && requests>0);
}
static void test_reusable_timer_templates(void)
{
 for(unsigned i=0;i<4;i++) {
  struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
  cfg.short_press_mode=DIMMER_SHORT_CUSTOM;
  cfg.timer_duration_s=120;cfg.timer_2_duration_s=300;
  cfg.timer_3_duration_s=900;cfg.timer_4_duration_s=1800;
  const uint32_t durations[]={120,300,900,1800};
  cfg.single_up_action=(enum dimmer_action)(DIMMER_ACTION_TIMED_ON_1+i);
  cfg.double_down_action=cfg.single_up_action;
  cfg.auto_off_mode=DIMMER_AUTO_OFF_EVERY_ON;cfg.auto_off_duration_s=10;
  initialize(&c,&cfg,false,0);click(&c,GESTURE_SIDE_UP,100);
  assert(c.model.state.on && requested_on && c.model.state.off_timer_active);
  assert(dimmer_model_timer_remaining_s(&c.model,260)==durations[i]);
  click(&c,GESTURE_SIDE_UP,1000);
  assert(c.model.state.on && dimmer_model_timer_remaining_s(&c.model,1160)==durations[i]);
  /* Same template works independently of side and click count. */
  press_twice(&c,GESTURE_SIDE_DOWN,2000);
  assert(dimmer_model_timer_remaining_s(&c.model,2030)==durations[i]);
  cfg.single_up_action=(enum dimmer_action)(DIMMER_ACTION_TIMED_TOGGLE_1+i);
  initialize(&c,&cfg,false,0);click(&c,GESTURE_SIDE_UP,100);
  assert(c.model.state.on && dimmer_model_timer_remaining_s(&c.model,260)==durations[i]);
  click(&c,GESTURE_SIDE_UP,1000);
  assert(!c.model.state.on && !requested_on && !c.model.state.off_timer_active);
  /* Timed toggle also turns OFF an ordinary Zigbee ON, regardless of timer. */
  application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,2000);
  click(&c,GESTURE_SIDE_UP,3000);
  assert(!c.model.state.on && !requested_on && !c.model.state.off_timer_active);
 }
}
static void test_ramp_crosses_operating_minimum(void)
{
 struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
 cfg.min_level=50;cfg.rise_transition_ms=1000;cfg.fall_transition_ms=1000;
 initialize(&c,&cfg,false,0);
 application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,0);
 application_controller_tick(&c,100);assert(requested_on && requested_level==10);
 application_controller_tick(&c,1000);assert(requested_level==100);
 application_controller_command(&c,false,100,DIMMER_SOURCE_ZIGBEE,1000);
 application_controller_tick(&c,1900);assert(requested_on && requested_level==10);
 application_controller_tick(&c,2000);assert(!requested_on && !c.output_pending);
 cfg.ramp_start_level=20;cfg.ramp_end_level=5;
 initialize(&c,&cfg,false,0);
 application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,0);
 application_controller_tick(&c,0);assert(requested_on && requested_level==20);
 application_controller_tick(&c,1000);assert(requested_level==100);
 application_controller_command(&c,false,100,DIMMER_SOURCE_ZIGBEE,1000);
 application_controller_tick(&c,1999);assert(requested_on && requested_level>=5 && requested_level<10);
 application_controller_tick(&c,2000);assert(!requested_on);
}
static void test_timed_toggle_cancels_delayed_on(void)
{
 struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
 cfg.short_press_mode=DIMMER_SHORT_CUSTOM;
 cfg.single_up_action=DIMMER_ACTION_TIMED_TOGGLE_1;cfg.initial_on_delay_ms=5000;
 initialize(&c,&cfg,false,0);click(&c,GESTURE_SIDE_UP,100);
 assert(c.model.state.on && !c.output_on);
 click(&c,GESTURE_SIDE_UP,1000);
 application_controller_tick(&c,10000);
 assert(!c.model.state.on && !requested_on && !c.model.state.off_timer_active);
}

/* User-reported intermittent sequence: protect the expected behavior without
 * claiming a hardware cause was reproduced. */
static void test_toggle_after_timed_double(void)
{
 for(unsigned ramp=0;ramp<2;ramp++) {
  for(unsigned legacy=0;legacy<2;legacy++) {
   struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
   cfg.short_press_mode=DIMMER_SHORT_CUSTOM;cfg.single_up_action=DIMMER_ACTION_TOGGLE;
   cfg.double_up_action=legacy?DIMMER_ACTION_TIMED_ON:DIMMER_ACTION_TIMED_ON_2;
   cfg.rise_transition_ms=cfg.fall_transition_ms=ramp?1000:0;
   initialize(&c,&cfg,false,0);press_twice(&c,GESTURE_SIDE_UP,10);
   application_controller_tick(&c,1040);
   assert(c.model.state.on && c.model.state.off_timer_active && requested_on);
   click(&c,GESTURE_SIDE_UP,2000);
   assert(!c.model.state.on && !c.model.state.off_timer_active);
   application_controller_tick(&c,3160);
   assert(!requested_on && !c.output_on && !c.output_pending);
   application_controller_tick(&c,1000000);
   assert(!requested_on && !c.model.state.on);
  }
 }
}

static void test_minimum_on_off_skips_fade_duration(void)
{
 for(unsigned minimum=1;minimum<=30;minimum+=29) {
  for(unsigned endpoint=0;endpoint<2;endpoint++) {
   struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
   cfg.min_level=(uint8_t)minimum;
   cfg.ramp_start_level=cfg.ramp_end_level=(uint8_t)endpoint;
   cfg.rise_transition_ms=cfg.fall_transition_ms=1000;
   initialize(&c,&cfg,false,0);
   application_controller_command(&c,true,(uint8_t)minimum,DIMMER_SOURCE_ZIGBEE,10);
   assert(requests==1 && requested_on && requested_level==minimum && !c.output_pending);
   application_controller_command(&c,false,(uint8_t)minimum,DIMMER_SOURCE_ZIGBEE,20);
   assert(requests==2 && !requested_on && !c.output_on && !c.output_pending);
   /* The explicit initial delay remains separate from the fade duration. */
   cfg.initial_on_delay_ms=200;
   initialize(&c,&cfg,false,0);
   application_controller_command(&c,true,(uint8_t)minimum,DIMMER_SOURCE_ZIGBEE,10);
   assert(requests==0 && c.output_pending);
   application_controller_tick(&c,210);
   assert(requests==1 && requested_on && requested_level==minimum && !c.output_pending);
  }
 }
}
static void test_off_during_delayed_on_does_not_wait_for_fade(void)
{
 struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
 cfg.initial_on_delay_ms=5000;cfg.rise_transition_ms=cfg.fall_transition_ms=1000;
 initialize(&c,&cfg,false,0);
 application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,0);
 application_controller_command(&c,false,100,DIMMER_SOURCE_ZIGBEE,10);
 assert(!c.output_pending && !requested_on && !c.output_on);
 unsigned count=requests;application_controller_tick(&c,10000);assert(requests==count);
}

static void test_protection_cancels_all_on_paths_without_resuming(void)
{
 struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
 cfg.initial_on_delay_ms=500;cfg.rise_transition_ms=1000;cfg.fall_transition_ms=2000;
 cfg.auto_off_mode=DIMMER_AUTO_OFF_EVERY_ON;cfg.auto_off_duration_s=60;
 cfg.short_press_mode=DIMMER_SHORT_CUSTOM;cfg.single_up_action=DIMMER_ACTION_TIMED_ON_1;
 initialize(&c,&cfg,false,0);
 application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,10);
 assert(c.output_pending&&c.model.state.off_timer_active);
 application_controller_set_protection(&c,true,100);
 assert(!requested_on&&!c.output_on&&!c.output_pending&&!c.model.state.on&&!c.model.state.target_on);
 assert(!c.model.state.off_timer_active&&!c.model.state.restore_waiting);
 assert(c.model.state.level==100&&c.model.state.fault.code==DIMMER_FAULT_OUTPUT_INHIBITED);
 unsigned before=requests;uint32_t op=c.model.state.operation_id;
 application_controller_tick(&c,5000);assert(requests==before);
 for(enum dimmer_request_source source=DIMMER_SOURCE_ZIGBEE;source<=DIMMER_SOURCE_PHYSICAL_HOLD;source++){
  application_controller_command(&c,true,180,source,5100+source);
  assert(!requested_on&&!c.model.state.on&&!c.output_pending);
  assert(!c.model.state.off_timer_active);
 }
 application_controller_bypass_on(&c,5200);assert(!c.model.state.on&&!c.model.state.auto_off_bypassed);
 application_controller_restore_handoff(&c,true,200);assert(!c.model.state.on&&!c.output_on&&c.model.state.level==100);
 application_controller_feedback(&c,op,true,200);assert(!c.model.state.on&&!c.output_on);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,5300);
 application_controller_tick(&c,6000);assert(!c.hold_active[0]&&!c.model.state.on);
 application_controller_set_protection(&c,false,6100);before=requests;
 application_controller_tick(&c,10000);assert(requests==before&&!c.model.state.on);
 assert(!c.model.state.fault.active);
 application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,11000);
 assert(c.model.state.on&&c.output_pending);
 /* A trip during an actual ON fade must issue an immediate OFF too. */
 application_controller_tick(&c,12000);assert(c.output_on);
 application_controller_set_protection(&c,true,12010);assert(!requested_on&&!c.output_on&&!c.output_pending);
 /* A protection trip also cancels deferred power-on restore. */
 cfg.power_on_behavior=DIMMER_POWER_ON_AWAIT_ZIGBEE;
 initialize(&c,&cfg,true,0);assert(c.model.state.restore_waiting);
 application_controller_set_protection(&c,true,10);
 application_controller_set_protection(&c,false,20);
 application_controller_tick(&c,100000);assert(!c.model.state.on&&!c.model.state.restore_waiting);
}

int main(void){
 test_front_holds_leave_off_lamp_unchanged();
 test_front_holds_dim_on_lamp_in_each_direction();
 test_front_holds_do_not_bypass_pending_on_delay();
 test_front_hold_stops_when_accepted_state_turns_off();
 test_protection_cancels_all_on_paths_without_resuming();
 test_minimum_on_off_skips_fade_duration();
 test_off_during_delayed_on_does_not_wait_for_fade();
 test_disabled_suppresses_events();
 test_reusable_timer_templates();
 test_ramp_crosses_operating_minimum();
 test_timed_toggle_cancels_delayed_on();
 test_toggle_after_timed_double();
 requests=events=system_events=0;
 struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
 struct application_callbacks cb={.secondary_request=request,.gesture_event=event,.system_event=system_event};
 application_controller_init(&c,&cfg,false,100,&cb,&c,0);
 application_controller_command(&c,true,77,DIMMER_SOURCE_ZIGBEE,5);
 assert(requests==1&&requested_on&&requested_level==77);
 requests=0; events=0;
 application_controller_init(&c,&cfg,false,100,&cb,&c,0);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,10);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,false,20);
 application_controller_tick(&c,170);
 assert(events==2);assert(requests==1&&requested_on);assert(application_controller_state(&c)->on);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,1000);
 application_controller_tick(&c,1250);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,false,1750);
 assert(events==5);assert(requested_level>100);
 test_delayed_failure_and_off_cancel();
 test_delay_ramps_and_command_replacement();
 test_nonadjustable_holds_emit_events_without_output();
 test_hold_repeats_internal_level_steps();
 test_automatic_off_sources_and_bypass();
 test_single_timer_double_bypass_and_inverse();
 system_events=0;cfg.double_up_action=DIMMER_ACTION_TIMED_ON;cfg.timer_duration_s=1;
 application_controller_init(&c,&cfg,false,100,&cb,&c,0);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,10);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,false,20);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,30);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,false,40);
 application_controller_tick(&c,1040);
 assert(system_events==1&&last_system_event==APPLICATION_EVENT_TIMER_EXPIRED);
 /* Recovery chord cancels pending clicks and active dimming. */
 cfg=dimmer_config_defaults();requests=0;
 application_controller_init(&c,&cfg,false,100,&cb,&c,0);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,10);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,false,20);
 application_controller_cancel_gestures(&c);
 application_controller_tick(&c,1000);assert(requests==0);
 application_controller_restore_handoff(&c,true,100);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,1100);
 application_controller_tick(&c,1400);assert(requests>0);
 application_controller_cancel_gestures(&c);unsigned saved_requests=requests;
 application_controller_tick(&c,2400);assert(requests==saved_requests);
 /* Recovery restoration takes precedence over wait-for-Zigbee without changing config. */
 cfg.power_on_behavior=DIMMER_POWER_ON_AWAIT_ZIGBEE;
 application_controller_init(&c,&cfg,false,254,&cb,&c,0);
 application_controller_restore_handoff(&c,true,122);
 assert(c.model.state.on&&c.model.state.level==122&&!c.model.state.restore_waiting);
 assert(c.model.config.power_on_behavior==DIMMER_POWER_ON_AWAIT_ZIGBEE);
 /* Coordinator commands win over an in-flight local long hold. */
 cfg=dimmer_config_defaults();requests=0;
 application_controller_init(&c,&cfg,true,100,&cb,&c,0);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,10);
 application_controller_tick(&c,300);assert(requests>0);
 application_controller_command(&c,false,100,DIMMER_SOURCE_ZIGBEE,310);
 saved_requests=requests;application_controller_tick(&c,1000);
 assert(requests==saved_requests&&!application_controller_state(&c)->on);
 /* Do not advance gestures/held levels while a raw release is debouncing. */
 application_controller_init(&c,&cfg,true,100,&cb,&c,0);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,10);
 application_controller_tick(&c,300);saved_requests=requests;
 application_controller_tick_input(&c,1000,false);assert(requests==saved_requests);
 /* A release exactly at LONG threshold before its tick must not toggle. */
 cfg=dimmer_config_defaults();cfg.long_press_ms=500;requests=0;
 application_controller_init(&c,&cfg,false,100,&cb,&c,0);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,true,100);
 application_controller_tick(&c,575);
 application_controller_tick_input(&c,600,false);
 application_controller_button_edge(&c,GESTURE_SIDE_UP,false,600);
 application_controller_tick(&c,1000);assert(requests==0&&!application_controller_state(&c)->on);
 return 0;
}
