import io,struct
from pathlib import Path
import pytest
from vomar_updater.core.installation import *
from vomar_updater.core.packages import inspect_package
from vomar_updater.core.storage import Store
ROOT=Path(__file__).resolve().parents[3]

class Probe:
    halted=True;generation='single-live-lease';serial='synthetic';version='OpenOCD simulator'
    def __init__(self):
        self.flash=bytearray(b'\xff'*FLASH);struct.pack_into('<II',self.flash,0,0x20010000,0x101)
        f=bytearray(b'\xff'*PAGE)
        for at,v in ((0x10,4096),(0x14,256),(0x100,0x52840),(0x104,1),(0x10c,256),(0x110,1024),(0x60,1),(0x64,2)):struct.pack_into('<I',f,at,v)
        self.ficr=bytes(f);self.uicr=b'\xff'*PAGE;self.writes=[];self.fail=None
    def identity(self):return identity(self.ficr)
    def check(self,expected):assert self.identity()==expected and self.halted
    def read(self,at,size):
        if at>=0x10001000:return self.uicr[at-0x10001000:at-0x10001000+size]
        if at>=0x10000000:return self.ficr[at-0x10000000:at-0x10000000+size]
        return bytes(self.flash[at:at+size])
    def watchdog(self):return {'runStatus':0,'config':0,'crv':0,'rren':0}
    def erase_page(self,at,expected):
        self.check(expected);self.writes.append(('erase',at));self.flash[at:at+PAGE]=b'\xff'*PAGE
        if self.fail==at:raise ConnectionError('simulated uncertain erase')
    def program(self,at,data,expected):
        self.check(expected);self.writes.append(('program',at));self.flash[at:at+len(data)]=data
        if self.fail==at:raise ConnectionError('simulated uncertain program')
    def start(self):self.writes.append(('start',None));self.halted=False


def setup(tmp_path):
    probe=Probe();original=capture_original(probe);p=ROOT/'tools/android/test-fixtures/common-v3-synthetic'
    package=inspect_package((p/'one-common.zip').read_bytes(),(p/'public.der').read_bytes());plan=prepare_install(original,package)
    store=Store(tmp_path/'state');store.put(original.raw,'original');export=tmp_path/'protected original.zip';store.export(original.digest,export)
    return probe,plan,store,export


def test_install_anchor_last_and_start_is_separate(tmp_path):
    probe,plan,store,path=setup(tmp_path);engine=InstallEngine(store);r=engine.review(plan,probe,path)
    session=engine.execute(plan,probe,r,engine.approve(r))
    assert probe.flash==plan.final and probe.halted
    assert probe.writes[-1]==('program',ANCHOR+COMMIT_OFFSET)
    r=engine.review(plan,probe,path,start=True);engine.execute(plan,probe,r,engine.approve(r))
    assert probe.writes[-1]==('start',None) and store.sessions()[0]['phase']=='await-operator'

@pytest.mark.parametrize('boundary',[0,4096,0xb000,0xc000,0xb0000,0xff000,ANCHOR+COMMIT_OFFSET])
def test_interruption_preserves_halt_and_explicit_repair(tmp_path,boundary):
    probe,plan,store,path=setup(tmp_path);engine=InstallEngine(store);r=engine.review(plan,probe,path);probe.fail=boundary
    with pytest.raises(ConnectionError):engine.execute(plan,probe,r,engine.approve(r))
    session=store.sessions()[0];assert session['uncertain'] and probe.halted
    assert not any(w[0]=='start' for w in probe.writes)
    probe.fail=None
    with pytest.raises(ValueError):engine.execute(plan,probe,r,'old approval')
    review=engine.review(plan,probe,path,resume_session=session['id']);engine.execute(plan,probe,review,engine.approve(review))
    assert probe.flash==plan.final and probe.halted


def test_wrong_export_and_unissued_page_deny_repair(tmp_path):
    probe,plan,store,path=setup(tmp_path);engine=InstallEngine(store);r=engine.review(plan,probe,path);probe.fail=0
    with pytest.raises(ConnectionError):engine.execute(plan,probe,r,engine.approve(r))
    probe.flash[PAGE*200]=0
    with pytest.raises(ValueError):engine.review(plan,probe,path,resume_session=store.sessions()[0]['id'])
    path.write_bytes(b'wrong')
    with pytest.raises(ValueError):engine.review(plan,probe,path)


def test_adapter_forbids_uicr_and_cross_page_batches():
    from vomar_updater.adapters.openocd import OpenOcdProbe,tcl_quote
    probe=object.__new__(OpenOcdProbe)
    for at,data in [(0x10001000,b'0000'),(4092,b'00000000'),(1,b'0000'),(0,b'x'*260)]:
        with pytest.raises(ValueError):probe.program(at,data,())
    with pytest.raises(ValueError):probe.erase_page(0x10001000,())
    assert '\\$' in tcl_quote('a $x [x] file')


def test_watchdog_registers_match_authoritative_android_wire():
    from vomar_updater.adapters.openocd import OpenOcdProbe
    p=object.__new__(OpenOcdProbe);seen=[]
    def read(at,size):seen.append(at);return bytes(size)
    p.read=read
    assert p.watchdog()=={'runStatus':0,'config':0,'crv':0,'rren':0}
    assert seen==[0x40010400,0x4001050c,0x40010504,0x40010508]
