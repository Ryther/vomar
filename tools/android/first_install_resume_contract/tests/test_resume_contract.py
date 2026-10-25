"""Explicit recovery candidate on synthetic inputs; no Gradle or physical IO."""
from pathlib import Path
import subprocess,sys,json
import pytest
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'tools/android/first_install_contract/tests'))
from test_first_install_contract import jar,kotlin,original_fixture,archive,common_fixture
ISLAND=ROOT/'tools/android/first_install_resume_contract'

@pytest.fixture(scope='module')
def resume(kotlin,tmp_path_factory):
 base=tmp_path_factory.mktemp('resume_kotlin')
 compiler=[jar('org.jetbrains.kotlin',n,v) for n,v in [('kotlin-compiler-embeddable','2.2.20'),('kotlin-stdlib','2.2.20'),('kotlin-script-runtime','2.2.20'),('kotlin-reflect','1.6.10'),('kotlin-daemon-embeddable','2.2.20')]]
 compiler += [jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','23.0.0')]
 output=base/'resume.jar';cp=kotlin[3];friend=cp.split(':')[0]
 args=['java','-cp',':'.join(map(str,compiler)),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-Xfriend-paths='+friend,'-classpath',cp,'-d',str(output),*map(str,sorted((ISLAND/'src').glob('*.kt'))),*map(str,sorted((ISLAND/'tests').glob('*.kt')))]
 result=subprocess.run(args,capture_output=True,text=True);assert result.returncode==0,result.stdout+result.stderr
 return ['java','-Xmx256m','-cp',str(output)+':'+cp,'org.openvimar.installer.resume.ResumeProbeKt']

@pytest.fixture
def inputs(tmp_path,request):
 regions,m=original_fixture()
 if getattr(request.node,'callspec',None) and str(request.node.callspec.params.get('scenario','')).startswith('body-short-frontier'):
  import hashlib
  regions['flash.bin']=regions['flash.bin'][:0xef000]+b'\xff'*(0x100000-0xef000)
  m['regions'][0]['sha256']=hashlib.sha256(regions['flash.bin']).hexdigest()
 backup=tmp_path/'original.zip';backup.write_bytes(archive(regions,m))
 raw,key,_,_=common_fixture(candidate=True);release=tmp_path/'candidate.zip';release.write_bytes(raw);public=tmp_path/'public.der';public.write_bytes(key)
 return backup,release,public

@pytest.mark.parametrize('scenario',['same','moved','changed-backup','wrong-binding'])
def test_initial_export_receipt_and_bit_identical_moved_backup_are_required(resume,inputs,tmp_path,scenario):
 out=tmp_path/'out';out.mkdir()
 run=subprocess.run([*resume,'receipt',*map(str,inputs),str(out),scenario],capture_output=True,text=True)
 if scenario in ['changed-backup','wrong-binding']:
  assert run.returncode!=0 and not (out/'receipt.json').exists();return
 assert run.returncode==0,run.stderr
 receipt=json.loads((out/'receipt.json').read_text())
 assert set(receipt)=={'schemaVersion','bindingId','archiveSha256','document'}
 assert receipt['document']=='content://original/document/one'
 if scenario=='moved':assert (out/'selected.txt').read_text()=='content://cloud/document/moved-original'

@pytest.mark.parametrize('scenario',['good','stale','gap','corrupt','base-changed','frontier','durability','durability-fail'])
def test_resume_journal_is_hash_linked_atomic_and_retains_maximum_frontier_across_restarts(resume,tmp_path,scenario):
 subprocess.run([*resume,'journal',str(tmp_path),scenario],check=True)

@pytest.mark.parametrize('scenario',['good','body-ready','body-short-frontier','body-short-frontier-lost','body-short-frontier-tail','committed','unissued-changed','uicr','uid','cancel-prior','cancel-after','generation','lost-commit','stale-head','stale-prepared','replay-prepared','wrong-generation','resume-again'])
def test_explicit_resume_uses_protected_original_and_frontier_never_unknown_flash(resume,inputs,tmp_path,scenario):
 out=tmp_path/'out';out.mkdir()
 subprocess.run([*resume,'engine',*map(str,inputs),str(out),scenario],check=True)
