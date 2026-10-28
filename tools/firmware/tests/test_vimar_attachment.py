"""Synthetic pulse trains exercise the wired input without hardware or a broker."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]

class AttachmentInputTests(unittest.TestCase):
    def test_pulse_capture_and_stable_wired_edges(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.c"
            source.write_text(r'''
#include "vimar_attachment.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
static uint32_t tick(uint64_t ms){return (uint32_t)(ms*32768/1000);}
static struct vimar_attachment_sample poll(struct vimar_attachment_input *s,
 struct vimar_attachment_capture *c,uint64_t ms){return vimar_attachment_tick(s,c,tick(ms),ms);}
static void pulse(struct vimar_attachment_capture *c,uint64_t ms){
 vimar_attachment_edge(c,false,tick(ms));vimar_attachment_edge(c,true,tick(ms+5));
}
static void train(unsigned hz){
 struct vimar_attachment_capture c={0};struct vimar_attachment_input s={0};
 poll(&s,&c,0);assert(!poll(&s,&c,50).pressed);
 bool pressed=false,released=false;
 uint64_t prior=UINT64_MAX;
 for(uint64_t ms=60;ms<=450;ms++){
  uint64_t index=(ms-60)*hz/1000;
  if(ms<300 && index!=prior){pulse(&c,ms);prior=index;}
  struct vimar_attachment_sample a=poll(&s,&c,ms+5);
  if(a.changed){if(a.pressed){assert(!pressed);pressed=true;}else{assert(pressed);released=true;}}
 }
 assert(pressed&&released&&!s.pressed);
}
int main(void){
 struct vimar_attachment_capture c={0};
 vimar_attachment_edge(&c,true,100);assert(!c.pulses);
 vimar_attachment_edge(&c,false,200);vimar_attachment_edge(&c,true,298);assert(!c.pulses);
 vimar_attachment_edge(&c,false,300);vimar_attachment_edge(&c,true,399);assert(c.pulses==1);
 /* Repeated HIGH without a new LOW cannot create phantom pulses. */
 vimar_attachment_edge(&c,true,600);assert(c.pulses==1);
 c=(struct vimar_attachment_capture){0};
 vimar_attachment_edge(&c,false,UINT32_MAX-40);vimar_attachment_edge(&c,true,58);assert(c.pulses==1);
 c.pulses=UINT32_MAX;vimar_attachment_edge(&c,false,100);vimar_attachment_edge(&c,true,200);assert(c.pulses==0&&c.have_pulse);
 train(50);train(60);train(100);train(120); /* Cycle and half-cycle trains. */
 c=(struct vimar_attachment_capture){0};struct vimar_attachment_input s={0};
 poll(&s,&c,0);poll(&s,&c,50);pulse(&c,60);
 for(uint64_t ms=65;ms<180;ms+=5)assert(!poll(&s,&c,ms).changed);
 /* Boot-held pulse train remains suppressed until a stable quiet interval. */
 c=(struct vimar_attachment_capture){0};s=(struct vimar_attachment_input){0};
 for(uint64_t ms=0;ms<250;ms+=10){pulse(&c,ms);assert(!poll(&s,&c,ms+5).changed);}
 for(uint64_t ms=255;ms<330;ms+=5)assert(!poll(&s,&c,ms).changed);
 assert(s.enabled);
 bool pressed=false;
 for(uint64_t ms=350;ms<550;ms+=5){
  if((ms-350)%20==0)pulse(&c,ms);
  struct vimar_attachment_sample a=poll(&s,&c,ms+5);if(a.changed&&a.pressed)pressed=true;
 }
 assert(pressed);
 /* Scheduler stalls cancel, never turn a stale captured pulse into a click. */
 struct vimar_attachment_sample a=poll(&s,&c,900);assert(a.cancel&&!a.changed&&!a.pressed);
 for(uint64_t ms=925;ms<1025;ms+=25)assert(!poll(&s,&c,ms).changed);
 /* GPIO timestamp rollover does not falsely preserve a released train. */
 c=(struct vimar_attachment_capture){.have_pulse=true,.last_pulse=UINT32_MAX-20};
 s=(struct vimar_attachment_input){0};
 a=vimar_attachment_tick(&s,&c,50,0);assert(!a.pressed);
 a=vimar_attachment_tick(&s,&c,2000,50);assert(!a.pressed);
 puts("attachment pulse checks passed");return 0;
}
''')
            executable = Path(directory) / "input"
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "firmware/src"), str(source), str(ROOT / "firmware/src/vimar_attachment.c"), "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)
