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
