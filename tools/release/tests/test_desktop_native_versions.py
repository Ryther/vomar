"""Native package versions belong to the desktop component, not the distribution."""
import json
import os
from pathlib import Path
import plistlib
import re
import runpy
import shutil
import subprocess
import sys
import tarfile
import types

import pytest

from tools.release import package_desktop


def frozen_runtime():
    return {'schemaVersion':1,'nativeVersion':'1.1.0','pythonVersion':'3.13.18',
            'opensslVersion':'OpenSSL 3.5.9 29 Sep 2026','frozen':True,
            'defaultTrustStore':{'caCertificates':100,'hashedCaFiles':0},
            'tlsSelfTest':{'address':'127.0.0.1','trustedCertificateAccepted':True,
                           'untrustedCertificateRejected':True,'negotiatedTlsVersion':'TLSv1.3'}}


@pytest.mark.parametrize('damage',['python','openssl','source-interpreter','untrusted','missing-test','empty-trust'])
def test_actual_frozen_runtime_mismatch_rejects_package(tmp_path, monkeypatch, damage):
    observed=frozen_runtime()
    if damage=='python':observed['pythonVersion']='3.13.12'
    elif damage=='openssl':observed['opensslVersion']='OpenSSL 3.0.18 30 Sep 2025'
    elif damage=='source-interpreter':observed['frozen']=False
    elif damage=='untrusted':observed['tlsSelfTest']['untrustedCertificateRejected']=False
    elif damage=='missing-test':observed.pop('tlsSelfTest')
    else:observed['defaultTrustStore']={'caCertificates':0,'hashedCaFiles':0}
    monkeypatch.setattr(package_desktop,'run',lambda *a,**k:subprocess.CompletedProcess(a,0,stdout=json.dumps(observed)))
    with pytest.raises(ValueError):package_desktop.verify_frozen_runtime(tmp_path/'cli','1.1.0',tmp_path,{})


def test_actual_frozen_runtime_records_lazy_default_ca_directory(tmp_path, monkeypatch):
    observed=frozen_runtime();observed['defaultTrustStore']={'caCertificates':0,'hashedCaFiles':3}
    calls=[]
    def run(*args,**kwargs):
        calls.append(args);return subprocess.CompletedProcess(args,0,stdout=json.dumps(observed))
    monkeypatch.setattr(package_desktop,'run',run)
    assert package_desktop.verify_frozen_runtime(tmp_path/'cli','1.1.0',tmp_path,{})==observed
    assert calls[0][1:]==('--runtime-info','--tls-self-test')


def test_frozen_smoke_cannot_borrow_build_python_or_tls_libraries(tmp_path, monkeypatch):
    prefix=tmp_path/'runtime/venv';base=tmp_path/'runtime/base/python'
    monkeypatch.setattr(package_desktop.sys,'prefix',str(prefix));monkeypatch.setattr(package_desktop.sys,'base_prefix',str(base))
    monkeypatch.setenv('PATH',os.pathsep.join([str(prefix/'bin'),str(base/'bin'),'/usr/bin']))
    monkeypatch.setenv('LD_LIBRARY_PATH',str(base/'lib'));monkeypatch.setenv('PYTHONPATH',str(tmp_path/'source'))
    monkeypatch.setenv('DYLD_LIBRARY_PATH',str(base/'lib'))
    observed=package_desktop.frozen_environment()
    assert all(name not in observed for name in ('LD_LIBRARY_PATH','DYLD_LIBRARY_PATH','PYTHONPATH'))
    assert observed['PATH']=='/usr/bin'


def test_desktop_version_reads_native_owner(tmp_path, monkeypatch):
    (tmp_path/'pyproject.toml').write_text('[project]\nversion = "1.1.0"\n')
    (tmp_path/'VERSION').write_text('2.0.0\n')
    monkeypatch.setattr(package_desktop, 'ROOT', tmp_path)
    assert package_desktop.native_version() == '1.1.0'


