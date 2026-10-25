from pathlib import Path
import subprocess,sys
import pytest
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'tests'))
from test_resume_contract import ROOT,ISLAND,resume,inputs,kotlin,jar

@pytest.fixture(scope='module')
def evidence(resume,tmp_path_factory):
 base=tmp_path_factory.mktemp('install_evidence')
 compiler=[jar('org.jetbrains.kotlin',n,v) for n,v in [('kotlin-compiler-embeddable','2.2.20'),('kotlin-stdlib','2.2.20'),('kotlin-script-runtime','2.2.20'),('kotlin-reflect','1.6.10'),('kotlin-daemon-embeddable','2.2.20')]]
 compiler += [jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','23.0.0')]
 cp=resume[3];output=base/'evidence.jar';app=ROOT/'apps/android-updater/app/src/main/kotlin/org/openvimar/updater/installer'
 sources=[app/'InitialInstallRetainedEvidence.kt',app/'InitialInstallResumeOption.kt',HERE/'EvidenceProbe.kt']
 result=subprocess.run(['java','-cp',':'.join(map(str,compiler)),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-jvm-target','17','-Xfriend-paths='+','.join(cp.split(':')[:2]),'-classpath',cp,'-d',str(output),*map(str,sources)],capture_output=True,text=True)
 assert result.returncode==0,result.stdout+result.stderr
 return ['java','-Xmx256m','-cp',str(output)+':'+cp,'org.openvimar.updater.installer.EvidenceProbeKt']

@pytest.mark.parametrize('scenario',['good','missing-receipt','corrupt-receipt','missing-original','wrong-target','retry-sync','start','multiple','prefer-resumed'])
def test_retained_original_export_and_start_evidence_is_exact_and_not_an_approval(evidence,inputs,tmp_path,scenario):
 out=tmp_path/'out';out.mkdir()
 subprocess.run([*evidence,'evidence',*map(str,inputs),str(out),scenario],check=True)
