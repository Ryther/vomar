"""Wired P-terminal behavior through the real controller and output model."""
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = r'''
#include "application_controller.h"
#include <assert.h>
#include <stdlib.h>
static unsigned outputs,events;
static void request(void *ctx,uint32_t op,bool on,uint8_t level) {
 outputs++;application_controller_feedback(ctx,op,on,level);
}
static void gesture(void *ctx,const struct gesture_event *e){(void)ctx;(void)e;events++;}
static void edge(struct application_controller *c,bool pressed,uint64_t now){
 application_controller_attachment_edge(c,pressed,now);
}
static void init(struct application_controller *c,struct dimmer_config *cfg,bool on,uint8_t level){
 struct application_callbacks cb={.secondary_request=request,.gesture_event=gesture};
 outputs=0;events=0;application_controller_init(c,cfg,on,level,&cb,c,0);
}
static void hold(struct application_controller *c,uint64_t at){edge(c,true,at);application_controller_tick(c,at+250);}
int main(int argc,char **argv){
 assert(argc==2);int scenario=atoi(argv[1]);
 struct application_controller c;struct dimmer_config cfg=dimmer_config_defaults();
 cfg.min_level=20;cfg.max_level=180;
 init(&c,&cfg,false,100);
 if(scenario==0){
  cfg.short_press_mode=DIMMER_SHORT_CUSTOM;cfg.single_up_action=DIMMER_ACTION_DISABLED;
  init(&c,&cfg,false,100);edge(&c,true,10);edge(&c,false,80);
  assert(c.model.state.on&&c.model.state.level==100&&outputs==1&&events==0);
  edge(&c,true,100);edge(&c,false,170);assert(!c.model.state.on&&outputs==2);
 } else if(scenario==1){
  init(&c,&cfg,true,100);hold(&c,10);assert(c.model.state.level==110&&outputs==1);
  application_controller_tick(&c,359);assert(outputs==1);
  application_controller_tick(&c,360);assert(c.model.state.level==120&&outputs==2);
  edge(&c,false,370);application_controller_tick(&c,800);assert(outputs==2&&events==0);
  hold(&c,900);assert(c.model.state.level==110);edge(&c,false,1200);
 } else if(scenario==2){
  hold(&c,10);application_controller_tick(&c,500);edge(&c,false,600);
  assert(!c.model.state.on&&outputs==0&&events==0);
  application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,610);
  hold(&c,620);assert(c.model.state.level==90);edge(&c,false,900);
  init(&c,&cfg,false,100);
  /* A long release observed without a tick must not become a short toggle. */
  edge(&c,true,700);edge(&c,false,1000);assert(!c.model.state.on&&outputs==0);
  application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,1010);
  hold(&c,1020);assert(c.model.state.level==90);
 } else if(scenario==3){
  init(&c,&cfg,true,180);hold(&c,10);assert(c.model.state.level==170);
  edge(&c,false,300);init(&c,&cfg,true,20);hold(&c,400);assert(c.model.state.level==30);
  edge(&c,false,700);application_controller_command(&c,true,20,DIMMER_SOURCE_ZIGBEE,800);
  hold(&c,900);assert(c.model.state.level==30);
 } else if(scenario==4){
  cfg.auto_off_mode=DIMMER_AUTO_OFF_PHYSICAL_ON_ONLY;cfg.auto_off_duration_s=30;
  init(&c,&cfg,false,100);edge(&c,true,10);edge(&c,false,80);
  assert(c.model.state.on&&c.model.state.off_timer_active);
  application_controller_tick(&c,30080);assert(!c.model.state.on);
 } else if(scenario==5){
  edge(&c,true,10);application_controller_cancel_gestures(&c);edge(&c,false,80);
  application_controller_tick(&c,1000);assert(outputs==0&&!c.model.state.on);
  edge(&c,true,1010);edge(&c,false,1080);assert(c.model.state.on);
  hold(&c,1100);assert(c.model.state.level==110);
  application_controller_command(&c,true,150,DIMMER_SOURCE_ZIGBEE,1400);
  unsigned saved=outputs;application_controller_tick(&c,2000);edge(&c,false,2100);
  assert(c.model.state.level==150&&outputs==saved);
  hold(&c,2200);assert(c.model.state.level==160); /* Cancelled release cannot reverse. */
 } else if(scenario==6){
  init(&c,&cfg,true,100);hold(&c,10);assert(c.model.state.level==110);
  application_controller_set_protection(&c,true,300);
  application_controller_set_protection(&c,false,350);
  unsigned saved=outputs;edge(&c,false,400);application_controller_tick(&c,1000);
  assert(!c.model.state.on&&outputs==saved);
  edge(&c,true,1100);edge(&c,false,1180);assert(c.model.state.on);
 } else if(scenario==7){
  init(&c,&cfg,true,100);hold(&c,10);assert(c.model.state.level==110);
  application_controller_button_edge(&c,GESTURE_SIDE_DOWN,true,300);
  application_controller_tick(&c,550);assert(c.model.state.level==100);
  edge(&c,false,560);application_controller_button_edge(&c,GESTURE_SIDE_DOWN,false,570);
  unsigned saved=outputs;application_controller_tick(&c,900);assert(outputs==saved);
  /* A fresh auxiliary press cancels a pending front click. */
  application_controller_button_edge(&c,GESTURE_SIDE_UP,true,1000);
  application_controller_button_edge(&c,GESTURE_SIDE_UP,false,1010);
  edge(&c,true,1020);application_controller_tick(&c,1160);assert(outputs==saved);
  edge(&c,false,1200);assert(!c.model.state.on&&outputs==saved+1);
 } else if(scenario==8){
  cfg.output_mode=DIMMER_OUTPUT_FIXED_LEVEL;
  init(&c,&cfg,true,100);hold(&c,10);edge(&c,false,400);assert(outputs==0);
  edge(&c,true,500);edge(&c,false,550);assert(!c.model.state.on&&outputs==1);
 } else if(scenario==9){
  cfg.power_on_behavior=DIMMER_POWER_ON_AWAIT_ZIGBEE;init(&c,&cfg,false,100);
  assert(c.model.state.restore_waiting);edge(&c,true,10);assert(!c.model.state.restore_waiting);
  edge(&c,false,80);assert(c.model.state.on);
 } else if(scenario==10){
  init(&c,&cfg,true,100);edge(&c,true,10);
  application_controller_cancel_attachment(&c);
  edge(&c,true,20);application_controller_tick(&c,500);edge(&c,false,600);
  assert(outputs==0&&c.model.state.level==100);
  hold(&c,700);assert(c.model.state.level==110);
 } else if(scenario==11){
  init(&c,&cfg,true,100);edge(&c,true,10);
  application_controller_attachment_settled(&c,false);
  application_controller_tick(&c,270);assert(outputs==0);
  edge(&c,false,259);assert(!c.model.state.on&&outputs==1);
  /* Pause ongoing steps as soon as release debounce starts. */
  application_controller_attachment_settled(&c,true);
  application_controller_command(&c,true,100,DIMMER_SOURCE_ZIGBEE,300);
  hold(&c,400);assert(c.model.state.level==110);
  unsigned saved=outputs;
  application_controller_attachment_settled(&c,false);
  application_controller_tick(&c,800);assert(outputs==saved);
  edge(&c,false,749);assert(outputs==saved);
 } else if(scenario==12){
  cfg.long_press_ms=300;cfg.level_step=3;cfg.level_step_period_ms=50;
  cfg.min_level=95;cfg.max_level=105;init(&c,&cfg,true,100);
  edge(&c,true,10);application_controller_tick(&c,309);assert(outputs==0);
  application_controller_tick(&c,310);assert(c.model.state.level==103);
  application_controller_tick(&c,359);assert(c.model.state.level==103);
  application_controller_tick(&c,360);assert(c.model.state.level==105);
  application_controller_tick(&c,410);assert(c.model.state.level==105);
  edge(&c,false,420);edge(&c,true,500);application_controller_tick(&c,800);
  assert(c.model.state.level==102);
  application_controller_tick(&c,850);application_controller_tick(&c,900);
  application_controller_tick(&c,950);assert(c.model.state.level==95);
 }
 return 0;
}
'''


@pytest.fixture(scope="module")
def controller_runner(tmp_path_factory):
    directory = tmp_path_factory.mktemp("attachment-controller")
    source = directory / "test.c"
    source.write_text(SOURCE)
    runner = directory / "test"
    names = ["application_controller", "dimmer_config", "dimmer_model",
             "gesture_classifier", "local_action_mapper", "led_controller"]
    subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I",
                    str(ROOT / "firmware/src"), str(source),
                    *(str(ROOT / "firmware/src" / f"{name}.c") for name in names),
                    "-o", str(runner)], check=True)
    return runner


@pytest.mark.parametrize("scenario", range(13), ids=[
    "short-toggle-independent-of-front-actions", "hold-repeat-release-reverse",
    "hold-off-and-delayed-release", "endpoint-direction", "physical-auto-off",
    "cancel-and-zigbee-suppress-until-release", "protection-cancels",
    "front-attachment-arbitration", "fixed-output-no-hold", "cancel-restore",
    "explicit-cancel-blocks-duplicate-press", "release-debounce-pauses-hold", "configured-threshold-rate-and-limits",
])
def test_wired_attachment_behavior(controller_runner, scenario):
    subprocess.run([str(controller_runner), str(scenario)], check=True)