@pytest.mark.parametrize('version', ['2.0.0-beta', '1.0', '1.2.65536'])
def test_native_version_rejects_unrepresentable_platform_versions(tmp_path, monkeypatch, version):
    (tmp_path/'pyproject.toml').write_text(f'[project]\nversion = "{version}"\n')
    monkeypatch.setattr(package_desktop, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='Native desktop version'):
        package_desktop.native_version()


def test_windows_resource_contains_native_string_and_numeric_versions(tmp_path):
    resource = package_desktop.windows_version_resource(tmp_path, '1.1.0')
    captured = {}
    def node(name):
        def constructor(*args, **kwargs):
            captured.setdefault(name, []).append((args, kwargs))
            return (name, args, kwargs)
        return constructor
    namespace = {name: node(name) for name in ('VSVersionInfo', 'FixedFileInfo', 'StringFileInfo', 'StringTable', 'StringStruct', 'VarFileInfo', 'VarStruct')}
    exec(resource.read_text(), namespace)
    fixed = captured['FixedFileInfo'][0][1]
    assert fixed['filevers'] == (1, 1, 0, 0)
    assert fixed['prodvers'] == (1, 1, 0, 0)
    strings = dict(args for args, _ in captured['StringStruct'])
    assert strings['FileVersion'] == '1.1.0'
    assert strings['ProductVersion'] == '1.1.0'
    assert resource.parent == tmp_path


@pytest.mark.parametrize('system', ['darwin', 'win32'])
def test_spec_sets_native_metadata_for_both_entrypoints(tmp_path, monkeypatch, system):
    captured = {}
    def constructor(name):
        def build(*args, **kwargs):
            captured.setdefault(name, []).append(kwargs)
            return types.SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])
        return build
    hooks = types.ModuleType('PyInstaller.utils.hooks')
    hooks.collect_submodules = lambda name: []
    monkeypatch.setitem(sys.modules, 'PyInstaller.utils.hooks', hooks)
    monkeypatch.setattr(sys, 'platform', system)
    monkeypatch.setenv('VOMAR_PROBE_ROOT', str(tmp_path))
    monkeypatch.setenv('VOMAR_NOTICES_ROOT', str(tmp_path))
    monkeypatch.setenv('VOMAR_NATIVE_VERSION', '1.1.0')
    monkeypatch.setenv('VOMAR_VERSION_RESOURCE', str(tmp_path/'native-version.txt'))
    spec = package_desktop.ROOT/'apps/desktop-updater/packaging/vomar.spec'
    runpy.run_path(str(spec), init_globals={'SPECPATH':str(spec.parent), **{name:constructor(name) for name in ('Analysis', 'PYZ', 'EXE', 'COLLECT', 'BUNDLE')}})
    if system == 'darwin':
        bundle = captured['BUNDLE'][0]
        assert bundle['version'] == '1.1.0'
        assert bundle['info_plist']['CFBundleShortVersionString'] == '1.1.0'
        assert bundle['info_plist']['CFBundleVersion'] == '1.1.0'
    else:
        assert [item['version'] for item in captured['EXE']] == [str(tmp_path/'native-version.txt')]*2


@pytest.mark.parametrize('observed', ['2.0.0', '0.0.0', '1.1.0\nunexpected'])
def test_cli_version_mismatch_rejects_package(tmp_path, monkeypatch, observed):
    monkeypatch.setattr(package_desktop, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=observed+'\n'))
    with pytest.raises(ValueError, match='CLI.*version'):
        package_desktop.verify_cli_version(tmp_path/'vomar-cli', '1.1.0', tmp_path, {})


def test_actual_cli_version_stdout_is_verified(tmp_path):
    cli = tmp_path/'vomar-cli'
    cli.write_text(f'#!{sys.executable}\nprint("1.1.0")\n')
    cli.chmod(0o755)
    assert package_desktop.verify_cli_version(cli, '1.1.0', tmp_path, os.environ.copy()) == '1.1.0'


