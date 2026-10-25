import importlib.util
from pathlib import Path
import zipfile
import pytest
import sys

spec = importlib.util.spec_from_file_location('build_updater', Path(__file__).parents[1] / 'build_updater.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# Exact package/SDK lines captured from pinned aapt2 35.0.0 during failed regeneration:
# experiments/android-updater/20261022T150311Z/aapt2-badging.txt
CAPTURED_BADGING = "package: name='org.openvimar.updater' versionCode='1' versionName='0.1.0' platformBuildVersionName='15' platformBuildVersionCode='35' compileSdkVersion='35' compileSdkVersionCodename='15'\nminSdkVersion:'26'\ntargetSdkVersion:'35'\n"
CURRENT_BADGING = CAPTURED_BADGING.replace("versionCode='1'", "versionCode='20'").replace("versionName='0.1.0'", "versionName='1.0.0'")

def test_patchReleaseAcceptedAndPreviousApkRejected():
    patched = CURRENT_BADGING
    m.audit_manifest(patched, 'android:allowBackup=false')
    with pytest.raises(ValueError, match='version'):
        m.audit_manifest(CAPTURED_BADGING, 'android:allowBackup=false')
    previous = CAPTURED_BADGING.replace("versionCode='1'", "versionCode='5'").replace("versionName='0.1.0'", "versionName='0.1.4'")
    with pytest.raises(ValueError, match='version'):
        m.audit_manifest(previous, 'android:allowBackup=false')

def test_apkBuildDoesNotInventCurrentFirmwareQualification():
    status = m.release_status()
    assert status['real_bundle']['status'] == 'not_assessed_by_apk_build'
    assert status['android_instrumentation'] == 'not_run_by_apk_build'

def test_manifestAcceptsPinnedAapt2Badging():
    m.audit_manifest(CURRENT_BADGING, 'android:allowBackup=false')

def apk(tmp_path, entries):
    p = tmp_path / 'test.apk'
    with zipfile.ZipFile(p, 'w') as z:
        for name, data in entries.items(): z.writestr(name, data)
    return p

@pytest.mark.parametrize('name,data', [('assets/private.pem', b'-----BEGIN EC PRIVATE KEY-----'), ('assets/stock.bin', b'original'), ('assets/backup.dat',b'dump'), ('assets/key.der',b'private-DER'), ('DebugProbesKt.bin', b'forged'), ('classes.dex', b'prefix-----BEGIN PRIVATE KEY-----')])
def test_apkHasNoPrivateKeyOrOriginalDump(tmp_path, name, data):
    with pytest.raises(ValueError): m.audit_entries(apk(tmp_path, {'res/raw/firmware_public.der':b'production',name:data}), b'production', b'fixture')

def test_fixtureSigningKeyNotTrustedByRelease(tmp_path):
    with pytest.raises(ValueError): m.audit_entries(apk(tmp_path, {'res/raw/firmware_public.der':b'fixture'}), b'production', b'fixture')
    with pytest.raises(ValueError): m.audit_entries(apk(tmp_path, {'res/raw/firmware_public.der':b'production', 'classes.dex':b'fixture'}), b'production', b'fixture')

def test_githubAccessIsAllowedButDebugAndBackupRemainForbidden():
    good=CURRENT_BADGING
    xml='android:allowBackup(0x01010280)=false'
    m.audit_manifest(good, xml)
    m.audit_manifest(good+"uses-permission: name='android.permission.INTERNET'", xml)
    for bad in ['application-debuggable']:
        with pytest.raises(ValueError): m.audit_manifest(good+bad, xml)
    with pytest.raises(ValueError): m.audit_manifest(good, xml.replace('false','true'))

def test_bundleQualificationCannotBeBypassed():
    report=m.release_status()
    assert report['real_bundle']['status']=='not_assessed_by_apk_build'
    assert 'separately pinned' in report['real_bundle']['reason']

def test_buildDoesNotOverwritePriorRelease(tmp_path):
    m.reserve_output(tmp_path/'release')
    with pytest.raises(FileExistsError): m.reserve_output(tmp_path/'release')

@pytest.mark.parametrize('version', ['0.6.3', '0.7.0'])
def test_defaultBuildAttemptsAreGroupedByAppVersion(tmp_path, monkeypatch, version):
    monkeypatch.setattr(m, 'ROOT', tmp_path)
    monkeypatch.setattr(m, 'APP_VERSION', version)
    monkeypatch.setattr(sys, 'argv', ['build_updater.py'])
    outputs=[]
    monkeypatch.setattr(m, 'build', lambda output: outputs.append(output) or {})
    m.main()
    assert outputs[0].parent == tmp_path/'experiments/android-updater/builds'/version

def test_explicitBuildOutputIsStillHonored(tmp_path, monkeypatch):
    explicit=tmp_path/'controlled-check'
    monkeypatch.setattr(sys, 'argv', ['build_updater.py', '--output', str(explicit)])
    outputs=[]
    monkeypatch.setattr(m, 'build', lambda output: outputs.append(output) or {})
    m.main()
    assert outputs == [explicit]

def test_reportDoesNotClaimHardwareSuccess():
    r=m.release_status()
    assert r['hardware_validation']=='not_performed'
    assert r['android_instrumentation']=='not_run_by_apk_build'

def test_signerReadsSinglePasswordLineOnce(tmp_path):
    args=m.signing_command(tmp_path/'key.jks', tmp_path/'password', tmp_path/'out.apk', tmp_path/'in.apk')
    assert args.count('file:'+str(tmp_path/'password'))==1
    assert '--key-pass' not in args  # same password defaults to store password

def test_releaseResourceNameMayBeShortened(tmp_path):
    resources='resource 0x7f080000 raw/firmware_public\n      () (file) res/jf.der\n'
    assert m.anchor_resource_path(resources)=='res/jf.der'
    m.audit_entries(apk(tmp_path, {'res/jf.der':b'production'}), b'production', b'fixture', 'res/jf.der')

def test_failedAuditNeverPublishesFinalApk(tmp_path):
    candidate=tmp_path/'candidate.apk'; candidate.write_bytes(b'bad')
    final=tmp_path/'vimar-updater-0.1.0.apk'
    def reject(_): raise ValueError('rejected')
    with pytest.raises(ValueError): m.publish_verified(candidate,final,reject)
    assert not final.exists()

@pytest.mark.parametrize('field,value', [('minSdkVersion', '25'), ('minSdkVersion', '27'), ('targetSdkVersion', '34'), ('targetSdkVersion', '36')])
def test_manifestRejectsWrongSdk(field, value):
    good=CURRENT_BADGING
    expected = '26' if field == 'minSdkVersion' else '35'
    with pytest.raises(ValueError, match='SDK'):
        m.audit_manifest(good.replace(f"{field}:'{expected}'", f"{field}:'{value}'"), 'android:allowBackup=false')

def test_externalOutputRejectedBeforeSideEffects(tmp_path, monkeypatch):
    monkeypatch.setattr(m, 'ROOT', tmp_path / 'repo')
    calls = []
    monkeypatch.setattr(m, 'run', lambda *args, **kwargs: calls.append(args))
    output = tmp_path / 'external-release'
    with pytest.raises(ValueError, match='repository'):
        m.build(output)
    assert not output.exists()
    assert calls == []

@pytest.mark.parametrize('symlinked', [False, True])
def test_inputsOutputRejectedBeforeSideEffects(tmp_path, monkeypatch, symlinked):
    root = tmp_path / 'repo'
    (root / 'inputs').mkdir(parents=True)
    monkeypatch.setattr(m, 'ROOT', root)
    if symlinked:
        (root / 'alias').symlink_to(root / 'inputs', target_is_directory=True)
        output = root / 'alias' / 'release'
    else:
        output = root / 'inputs' / 'release'
    calls = []
    monkeypatch.setattr(m, 'run', lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match='inputs'):
        m.build(output)
    assert not output.exists()
    assert calls == []
