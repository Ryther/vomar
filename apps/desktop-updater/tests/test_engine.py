import asyncio
from dataclasses import replace
from pathlib import Path
import pytest
from vomar_updater.core.engine import Engine,Identity
from vomar_updater.core.packages import inspect_package
from vomar_updater.core.storage import Store
ROOT=Path(__file__).resolve().parents[3]

class FakeBle:
    authenticated=True
    def __init__(self,p):
        m=p.manifest;self.i=Identity(2,'VIMAR30805',2,('00000001','00000002'),m['loaderContracts'][0]['kind'],m['loaderContracts'][0]['sha256'],'1'*64)
        self.current={'recovery':{'hash':m['targetRecoverySignedHash'],'active':True,'bootable':True},'primary':{'hash':m['allowedSourceSignedHashes'][0],'bootable':True}};self.p=p;self.writes=[]
    async def connect(self,t):pass
    async def identity(self):return self.i
    async def images(self):import copy;return copy.deepcopy(self.current)
    async def upload(self,raw,progress):
        self.writes.append('upload');await progress(len(raw));self.current['primary']['hash']=self.p.manifest['main']['signedRegionSha256']
    async def reset(self):self.writes.append('reset');return True
    async def close(self):pass


def package():
    p=ROOT/'tools/android/test-fixtures/common-v3-synthetic';return inspect_package((p/'one-common.zip').read_bytes(),(p/'public.der').read_bytes())


def test_live_change_rejects_before_any_write(tmp_path):
    async def scenario():
        p=package();b=FakeBle(p);s=Store(tmp_path);e=Engine(s,b)
        preview=await e.inspect(p,'opaque-platform-id');c=e.approve(preview);b.i=replace(b.i,uid=('00000003','00000004'))
        with pytest.raises(ValueError):await e.execute(p,preview,c)
        assert not b.writes
        with pytest.raises(ValueError):await e.execute(p,preview,c)
        s.close()
    asyncio.run(scenario())


def test_reset_acknowledgment_is_not_installed_success(tmp_path):
    async def scenario():
        p=package();b=FakeBle(p);s=Store(tmp_path);events=[];e=Engine(s,b,on_event=events.append)
        preview=await e.inspect(p,'opaque-platform-id');session=await e.execute(p,preview,e.approve(preview))
        assert b.writes==['upload','reset']
        assert s.sessions()[0]['phase']=='await-operator' and s.sessions()[0]['uncertain']
        assert events[-1].phase=='await-operator'
        assert all(x['phase']!='verified' for x in s.events(session))
        s.close()
    asyncio.run(scenario())
