"""Disposable localhost broker only; never reads household profiles."""
import asyncio,json,os,socket,subprocess,time
from pathlib import Path
import pytest
from vomar_updater.adapters.mqtt import MqttBridge
from vomar_updater.core.fleet import Broker,Network

@pytest.mark.skipif(not os.environ.get('MOSQUITTO_BINARY'),reason='Set MOSQUITTO_BINARY to a disposable test broker binary')
def test_real_broker_discovery_retained_and_disconnect(tmp_path):
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    conf=tmp_path/'broker.conf';conf.write_text(f'listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n')
    broker=subprocess.Popen([os.environ['MOSQUITTO_BINARY'],'-c',str(conf)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+5
        while True:
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1):break
            except OSError:
                if time.monotonic()>deadline:raise
                time.sleep(.05)
        async def scenario():
            b=MqttBridge(Broker(f'tcp://127.0.0.1:{port}',(Network('test','Test','fixture'),),allow_plaintext=True));await b.connect()
            row={'ieee_address':'0x0000000000000001','friendly_name':'Synthetic','model_id':'Vimar30805','definition':{'vendor':'OpenVimar','model':'30805-custom','supports_ota':True}}
            await b.publish('fixture/bridge/devices',[row]);deadline=time.monotonic()+3
            while not b.devices and time.monotonic()<deadline:await asyncio.sleep(.05)
            assert b.target('test',row['ieee_address'])==row
            await b.close();assert not b.connected and not b.devices
        asyncio.run(scenario())
    finally:broker.terminate();broker.wait(timeout=5)
