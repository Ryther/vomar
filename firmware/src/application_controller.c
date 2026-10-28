#include "application_controller.h"
#include "local_action_mapper.h"
#include <string.h>
/* Output samples are command estimates, never measurements of the lamp. */
static void emit_output(struct application_controller *c,bool on,uint8_t level)
{
 c->emitting_output=true;
 if(c->callbacks.secondary_request)c->callbacks.secondary_request(c->context,c->model.state.operation_id,on,level);
 c->emitting_output=false;
}
static void advance_output(struct application_controller *c,uint64_t now)
{
 if(!c->output_pending||now<c->output_start_ms)return;
 uint64_t elapsed=now-c->output_start_ms;
 bool done=elapsed>=c->output_duration_ms;
 int value=done?c->ramp_to:(int)c->ramp_from+
     ((int)c->ramp_to-(int)c->ramp_from)*(int64_t)elapsed/c->output_duration_ms;
 bool on=value>0 && !(done && !c->ramp_target_on);
 uint8_t level=on?(uint8_t)value:c->model.state.level;
 if(on&&c->model.config.output_mode==DIMMER_OUTPUT_DIMMABLE){
     if(!c->ramp_cross_min && level<c->model.config.min_level)level=c->model.config.min_level;
     if(level>c->model.config.max_level)level=c->model.config.max_level;
 }
 if(on!=c->output_on||(on&&level!=c->output_level))emit_output(c,on,level);
 if(done)c->output_pending=false;
}
static void schedule_output(struct application_controller *c,uint64_t now,bool immediate)
{
 bool on=c->model.state.target_on && !c->protection_blocked;
 uint8_t level=c->model.state.target_level;
 if(!immediate&&c->output_pending&&c->ramp_target_on==on&&(!on||c->ramp_to==level)){
     (void)dimmer_model_apply_effective(&c->model,c->model.state.operation_id,on,level);
     if(c->callbacks.state_changed)c->callbacks.state_changed(c->context);
     return;
 }
 c->ramp_target_on=on;
 c->ramp_cross_min=!on || !c->output_on;
 c->ramp_from=c->output_on?c->output_level:0;c->ramp_to=on?level:0;
 if(on && !c->output_on){
  c->ramp_from=c->model.config.ramp_start_level;
  if(c->ramp_from>level)c->ramp_from=level;
 }
 if(!on){
  c->ramp_to=c->model.config.ramp_end_level;
  if(c->ramp_to>c->ramp_from)c->ramp_to=c->ramp_from;
 }
 c->output_start_ms=now+(!immediate&&on&&!c->output_on?c->model.config.initial_on_delay_ms:0);
 c->output_duration_ms=(immediate||c->model.config.output_mode!=DIMMER_OUTPUT_DIMMABLE)?0:(on && !c->output_on ?
     c->model.config.rise_transition_ms:c->ramp_to>c->ramp_from?
     c->model.config.rise_transition_ms:c->model.config.fall_transition_ms);
 /* At the operating minimum a fade becomes a silent wait rather than a
  * visible transition. Keep the separately configured initial ON delay. */
 bool minimum_on=on && !c->output_on && level<=c->model.config.min_level;
 bool minimum_off=!on && (!c->output_on || c->output_level<=c->model.config.min_level);
 if(minimum_on || minimum_off || c->ramp_from==c->ramp_to)c->output_duration_ms=0;
 /* Accepted state is independent of delayed/ramped output completion. */
 (void)dimmer_model_apply_effective(&c->model,c->model.state.operation_id,on,level);
 c->output_pending=true;
 if(c->callbacks.state_changed)c->callbacks.state_changed(c->context);
 if(c->output_start_ms==now&&c->output_duration_ms==0){
     emit_output(c,on,level);c->output_pending=false;
 }
}
static void send_request_mode(struct application_controller *c,bool on,uint8_t level,uint64_t now,bool immediate)
{
 if(c->protection_blocked){on=false;immediate=true;}
 (void)dimmer_model_request(&c->model,on,level,now);
 schedule_output(c,now,immediate);
}
static void send_request(struct application_controller *c,bool on,uint8_t level,uint64_t now)
{send_request_mode(c,on,level,now,false);}
static void ordinary_request(struct application_controller *c,bool on,uint8_t level,
 enum dimmer_request_source source,uint64_t now)
{
 send_request_mode(c,on,level,now,source==DIMMER_SOURCE_ZIGBEE_LEVEL||source==DIMMER_SOURCE_PHYSICAL_HOLD);
 if(!c->model.state.target_on||c->model.state.auto_off_bypassed)return;
 bool starts=c->model.config.auto_off_mode==DIMMER_AUTO_OFF_EVERY_ON||
  (c->model.config.auto_off_mode==DIMMER_AUTO_OFF_PHYSICAL_ON_ONLY&&(source==DIMMER_SOURCE_PHYSICAL||source==DIMMER_SOURCE_PHYSICAL_HOLD));
 if(starts)dimmer_model_start_off_timer(&c->model,now,c->model.config.auto_off_duration_s*1000U);
}
static void timed_on(struct application_controller *c,uint64_t now,uint32_t duration_s)
{send_request(c,true,c->model.state.level,now);if(c->model.state.on)dimmer_model_start_off_timer(&c->model,now,duration_s*1000U);}
static uint32_t template_duration(const struct dimmer_config *cfg,unsigned index)
{
 switch(index){case 1:return cfg->timer_2_duration_s;case 2:return cfg->timer_3_duration_s;
 case 3:return cfg->timer_4_duration_s;default:return cfg->timer_duration_s;}
}
static void bypass_on(struct application_controller *c,uint64_t now)
{send_request(c,true,c->model.state.level,now);if(!c->protection_blocked)dimmer_model_bypass_off_timer(&c->model);}
static bool front_hold_allowed(const struct application_controller *c)
{
 /* Accepted ON can precede applied output during the initial delay. */
 return !c->protection_blocked && c->model.config.output_mode==DIMMER_OUTPUT_DIMMABLE &&
     c->model.state.on && c->output_on;
}
static void classified(const struct gesture_event *e,void *ctx)
{
 struct application_controller *c=ctx;
 /* A press cannot be published before we know whether its click is disabled. */
 if(e->type==GESTURE_EVENT_PRESS){
  uint8_t *count=&c->queued_press_count[e->side];
  if(*count<2)c->queued_press[e->side][(*count)++]=*e;
  return;
 }
 enum dimmer_action a=local_action_for(&c->model.config,e->type,e->side);
 bool disabled=a==DIMMER_ACTION_DISABLED;
 if(!disabled && c->callbacks.gesture_event){
  for(uint8_t i=0;i<c->queued_press_count[e->side];i++)
   c->callbacks.gesture_event(c->context,&c->queued_press[e->side][i]);
  c->callbacks.gesture_event(c->context,e);
 }
 c->queued_press_count[e->side]=0;
 if(disabled)return;
 if(e->type==GESTURE_EVENT_LONG){if(!front_hold_allowed(c))return;int level=(int)c->model.state.level+local_action_level_delta(&c->model.config,e->side);if(level<1)level=1;if(level>254)level=254;ordinary_request(c,true,(uint8_t)level,DIMMER_SOURCE_PHYSICAL_HOLD,c->now_ms);c->hold_active[e->side]=true;c->next_level_step_ms[e->side]=c->now_ms+c->model.config.level_step_period_ms;return;}
 if(e->type==GESTURE_EVENT_RELEASE){c->hold_active[e->side]=false;return;}
 if(a>=DIMMER_ACTION_TIMED_ON_1 && a<=DIMMER_ACTION_TIMED_TOGGLE_4){
  bool toggle=a>=DIMMER_ACTION_TIMED_TOGGLE_1;
  unsigned index=(unsigned)(a-(toggle?DIMMER_ACTION_TIMED_TOGGLE_1:DIMMER_ACTION_TIMED_ON_1));
  if(toggle && c->model.state.on)ordinary_request(c,false,c->model.state.level,DIMMER_SOURCE_PHYSICAL,c->now_ms);
  else timed_on(c,c->now_ms,template_duration(&c->model.config,index));
  return;
 }
 switch(a){case DIMMER_ACTION_TOGGLE:ordinary_request(c,!c->model.state.on,c->model.state.level,DIMMER_SOURCE_PHYSICAL,c->now_ms);break;case DIMMER_ACTION_ON:ordinary_request(c,true,c->model.state.level,DIMMER_SOURCE_PHYSICAL,c->now_ms);break;case DIMMER_ACTION_OFF:ordinary_request(c,false,c->model.state.level,DIMMER_SOURCE_PHYSICAL,c->now_ms);break;case DIMMER_ACTION_TIMED_ON:timed_on(c,c->now_ms,c->model.config.timer_duration_s);break;case DIMMER_ACTION_BYPASS_ON:bypass_on(c,c->now_ms);break;default:break;}
}
void application_controller_cancel_attachment(struct application_controller *c)
{
 /* Keep the logical assertion until release, so cancellation cannot turn the
  * remaining hold or duplicate asserted edges into a fresh click. */
 if(c->attachment_pressed)c->attachment_cancelled=true;
}
void application_controller_attachment_settled(struct application_controller *c,bool settled)
{c->attachment_settled=settled;}
static void attachment_step(struct application_controller *c,uint64_t now)
{
 int level=(int)c->model.state.level+
     (c->attachment_down?-(int)c->model.config.level_step:(int)c->model.config.level_step);
 if(level<c->model.config.min_level)level=c->model.config.min_level;
 if(level>c->model.config.max_level)level=c->model.config.max_level;
 ordinary_request(c,true,(uint8_t)level,DIMMER_SOURCE_PHYSICAL_HOLD,now);
}
static void attachment_tick(struct application_controller *c,uint64_t now)
{
 if(!c->attachment_settled||!c->attachment_pressed||c->attachment_cancelled||c->protection_blocked)return;
 if(!c->attachment_long){
  if(now-c->attachment_pressed_ms<c->model.config.long_press_ms)return;
  c->attachment_long=true;
  /* Stock wired LONG does not turn an OFF light on. RELEASE still reverses
   * direction, independently of whether this hold produced output. */
  if(!c->model.state.on||c->model.config.output_mode!=DIMMER_OUTPUT_DIMMABLE)return;
  if(c->model.state.level<=c->model.config.min_level)c->attachment_down=false;
  if(c->model.state.level>=c->model.config.max_level)c->attachment_down=true;
  attachment_step(c,now);
  c->attachment_next_step_ms=now+c->model.config.level_step_period_ms;
 }else if(c->model.state.on&&c->model.config.output_mode==DIMMER_OUTPUT_DIMMABLE&&
          now>=c->attachment_next_step_ms&&c->attachment_next_step_ms){
  attachment_step(c,now);
  c->attachment_next_step_ms=now+c->model.config.level_step_period_ms;
 }
}
void application_controller_attachment_edge(struct application_controller *c,bool pressed,uint64_t now)
{
 c->now_ms=now;
 if(pressed){
  if(c->attachment_pressed)return;
  application_controller_cancel_gestures(c);
  dimmer_model_cancel_restore(&c->model);
  c->attachment_pressed=true;c->attachment_cancelled=c->protection_blocked;
  c->attachment_long=false;c->attachment_pressed_ms=now;c->attachment_next_step_ms=0;
  return;
 }
 if(!c->attachment_pressed)return;
 c->attachment_pressed=false;
 if(c->attachment_cancelled){c->attachment_cancelled=false;return;}
 bool was_long=c->attachment_long||now-c->attachment_pressed_ms>=c->model.config.long_press_ms;
 if(was_long)c->attachment_down=!c->attachment_down;
 else ordinary_request(c,!c->model.state.on,c->model.state.level,DIMMER_SOURCE_PHYSICAL,now);
}
void application_controller_init(struct application_controller *c,const struct dimmer_config *cfg,bool on,uint8_t level,const struct application_callbacks *cb,void *ctx,uint64_t now)
{memset(c,0,sizeof(*c));c->callbacks=*cb;c->context=ctx;dimmer_model_init_at(&c->model,cfg,on,level,now);c->output_on=c->model.state.on;c->output_level=c->model.state.level;c->attachment_settled=true;gesture_classifier_init(&c->gestures,cfg,classified,c);led_controller_init(&c->leds,cfg);}
void application_controller_button_edge(struct application_controller *c,enum gesture_side side,bool pressed,uint64_t now){c->now_ms=now;if(pressed){application_controller_cancel_attachment(c);dimmer_model_cancel_restore(&c->model);}gesture_classifier_edge(&c->gestures,side,pressed,now);}
void application_controller_command(struct application_controller *c,bool on,uint8_t level,enum dimmer_request_source source,uint64_t now){c->now_ms=now;if(source==DIMMER_SOURCE_ZIGBEE||source==DIMMER_SOURCE_ZIGBEE_LEVEL)application_controller_cancel_gestures(c);ordinary_request(c,on,level,source,now);}
void application_controller_bypass_on(struct application_controller *c,uint64_t now){c->now_ms=now;bypass_on(c,now);}
void application_controller_tick_input(struct application_controller *c,uint64_t now,bool settled){c->now_ms=now;attachment_tick(c,now);if(!front_hold_allowed(c))memset(c->hold_active,0,sizeof(c->hold_active));if(settled){gesture_classifier_tick(&c->gestures,now);for(enum gesture_side side=GESTURE_SIDE_UP;side<GESTURE_SIDE_COUNT;side++){if(c->hold_active[side]&&now>=c->next_level_step_ms[side]){int level=(int)c->model.state.level+local_action_level_delta(&c->model.config,side);if(level<1)level=1;if(level>254)level=254;ordinary_request(c,true,(uint8_t)level,DIMMER_SOURCE_PHYSICAL_HOLD,now);c->next_level_step_ms[side]+=c->model.config.level_step_period_ms;}}}bool timer=c->model.state.off_timer_active;bool restore=c->model.state.restore_waiting;if(dimmer_model_tick(&c->model,now)){if(c->callbacks.system_event)c->callbacks.system_event(c->context,timer?APPLICATION_EVENT_TIMER_EXPIRED:APPLICATION_EVENT_STATE_CORRECTION,0);schedule_output(c,now,false);}else if(restore&&!c->model.state.restore_waiting&&c->callbacks.system_event)c->callbacks.system_event(c->context,APPLICATION_EVENT_STATE_CORRECTION,0);advance_output(c,now);}
void application_controller_feedback(struct application_controller *c,uint32_t op,bool on,uint8_t level){if(c->protection_blocked&&on)return;if(c->emitting_output){if(op==c->model.state.operation_id){c->output_on=on;if(on)c->output_level=level;}return;}bool correction=op==c->model.state.operation_id&&(on!=c->model.state.target_on||level!=c->model.state.target_level);if(dimmer_model_apply_effective(&c->model,op,on,level)&&correction&&c->callbacks.system_event)c->callbacks.system_event(c->context,APPLICATION_EVENT_STATE_CORRECTION,0);}
const struct dimmer_state *application_controller_state(const struct application_controller *c){return dimmer_model_state(&c->model);}