@pytest.mark.parametrize('field', ['CFBundleShortVersionString', 'CFBundleVersion'])
def test_actual_macos_plist_rejects_mismatch(tmp_path, field):
    contents = tmp_path/'Contents'
    contents.mkdir()
    info = {'CFBundleShortVersionString':'1.1.0', 'CFBundleVersion':'1.1.0'}
    info[field] = '2.0.0'
    (contents/'Info.plist').write_bytes(plistlib.dumps(info))
    with pytest.raises(ValueError, match='macOS.*version'):
        package_desktop.verify_macos_version(tmp_path, '1.1.0')


def test_actual_macos_plist_records_both_native_versions(tmp_path):
    (tmp_path/'Contents').mkdir()
    info = {'CFBundleShortVersionString':'1.1.0', 'CFBundleVersion':'1.1.0'}
    (tmp_path/'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    assert package_desktop.verify_macos_version(tmp_path, '1.1.0') == info


@pytest.mark.parametrize('field', ['fileVersion', 'productVersion', 'fileParts', 'productParts'])
def test_windows_pe_inspection_rejects_native_version_mismatch(tmp_path, monkeypatch, field):
    observed = {'fileVersion':'1.1.0', 'productVersion':'1.1.0', 'fileParts':[1,1,0,0], 'productParts':[1,1,0,0]}
    observed[field] = [2,0,0,0] if field.endswith('Parts') else '2.0.0'
    monkeypatch.setattr(package_desktop, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=json.dumps(observed)))
    with pytest.raises(ValueError, match='Windows.*version'):
        package_desktop.verify_windows_version(tmp_path/'a tricky \' filename.exe', '1.1.0')


def test_windows_pe_inspection_passes_path_as_data(tmp_path, monkeypatch):
    executable = tmp_path/'a tricky \' filename.exe'
    observed = {'fileVersion':'1.1.0', 'productVersion':'1.1.0', 'fileParts':[1,1,0,0], 'productParts':[1,1,0,0]}
    def inspect(*args, **kwargs):
        assert str(executable) not in args[-1]
        assert kwargs['env']['VOMAR_VERSION_TARGET'] == str(executable)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(observed))
    monkeypatch.setattr(package_desktop, 'run', inspect)
    assert package_desktop.verify_windows_version(executable, '1.1.0') == observed


def test_windows_pe_inspection_accepts_inno_ascii_space_padding_and_preserves_raw_report(tmp_path, monkeypatch):
    observed = {'fileVersion':'1.1.0               ', 'productVersion':'1.1.0                                             ', 'fileParts':[1,1,0,0], 'productParts':[1,1,0,0]}
    monkeypatch.setattr(package_desktop, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=json.dumps(observed)))
    assert package_desktop.verify_windows_version(tmp_path/'setup.exe', '1.1.0') == observed


@pytest.mark.parametrize('field', ['fileVersion', 'productVersion'])
@pytest.mark.parametrize('value', ['2.0.0   ', ' 1.1.0', '1.1.0\t', '1.1.0\n', '1.1.0\u00a0', '1.1.0 junk ', '1.1.0.0 ', '', None])
def test_windows_pe_padding_does_not_allow_mismatched_or_malformed_versions(tmp_path, monkeypatch, field, value):
    observed = {'fileVersion':'1.1.0', 'productVersion':'1.1.0', 'fileParts':[1,1,0,0], 'productParts':[1,1,0,0]}
    observed[field] = value
    monkeypatch.setattr(package_desktop, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=json.dumps(observed)))
    with pytest.raises(ValueError, match='Windows.*version'):
        package_desktop.verify_windows_version(tmp_path/'setup.exe', '1.1.0')


