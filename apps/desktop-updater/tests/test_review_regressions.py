import asyncio,json,time
from pathlib import Path
import pytest
from test_engine import FakeBle,package
from vomar_updater.core.engine import Engine
from vomar_updater.core.storage import Store
from vomar_updater.core.fleet import Broker,Network,Scheduler,Batches
from vomar_updater.adapters.mqtt import MqttBridge
from vomar_updater.core.zigbee import ZigbeeEngine,ZigbeeReview


def test_stop_at_last_ble_read_prevents_new_reset(tmp_path):
    async def scenario():
        p=package();b=FakeBle(p);b.current['primary']['hash']=p.manifest['main']['signedRegionSha256'];s=Store(tmp_path);e=Engine(s,b)
        r=await e.inspect(p,'synthetic');images=b.images;reads=0
        async def stopped_read():
            nonlocal reads
            value=await images();reads+=1
            if reads==2:e.stop()
            return value
        b.images=stopped_read
        with pytest.raises(asyncio.CancelledError):await e.execute(p,r,e.approve(r))
        assert not b.writes and not s.sessions()[0]['uncertain']
    asyncio.run(scenario())


def test_stop_at_last_zigbee_read_prevents_submission(tmp_path):
    async def scenario():
        p=package();s=Store(tmp_path);scheduler=Scheduler();requests=[]
        class Bridge:
            birth=1
            async def verify_recovery(self,*args):scheduler.stop()
            async def request(self,*args,**kwargs):requests.append(args);return {'to':{'file_version':p.manifest['zigbeeOta']['fileVersion'],'software_build_id':p.version}}
        e=ZigbeeEngine(s,Bridge(),scheduler);r=ZigbeeReview('r',p.digest,'a','0x0000000000000001','https://example.org/carrier',1,time.monotonic()+30);e.reviews[r.token]=r
        with pytest.raises(asyncio.CancelledError):await e.execute(p,r,e.approve(r))
        assert not requests and not s.sessions()
    asyncio.run(scenario())


def test_sustained_telemetry_does_not_disconnect_owned_broker():
    b=MqttBridge(Broker('ssl://broker.example',(Network('a','A','z'),)));b.connected=True
    for _ in range(1024):b.feed('z/ordinary-telemetry',b'{}')
    assert b.connected


def test_restart_conservatively_recovers_running_batch_without_approval(tmp_path):
    s=Store(tmp_path);b=Batches(s);group=b.create('a'*64,['active','queued','done']);group['state']='running'
    group['jobs'][0].update(state='running',session='existing-session');group['jobs'][2]['state']='verified';b.save(group);s.close()
    reopened=Store(tmp_path);recovered=Batches(reopened).list()[0]
    assert recovered['state']=='paused'
    assert [j['state'] for j in recovered['jobs']]==['interrupted','queued','verified']
    assert recovered['jobs'][0]['session']=='existing-session'
    reopened.close()


def test_native_executable_names_do_not_collide_after_casefold():
    import ast
    source=Path(__file__).resolve().parents[1]/'packaging/vomar.spec';tree=ast.parse(source.read_text());names=[]
    for node in ast.walk(tree):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='EXE':names.extend(k.value.value for k in node.keywords if k.arg=='name')
    assert len(names)==2 and len({n.casefold() for n in names})==2


def test_cli_lists_batches_without_optional_broker(tmp_path):
    from vomar_updater.cli import parser,run
    args=parser().parse_args(['--state',str(tmp_path),'fleet','list'])
    assert asyncio.run(run(args))==[]


def test_batch_session_receipt_exists_before_first_device_write(tmp_path):
    async def scenario():
        p=package();s=Store(tmp_path);b=FakeBle(p);e=Engine(s,b);attached=[];upload=b.upload
        async def checked(raw,progress):
            assert attached and s.sessions()[0]['id']==attached[0]
            return await upload(raw,progress)
        b.upload=checked;r=await e.inspect(p,'fixture');await e.execute(p,r,e.approve(r),on_session=attached.append)
        assert len(attached)==1
    asyncio.run(scenario())


def test_batch_restart_does_not_repeat_acknowledged_session(tmp_path):
    s=Store(tmp_path);session=s.begin({'operation':'update'});s.record(session,'await-operator',{'acknowledged':True});b=Batches(s);group=b.create('a'*64,['done','queued']);group['state']='running';group['jobs'][0].update(state='running',session=session);b.save(group);s.close()
    s=Store(tmp_path);b=Batches(s);group=b.list()[0];assert group['state']=='paused' and group['jobs'][0]['state']=='await-operator'
    s.record(session,'operator-confirmed');assert b.list()[0]['jobs'][0]['state']=='verified';s.close()


def test_diagnostic_export_keeps_owner_event_loop_responsive(tmp_path,monkeypatch):
    import threading
    from vomar_updater.service import Service
    output=tmp_path/'diagnostic.json';started=threading.Event();release=threading.Event();original_open=Path.open
    def delayed_open(path,*args,**kwargs):
        if path==output:
            started.set();release.wait(2)
        return original_open(path,*args,**kwargs)
    monkeypatch.setattr(Path,'open',delayed_open)
    async def scenario():
        service=Service(tmp_path/'state');report={'identity':{'uid':['synthetic']},'history':[]}
        service.store.setting('last-diagnostic',report)
        export=asyncio.create_task(service.dispatch('diagnostics.export',{'path':str(output)}))
        try:
            assert await asyncio.to_thread(started.wait,3)
            assert not export.done(),'Diagnostic file I/O blocked the owning event loop'
        finally:
            release.set()
            await export
            await service.close()
        assert json.loads(output.read_text())==report
    asyncio.run(scenario())


def test_diagnostic_export_preserves_existing_destination(tmp_path):
    from vomar_updater.service import Service
    output=tmp_path/'existing.json';output.write_text('operator-owned document')
    async def scenario():
        service=Service(tmp_path/'state');service.store.setting('last-diagnostic',{'history':[]})
        try:
            with pytest.raises(FileExistsError):await service.dispatch('diagnostics.export',{'path':str(output)})
        finally:await service.close()
    asyncio.run(scenario())
    assert output.read_text()=='operator-owned document'
