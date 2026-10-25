import asyncio
import pytest
from vomar_updater.core.fleet import Broker,Network,Scheduler
from vomar_updater.adapters.credentials import Credentials


def test_plaintext_consent_and_overlapping_topics_are_rejected():
    with pytest.raises(ValueError):Broker('tcp://192.0.2.4',(Network('a','A','zigbee2mqtt'),)).validate()
    Broker('tcp://192.0.2.4',(Network('a','A','zigbee2mqtt'),),allow_plaintext=True).validate()
    with pytest.raises(ValueError):Broker('ssl://broker.example',(Network('a','A','z'),Network('b','B','z/other'))).validate()


def test_parallel_scheduler_preserves_network_and_ble_exclusion():
    async def run():
        s=Scheduler();active=set();seen=[]
        async def work(lane):
            assert lane not in active;active.add(lane);seen.append(lane);await asyncio.sleep(.01);active.remove(lane)
        await asyncio.gather(*(s.run(lane,lambda lane=lane:work(lane)) for lane in ['ble','ble','network:a','network:b','network:a']))
        assert len(seen)==5
    asyncio.run(run())


def test_no_plaintext_credential_fallback():
    class Missing:
        priority=0
    with pytest.raises(ValueError):Credentials(Missing()).set('broker','user','secret')


def test_retained_or_wrong_network_response_cannot_complete_request():
    from vomar_updater.adapters.mqtt import MqttBridge
    import json
    async def scenario():
        profile=Broker('ssl://broker.example',(Network('a','A','z/a'),Network('b','B','z/b')))
        bridge=MqttBridge(profile);future=asyncio.get_running_loop().create_future();bridge.pending['tx']=('z/a/bridge/response/device/ota_update/check','0x0000000000000001',future)
        data=json.dumps({'transaction':'tx','status':'ok','data':{'id':'0x0000000000000001','update_available':True}}).encode()
        bridge.feed('z/a/bridge/response/device/ota_update/check',data,True);assert not future.done()
        bridge.feed('z/b/bridge/response/device/ota_update/check',data,False);assert not future.done()
        bridge.feed('z/a/bridge/response/device/ota_update/check',data,False);assert future.done()
    asyncio.run(scenario())


def test_ambiguous_or_malformed_discovery_revokes_prior_identity():
    import json
    from vomar_updater.adapters.mqtt import MqttBridge
    b=MqttBridge(Broker('ssl://broker.example',(Network('a','A','z'),)))
    b.connected=True
    row={'ieee_address':'0x0000000000000001','friendly_name':'Fixture','model_id':'Vimar30805','definition':{'vendor':'OpenVimar','model':'30805-custom','supports_ota':True}}
    def feed(rows):b.feed('z/bridge/devices',json.dumps(rows).encode())
    feed([row]);assert b.target('a',row['ieee_address'])==row
    b.observations[('a',row['ieee_address'])]={'old':True}
    for rows in ([row,row],[row,{**row,'ieee_address':'0x0000000000000002'}],[{**row,'definition':None}],[{**row,'ieee_address':1}],{'invalid':'shape'}):
        feed(rows)
        with pytest.raises(ValueError):b.target('a',row['ieee_address'])
        assert not b.observations


def test_service_mixed_batch_parallel_routes_and_partial_failure_are_durable(tmp_path,monkeypatch):
    from dataclasses import dataclass
    from types import SimpleNamespace
    from vomar_updater.service import Service
    from vomar_updater.core.engine import Identity
    from vomar_updater.core.zigbee import ZigbeeReview
    from test_engine import package
    import time
    async def scenario():
        s=Service(tmp_path);s.package=package();s.mqtt=SimpleNamespace(close=lambda:None)
        active=set();overlap=[]
        class Zigbee:
            def __init__(self,*args):pass
            async def inspect(self,p,n,i,source):return ZigbeeReview(i,p.digest,n,i,source,1,time.monotonic()+300)
            def approve(self,r):return r.token
            async def execute(self,p,r,c):
                async def operation():
                    assert r.network not in active;active.add(r.network);overlap.append(len(active));await asyncio.sleep(.01);active.remove(r.network)
                    if r.network=='b':raise ConnectionError('Synthetic interruption')
                    return 'session-'+r.ieee
                return await s.scheduler.run('network:'+r.network,operation)
        monkeypatch.setattr('vomar_updater.core.zigbee.ZigbeeEngine',Zigbee)
        for i,n in enumerate(['a','b','a']):s.registry.save({'id':str(i),'name':'Synthetic '+str(i),'room':'','ble':'','network':n,'ieee':f'0x{i+1:016x}'})
        result=await s.dispatch('fleet.preview',{'ids':['0','1','2'],'mode':'network-parallel','transport':'zigbee','source':'https://example.org/fixture.ota'})
        outcome=await s.dispatch('execute',result)
        assert max(overlap)==2 and outcome['state']=='paused'
        assert [j['state'] for j in outcome['jobs']]==['verified','interrupted','verified']
        assert s.batches.list()[0]==outcome and not s.reviews
        s.store.close()
    asyncio.run(scenario())