@pytest.mark.parametrize('mutation', ['missing', 'extra', 'fileParts', 'productParts'])
def test_windows_pe_padding_preserves_exact_fields_and_numeric_versions(tmp_path, monkeypatch, mutation):
    observed = {'fileVersion':'1.1.0   ', 'productVersion':'1.1.0   ', 'fileParts':[1,1,0,0], 'productParts':[1,1,0,0]}
    if mutation == 'missing':del observed['fileVersion']
    elif mutation == 'extra':observed['unexpectedVersion'] = '1.1.0'
    else:observed[mutation] = [2,0,0,0]
    monkeypatch.setattr(package_desktop, 'run', lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout=json.dumps(observed)))
    with pytest.raises(ValueError, match='Windows.*version'):
        package_desktop.verify_windows_version(tmp_path/'setup.exe', '1.1.0')


@pytest.fixture
def synthetic_native_build(tmp_path, monkeypatch):
    """Replace native compilers/downloads, retaining real package/report writes."""
    from tools.release import branding, inventory
    source = tmp_path/'source'
    source.mkdir()
    (source/'pyproject.toml').write_text('[project]\nversion = "1.1.0"\n')
    installer = source/'apps/desktop-updater/packaging/windows/vomar.iss'
    installer.parent.mkdir(parents=True)
    shutil.copy2(package_desktop.ROOT/'apps/desktop-updater/packaging/windows/vomar.iss', installer)
    (source/'tools/release').mkdir(parents=True)
    (source/'tools/release/runtime-tools.json').write_text(json.dumps({'inno':{'assets':{'innosetup-7.1.0-x64.exe':{}}}}))
    (source/'docs').mkdir()
    (source/'docs/desktop.md').write_text('Synthetic user guide\n')
    (source/'assets/branding/png-sizes').mkdir(parents=True)
    (source/'assets/branding/vomar-icon.png').write_bytes(b'icon')
    for size in (16,24,32,48,64,128,256,512):
        (source/f'assets/branding/png-sizes/vomar-icon-{size}.png').write_bytes(b'icon')
    linux_scripts = source/'apps/desktop-updater/packaging/linux'
    linux_scripts.mkdir()
    for name in ('install.sh','uninstall.sh'):
        (linux_scripts/name).write_text('#!/bin/sh\nexit 0\n')
    monkeypatch.setattr(package_desktop, 'ROOT', source)
    monkeypatch.setattr(branding, 'synchronize', lambda **kwargs: False)
    monkeypatch.setattr(package_desktop, 'probe_tools', lambda output: output/'probe')
    monkeypatch.setattr(package_desktop, 'notices', lambda output: output/'notices')
    monkeypatch.setattr(package_desktop, 'build_runtime_provenance', lambda: {'synthetic':True})
    monkeypatch.setattr(package_desktop, 'fetch', lambda item, path: path.write_bytes(b'synthetic installer'))
    monkeypatch.setattr(inventory, 'native', lambda *args: {'synthetic':True})
    settings = {'cliVersion':'1.1.0', 'platformVersion':'1.1.0'}
    output = tmp_path/'output'
    def run(*raw_args, **kwargs):
        args = list(map(str, raw_args))
        if 'PyInstaller' in args:
            system = package_desktop.platform.system()
            bundle = output/'dist'/('Vomar.app' if system == 'Darwin' else 'Vomar')
            binary_dir = bundle/'Contents/MacOS' if system == 'Darwin' else bundle
            binary_dir.mkdir(parents=True)
            for name in (('Vomar.exe','vomar-cli.exe') if system == 'Windows' else ('Vomar','vomar-cli')):
                (binary_dir/name).write_bytes(b'synthetic executable')
            if system == 'Darwin':
                (bundle/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':settings['platformVersion'],'CFBundleVersion':settings['platformVersion']}))
            settings['buildEnv'] = kwargs['env']
        elif args[0].endswith('ISCC.exe'):
            defines = dict(arg[2:].split('=',1) for arg in args if arg.startswith('/D'))
            expanded = re.sub(r'\{#(\w+)\}', lambda match: defines[match[1]], installer.read_text())
            fields = dict(line.split('=',1) for line in expanded.splitlines() if '=' in line and not line.startswith(';'))
            settings['innoFields'] = fields
            (output/(fields['OutputBaseFilename']+'.exe')).write_bytes(b'synthetic setup')
        elif args[0] == 'powershell.exe':
            value = settings['platformVersion']
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps({'fileVersion':value,'productVersion':value,'fileParts':[int(p) for p in value.split('.')]+[0],'productParts':[int(p) for p in value.split('.')]+[0]}))
        elif args[0] == 'hdiutil':
            Path(args[-1]).write_bytes(b'synthetic dmg')
        elif Path(args[0]).name in ('vomar-cli', 'vomar-cli.exe') and args[1:] == ['--version']:
            return subprocess.CompletedProcess(args, 0, stdout=settings['cliVersion']+'\n')
        elif Path(args[0]).name in ('vomar-cli', 'vomar-cli.exe') and args[1:] == ['--runtime-info','--tls-self-test']:
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps(frozen_runtime()))
        return subprocess.CompletedProcess(args, 0, stdout='')
    monkeypatch.setattr(package_desktop, 'run', run)
    return output, settings


