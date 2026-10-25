"""Actual programming source on synthetic targets only; never opens USB."""
import subprocess
import pytest
from test_first_install_contract import ROOT, ISLAND, jar, kotlin, common_fixture


@pytest.fixture(scope='module')
def programming(kotlin,tmp_path_factory):
    base=tmp_path_factory.mktemp('programming_kotlin')
    compiler=[jar('org.jetbrains.kotlin',name,version) for name,version in [
        ('kotlin-compiler-embeddable','2.2.20'),('kotlin-stdlib','2.2.20'),('kotlin-script-runtime','2.2.20'),
        ('kotlin-reflect','1.6.10'),('kotlin-daemon-embeddable','2.2.20')]]
    compiler += [jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','23.0.0')]
    app=ROOT/'apps/android-updater/app/src/main/kotlin/org/openvimar/updater'
    sources=list((app/'installer').glob('*.kt'))
    sources=[p for p in sources if not p.name.startswith('Android') and not p.name.endswith('Service.kt')]
    sources += list((ROOT/'tools/android/first_install_resume_contract/src').glob('*.kt'))
    gate=app/'DkUsbOperationGate.kt'
    if gate.exists():sources.append(gate)
    output=base/'programming.jar';cp=kotlin[3]
    result=subprocess.run(['java','-cp',':'.join(map(str,compiler)),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler',
        '-no-stdlib','-no-reflect','-jvm-target','17','-Xfriend-paths='+cp.split(':')[0],'-classpath',cp,'-d',str(output),*map(str,sources),
        *map(str,sorted((ISLAND/'programming-tests').glob('*.kt')))],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    return ['java','-Xmx256m','-cp',str(output)+':'+cp,'org.openvimar.updater.ProgrammingProbeKt']


def test_process_wide_gate_keeps_one_owner_until_explicit_release_and_rejects_stale_token(programming):
    subprocess.run([*programming,'gate'],check=True)


@pytest.mark.parametrize('scenario',['wire-policy','wire-wait','wire-posted-read','wire-core-registers','wire-cache'])
def test_real_jlink_programming_wire_obeys_independent_per_clock_target(programming,scenario):
    subprocess.run([*programming,scenario],check=True)


@pytest.mark.parametrize('scenario',['lease-before-cancel','lease-after-cancel','lease-happy','lease-wdt','lease-control','lease-ready','lease-posthalt-mode','lease-posthalt-busy','lease-cross-boundary','lease-mid-batch-cancel','lease-batch-uid','lease-ff-words'])
def test_halted_nvmc_lease_cancellation_and_original_cpu_state(programming,scenario):
    subprocess.run([*programming,scenario],check=True)


@pytest.mark.parametrize('scenario',['lease-watchdog-paused','lease-watchdog-running','lease-retired-reset-flag'])
def test_active_watchdog_and_retired_capture_reset_are_rejected_before_cpu_halt(programming,scenario):
    subprocess.run([*programming,scenario],check=True)


@pytest.mark.parametrize('scenario',['controller-prewrite','controller-full','controller-partial-cancel','controller-persist-fail','controller-close-fail','controller-export-change','controller-begin-persist-fail','controller-start','controller-start-changed','controller-keep-halted','controller-already-custom','controller-anchor-present','controller-start-clean-debug','controller-start-wrong-pc','controller-start-wrong-msp','controller-start-ignored-catch','controller-start-enable-fail','controller-paused-watchdog','controller-watchdog-no-cap','controller-watchdog-running','controller-watchdog-empty-rre','controller-watchdog-long','controller-start-open-fail'])
def test_controller_retains_halted_connection_across_export_and_requires_fresh_exact_review(programming,tmp_path,scenario):
    raw,key,_,_=common_fixture(candidate=True,**({'watchdog_handoff':'paused-reset-before-main-v1'} if ('watchdog' in scenario and scenario!='controller-watchdog-no-cap') else {}));source=tmp_path/'candidate.zip';source.write_bytes(raw);pub=tmp_path/'public.der';pub.write_bytes(key)
    subprocess.run([*programming,scenario,str(source),str(pub),str(tmp_path)],check=True)


def test_restart_fence_blocks_new_original_binding_over_incomplete_same_uid_or_corrupt_journal(programming,tmp_path):
    subprocess.run([*programming,'recovery-fence',str(tmp_path)],check=True)


def test_selected_document_export_requires_completed_close_and_exact_bounded_reopen(programming):
    subprocess.run([*programming,'selected-document'],check=True)


def test_service_admission_never_recreates_a_job_or_loses_cancel_before_worker_attachment(programming):
    subprocess.run([*programming,'host-policy'],check=True)


def test_android_adapters_and_private_filesystem_instrumentation_compile_against_actual_sdk(programming,tmp_path):
    compiler=[jar('org.jetbrains.kotlin',name,version) for name,version in [
        ('kotlin-compiler-embeddable','2.2.20'),('kotlin-stdlib','2.2.20'),('kotlin-script-runtime','2.2.20'),
        ('kotlin-reflect','1.6.10'),('kotlin-daemon-embeddable','2.2.20')]]
    compiler += [jar('org.jetbrains.kotlinx','kotlinx-coroutines-core-jvm','1.8.0'),jar('org.jetbrains','annotations','23.0.0')]
    sdk=ROOT/'work/android-sdk/platforms/android-35';app=ROOT/'apps/android-updater/app'
    r=app/'build/intermediates/compile_and_runtime_not_namespaced_r_class_jar/release/processReleaseResources/R.jar'
    cp=programming[3]+':'+':'.join(map(str,[sdk/'android.jar',sdk/'optional/android.test.base.jar',sdk/'optional/android.test.runner.jar',jar('junit','junit','4.13.2'),r]))
    directory=app/'src/main/kotlin/org/openvimar/updater'
    sources=list((directory/'installer').glob('Android*.kt'))+list((directory/'installer').glob('*Service.kt'))
    sources += [directory/name for name in ['DkJlinkReadOnly.kt','DkSwdReadOnly.kt','DkBackupCapture.kt','DkJlinkInterfaceSelector.kt']]
    sources += [app/'src/androidTest/kotlin/org/openvimar/updater/InitialInstallAndroidAdapterTest.kt']
    friends=','.join(programming[3].split(':')[:2])
    result=subprocess.run(['java','-cp',':'.join(map(str,compiler)),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect',
        '-jvm-target','17','-Xfriend-paths='+friends,'-classpath',cp,'-d',str(tmp_path/'android-adapters.jar'),*map(str,sources)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr

@pytest.mark.parametrize('scenario',['resume-mode1','resume-mode2','resume-cancel','resume-bad-uicr','resume-mode-ack-loss','resume-unconfirmed'])
def test_resume_only_quiescence_restores_known_nvmc_mode_but_always_retains_halt(programming,tmp_path,scenario):
    raw,key,_,_=common_fixture(candidate=True);source=tmp_path/'candidate.zip';source.write_bytes(raw);pub=tmp_path/'public.der';pub.write_bytes(key)
    subprocess.run([*programming,scenario,str(source),str(pub),str(tmp_path)],check=True)

@pytest.mark.parametrize('scenario',['controller-resume','controller-resume-cancel','controller-resume-verified'])
def test_actual_controller_repairs_only_retained_same_original_after_fresh_review(programming,tmp_path,scenario):
    raw,key,_,_=common_fixture(candidate=True);source=tmp_path/'candidate.zip';source.write_bytes(raw);pub=tmp_path/'public.der';pub.write_bytes(key)
    subprocess.run([*programming,scenario,str(source),str(pub),str(tmp_path)],check=True)

def test_fresh_original_capture_also_checks_immutable_base_plus_progressed_resume_log(programming,tmp_path):
    subprocess.run([*programming,'resume-capture-fence',str(tmp_path)],check=True)