void application_controller_cancel_gestures(struct application_controller *c)
{
 application_controller_cancel_attachment(c);
 memset(c->gestures.sides,0,sizeof(c->gestures.sides));
 memset(c->queued_press_count,0,sizeof(c->queued_press_count));
 memset(c->hold_active,0,sizeof(c->hold_active));
}
void application_controller_restore_handoff(struct application_controller *c,bool on,uint8_t level)
{
 if(c->protection_blocked)return;
 dimmer_model_cancel_restore(&c->model);
 c->model.state.on=c->model.state.target_on=on;
 c->model.state.level=c->model.state.target_level=level;
 c->model.previous_on=on;c->model.previous_level=level;
 c->output_on=on;c->output_level=level;c->output_pending=false;
}

void application_controller_tick(struct application_controller *c,uint64_t now){application_controller_tick_input(c,now,true);}

void application_controller_output_failed(struct application_controller *c,uint32_t op,enum dimmer_fault_code code)
{
 if(op!=c->model.state.operation_id||c->protection_blocked)return;
 c->output_pending=false;
 dimmer_model_fail(&c->model,op,code);
 (void)dimmer_model_apply_effective(&c->model,op,c->output_on,c->output_level);
 if(c->callbacks.state_changed)c->callbacks.state_changed(c->context);
}

void application_controller_set_protection(struct application_controller *c,bool blocked,uint64_t now)
{
 if(c->protection_blocked==blocked)return;
 c->protection_blocked=blocked;c->now_ms=now;
 /* Clearing permits fresh commands only; discard gestures queued while blocked. */
 application_controller_cancel_gestures(c);
 if(!blocked){
  dimmer_model_clear_fault(&c->model,DIMMER_FAULT_OUTPUT_INHIBITED);
  if(c->callbacks.state_changed)c->callbacks.state_changed(c->context);
  return;
 }
 c->output_pending=false;c->ramp_target_on=false;
 uint32_t op=dimmer_model_request(&c->model,false,c->model.state.level,now);
 (void)dimmer_model_apply_effective(&c->model,op,false,c->model.state.level);
 c->output_on=false;
 emit_output(c,false,c->model.state.level);
 dimmer_model_fail(&c->model,op,DIMMER_FAULT_OUTPUT_INHIBITED);
 if(c->callbacks.state_changed)c->callbacks.state_changed(c->context);
 if(c->callbacks.system_event)c->callbacks.system_event(c->context,APPLICATION_EVENT_FAULT,DIMMER_FAULT_OUTPUT_INHIBITED);
}