@pytest.mark.parametrize('system,machine,platform_name', [('Windows','AMD64','windows-x64'), ('Darwin','arm64','macos-arm64'), ('Linux','x86_64','linux-x64')])
def test_build_keeps_distribution_filenames_and_native_metadata(synthetic_native_build, monkeypatch, system, machine, platform_name):
    output, settings = synthetic_native_build
    monkeypatch.setattr(package_desktop.platform, 'system', lambda: system)
    monkeypatch.setattr(package_desktop.platform, 'machine', lambda: machine)
    artifact = package_desktop.build(output, '2.0.0')
    assert artifact.name.startswith('vomar-desktop-2.0.0-')
    report = json.loads((output/f'package-report-{platform_name}.json').read_text())
    assert report['distributionVersion'] == '2.0.0'
    assert report['nativeVersion'] == '1.1.0'
    assert report['nativeVersionVerification']['cli'] == '1.1.0'
    assert report['nativeRuntime']['frozen']['pythonVersion']=='3.13.18'
    assert report['nativeRuntime']['frozen']['tlsSelfTest']['untrustedCertificateRejected'] is True
    assert json.loads((output/f'native-{platform_name}.json').read_bytes())['nativeRuntime']==report['nativeRuntime']
    assert settings['buildEnv']['VOMAR_NATIVE_VERSION'] == '1.1.0'
    if system == 'Windows':
        assert Path(settings['buildEnv']['VOMAR_VERSION_RESOURCE']).is_relative_to(output)
        assert settings['innoFields']['AppVersion'] == '1.1.0'
        for field in ('VersionInfoVersion','VersionInfoTextVersion','VersionInfoProductVersion','VersionInfoProductTextVersion'):
            assert settings['innoFields'][field] == '1.1.0'
        assert (output/'vomar-desktop-2.0.0-windows-x64-setup.exe').is_file()
        assert set(report['nativeVersionVerification']['windows']) == {'Vomar.exe','vomar-cli.exe','vomar-desktop-2.0.0-windows-x64-setup.exe'}
    elif system == 'Darwin':
        assert report['nativeVersionVerification']['macos'] == {'CFBundleShortVersionString':'1.1.0','CFBundleVersion':'1.1.0'}
    else:
        with tarfile.open(artifact) as archive:
            assert archive.extractfile('Vomar/.vomar-runtime').read() == b'2.0.0\n'


@pytest.mark.parametrize('mismatch', ['cliVersion', 'platformVersion'])
@pytest.mark.parametrize('system,machine', [('Darwin','arm64'), ('Windows','AMD64')])
def test_build_rejects_stale_native_artifact_without_success_report(synthetic_native_build, monkeypatch, mismatch, system, machine):
    output, settings = synthetic_native_build
    settings[mismatch] = '2.0.0'
    monkeypatch.setattr(package_desktop.platform, 'system', lambda: system)
    monkeypatch.setattr(package_desktop.platform, 'machine', lambda: machine)
    with pytest.raises(ValueError, match='version mismatch'):
        package_desktop.build(output, '2.0.0')
    assert not list(output.glob('package-report-*.json'))
