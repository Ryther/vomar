import asyncio
import copy
import struct
import pytest
import cbor2
from tools.firmware import read_boot_history as reader

UID=[0x11223344,0x55667788];MAIN='11'*32;RECOVERY='22'*32
HISTORY=dict(protocol=1,record_size=88,capacity=6,current_image=1,sequence=1,pending_reason=0,
 state=dict(initialized=True,loaded_valid=True,storage_valid=True,load_rc=88,decode_rc=0,save_rc=0,view_rc=0),
 entries=[dict(seq=1,image=1,reason=1,raw_reset_flags=0)])
class Transport:
 def __init__(self):self.frames=[];self.damage=None
 async def send_and_receive(self,frame):
  op,flags,size,group,seq,cmd=struct.unpack('>BBHHBB',frame[:8]);self.frames.append((op,group,cmd))
  assert op==8 and flags==0 and cmd==0 and frame[8:]==b'\xa0'
  value=dict(protocol=1,model='VIMAR30805',layout=2,uid=UID,loader_sha256=b'L'*32) if group==0x8040 else copy.deepcopy(HISTORY)
  if self.damage=='uid':value['uid']=[1,2]
  if self.damage=='unsupported':value={'rc':8}
  data=cbor2.dumps(value)
  return struct.pack('>BBHHBB',9,0,len(data),group,seq,cmd)+data
async def images():return [dict(slot=0,active=False,version='0.6.0',hash=MAIN),dict(slot=1,active=True,version='0.8.0',hash=RECOVERY)]

def test_read_only_export_checks_uid_and_hashes_twice_without_reset():
 transport=Transport();calls=[]
 async def states():calls.append(1);return await images()
 report=asyncio.run(reader.collect(transport,states,UID,MAIN,RECOVERY))
 assert len(calls)==2 and transport.frames==[(8,0x8040,0),(8,0x8041,0),(8,0x8040,0)]
 assert report['history']==HISTORY and report['uid']==UID and 'do not prove' in report['interpretation']

@pytest.mark.parametrize('damage',['uid','unsupported','main','recovery'])
def test_target_or_firmware_mismatch_aborts_before_history(damage):
 transport=Transport();transport.damage=damage
 async def states():
  data=await images()
  if damage=='main':data[0]['hash']='33'*32
  if damage=='recovery':data[1]['hash']='44'*32
  return data
 with pytest.raises((ValueError,RuntimeError)):asyncio.run(reader.collect(transport,states,UID,MAIN,RECOVERY))
 assert all(group!=0x8041 for _,group,_ in transport.frames)

@pytest.mark.parametrize('damage',['count','flags','bool','status','pending','format'])
def test_response_schema_is_bounded_and_does_not_infer_cause(damage):
 value=copy.deepcopy(HISTORY)
 if damage=='count':value['entries']*=7
 if damage=='flags':value['entries'][0]['raw_reset_flags']=-1
 if damage=='bool':value['state']['storage_valid']=1
 if damage=='status':value['state']['load_rc']=2**40
 if damage=='pending':value['pending_reason']=8
 if damage=='format':value['record_size']=89
 with pytest.raises(ValueError):reader.validate_history(value)


@pytest.mark.parametrize('field',['protocol','layout','uid'])
def test_identity_fields_require_integer_types_not_boolean_aliases(field):
 identity=dict(protocol=1,model='VIMAR30805',layout=2,uid=[1,2],loader_sha256=b'L'*32)
 if field=='uid':identity['uid']=[True,2]
 else:identity[field]=True
 with pytest.raises(ValueError):reader.verify_identity(identity,[1,2])


def test_offline_export_validation_and_cli_need_no_bluetooth(tmp_path):
 import json,subprocess,sys
 report=asyncio.run(reader.collect(Transport(),images,UID,MAIN,RECOVERY))
 assert reader.validate_export(report,UID,MAIN,RECOVERY)==report
 path=tmp_path/'diagnostic.json';path.write_text(json.dumps(report))
 result=subprocess.run([sys.executable,str(reader.ROOT/'tools/firmware/read_boot_history.py'),
  '--validate-export',str(path),'--expected-uid','11223344:55667788','--expected-main',MAIN,'--expected-recovery',RECOVERY],capture_output=True,text=True)
 assert result.returncode==0 and 'matches supplied' in result.stdout
 damaged=copy.deepcopy(report);damaged['images'][0]['hash']='33'*32
 with pytest.raises(ValueError):reader.validate_export(damaged,UID,MAIN,RECOVERY)
