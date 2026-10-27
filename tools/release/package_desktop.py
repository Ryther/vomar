"""Native-only PyInstaller packaging with verified redistributable probe tools."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import tomllib
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[2]


def run(*args,**kwargs):return subprocess.run([str(x) for x in args],check=True,**kwargs)


def native_version():
    version=tomllib.loads((ROOT/'pyproject.toml').read_text())['project']['version']
    if not isinstance(version,str) or not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',version) or any(int(part)>65535 for part in version.split('.')):
        raise ValueError('Native desktop version must be a platform-representable numeric SemVer')
    return version


def windows_version_resource(output,version):
    """Generate PyInstaller's version resource in the private build directory."""
    parts=tuple(int(part) for part in version.split('.'))+(0,)
    path=output/'native-version.txt'
    path.write_text(f'''VSVersionInfo(
  ffi=FixedFileInfo(filevers={parts!r}, prodvers={parts!r}, mask=0x3f,
                   flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('FileDescription', 'Vomar'),
    StringStruct('FileVersion', {version!r}),
    StringStruct('ProductName', 'Vomar'),
    StringStruct('ProductVersion', {version!r})
  ])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
''',encoding='utf-8')
    return path


def verify_cli_version(cli,version,output,env):
    observed=run(cli,'--version',cwd=output,env=env,capture_output=True,text=True).stdout.strip()
    if observed!=version:raise ValueError(f'CLI native version mismatch: expected {version}, observed {observed!r}')
    return observed


def verify_macos_version(bundle,version):
    with (bundle/'Contents/Info.plist').open('rb') as source:info=plistlib.load(source)
    observed={key:info.get(key) for key in ('CFBundleShortVersionString','CFBundleVersion')}
    if any(value!=version for value in observed.values()):raise ValueError(f'macOS native version mismatch: {observed!r}')
    return observed


def verify_windows_version(executable,version):
    # Pass paths as environment data, never as executable PowerShell text.
    script='''$ErrorActionPreference = 'Stop'
$v = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($env:VOMAR_VERSION_TARGET)
[ordered]@{
    fileVersion = $v.FileVersion
    productVersion = $v.ProductVersion
    fileParts = @($v.FileMajorPart, $v.FileMinorPart, $v.FileBuildPart, $v.FilePrivatePart)
    productParts = @($v.ProductMajorPart, $v.ProductMinorPart, $v.ProductBuildPart, $v.ProductPrivatePart)
} | ConvertTo-Json -Compress
'''
    result=run('powershell.exe','-NoProfile','-NonInteractive','-Command',script,env={**os.environ,'VOMAR_VERSION_TARGET':str(executable)},capture_output=True,text=True)
    observed=json.loads(result.stdout)
    parts=[int(part) for part in version.split('.')]+[0]
    if observed!={'fileVersion':version,'productVersion':version,'fileParts':parts,'productParts':parts}:
        raise ValueError(f'Windows native version mismatch for {executable.name}: {observed!r}')
    return observed


def fetch(item,path):
    with urllib.request.urlopen(item['url'],timeout=120) as r,path.open('wb') as out:shutil.copyfileobj(r,out)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Native tool checksum mismatch')


def probe_tools(output):
    system={'Linux':'linux','Windows':'win32','Darwin':'darwin'}[platform.system()];arch={'x86_64':'x64','AMD64':'x64','arm64':'arm64','aarch64':'arm64'}[platform.machine()]
    name=f'xpack-openocd-0.12.0-7-{system}-{arch}'+('.zip' if system=='win32' else '.tar.gz')
    item=json.loads((ROOT/'tools/release/runtime-tools.json').read_text())['openocd']['assets'][name];archive=output/name
    fetch(item,archive);extracted=output/'probe-source';extracted.mkdir()
    if archive.suffix=='.zip':
        from tools.dev.bootstrap import unpack
        unpack(archive,extracted)
    else:
        with tarfile.open(archive) as t:t.extractall(extracted,filter='data')
    roots=list(extracted.iterdir())
    if len(roots)!=1:raise ValueError('Unexpected probe archive layout')
    return roots[0]


def notices(output):
    dest=output/'notices';dest.mkdir()
    shutil.copy2(ROOT/'LICENSE',dest/'Vomar-MIT.txt');shutil.copy2(ROOT/'THIRD_PARTY_NOTICES.md',dest/'THIRD_PARTY_NOTICES.md')
    python_license=next((p for p in (Path(sysconfig.get_path('stdlib'))/'LICENSE.txt',Path(sys.base_prefix)/'LICENSE.txt') if p.is_file()),None)
    if python_license is None:raise ValueError('Exact Python runtime license is missing')
    shutil.copy2(python_license,dest/'Python-LICENSE.txt');shutil.copytree(ROOT/'licenses/qt',dest/'Qt-PySide6')
    records=[]
    # Include the exact installed distributions/available license texts in the
    # build SBOM. Development dependencies are identified, never asserted shipped.
    for d in metadata.distributions():
        name=d.metadata['Name'];version=d.version;records.append({'name':name,'version':version,'license':d.metadata.get('License-Expression') or d.metadata.get('License') or 'See bundled upstream notices'})
        for f in d.files or []:
            if '.dist-info/licenses/' in str(f) or str(f).endswith(('.dist-info/LICENSE','.dist-info/LICENSE.txt','.dist-info/COPYING')):
                source=Path(d.locate_file(f))
                if source.is_file():
                    target=dest/name/str(f).split('.dist-info/',1)[1];target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    (dest/'build-environment-sbom.json').write_text(json.dumps({'scope':'Installed native build environment; runtime dependency inspection is recorded separately','packages':records},indent=2)+'\n')
    return dest


def build(output,version):
    if platform.system()=='Darwin' and platform.machine() not in ('arm64','aarch64'):
        raise ValueError('macOS builds require Apple Silicon (arm64)')
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)',version):raise ValueError('Distribution SemVer required')
    desktop_version=native_version()
    from .branding import synchronize,SIZES
    if synchronize(check=True):raise ValueError('Stale brand assets; run python -m tools.release.branding --sync')
    output=output.absolute();output.mkdir(parents=True,exist_ok=False)
    probe=probe_tools(output);licenses=notices(output)
    env={**os.environ,'VOMAR_PROBE_ROOT':str(probe),'VOMAR_NOTICES_ROOT':str(licenses),'VOMAR_NATIVE_VERSION':desktop_version,'MACOSX_DEPLOYMENT_TARGET':'14.4'}
    brand=ROOT/'assets/branding'
    if platform.system()=='Windows':
        env['VOMAR_NATIVE_ICON']=str(brand/'vomar.ico')
        env['VOMAR_VERSION_RESOURCE']=str(windows_version_resource(output,desktop_version))
    elif platform.system()=='Darwin':
        iconset=output/'Vomar.iconset';iconset.mkdir()
        for size in (16,32,128,256,512):
            for scale in (1,2):
                pixels=size*scale
                original=brand/('vomar-icon.png' if pixels==1024 else f'png-sizes/vomar-icon-{pixels}.png')
                shutil.copy2(original,iconset/f'icon_{size}x{size}{"@2x" if scale==2 else ""}.png')
        native_icon=output/'Vomar.icns'
        run('iconutil','--convert','icns','--output',native_icon,iconset)
        env['VOMAR_NATIVE_ICON']=str(native_icon)
    spec=ROOT/'apps/desktop-updater/packaging/vomar.spec'
    run(sys.executable,'-m','PyInstaller','--clean','--noconfirm','--distpath',output/'dist','--workpath',output/'work',spec,cwd=ROOT,env=env)
    system=platform.system();arch='arm64' if platform.machine() in ('arm64','aarch64') else 'x64'
    bundle=output/'dist'/('Vomar.app' if system=='Darwin' else 'Vomar')
    if system=='Linux':
        shutil.copy2(ROOT/'apps/desktop-updater/packaging/linux/install.sh',bundle/'install.sh');shutil.copy2(ROOT/'apps/desktop-updater/packaging/linux/uninstall.sh',bundle/'uninstall.sh')
        for size in SIZES:
            icon=bundle/f'icons/{size}x{size}/apps/org.openvimar.updater.desktop.png'
            icon.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(brand/f'png-sizes/vomar-icon-{size}.png',icon)
        (bundle/'.vomar-runtime').write_text(version+'\n')
        artifact=output/f'vomar-desktop-{version}-linux-{arch}.tar.gz'
        with tarfile.open(artifact,'w:gz') as t:t.add(bundle,arcname='Vomar')
        run('ldd',bundle/'Vomar',stdout=(output/'native-dependencies.txt').open('w'))
    elif system=='Windows':
        artifact=output/f'vomar-desktop-{version}-windows-{arch}.zip'
        with zipfile.ZipFile(artifact,'w',zipfile.ZIP_DEFLATED) as z:
            for p in bundle.rglob('*'):
                if p.is_file():z.write(p,'Vomar/'+str(p.relative_to(bundle)))
        catalog=json.loads((ROOT/'tools/release/runtime-tools.json').read_text());item=catalog['inno']['assets']['innosetup-7.1.0-x64.exe'];installer=output/'inno.exe';fetch(item,installer)
        run(installer,'/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/CURRENTUSER','/DIR='+str(output/'inno'))
        run(output/'inno/ISCC.exe','/DNativeVersion='+desktop_version,'/DDistributionVersion='+version,'/DRuntime='+str(bundle),'/DBrandIcon='+str(brand/'vomar.ico'),'/O'+str(output),ROOT/'apps/desktop-updater/packaging/windows/vomar.iss')
    elif system=='Darwin':
        run('codesign','--force','--deep','--sign','-',bundle)
        stage=output/'dmg';stage.mkdir();shutil.copytree(bundle,stage/'Vomar.app',symlinks=True);(stage/'Applications').symlink_to('/Applications',target_is_directory=True)
        shutil.copy2(ROOT/'docs/desktop.md',stage/'README.md')
        artifact=output/f'vomar-desktop-{version}-macos-{arch}.dmg'
        run('hdiutil','create','-volname','Vomar','-srcfolder',stage,'-ov','-format','UDZO',artifact)
    else:raise ValueError('Unsupported native package platform')
    cli=bundle/('Contents/MacOS/vomar-cli' if system=='Darwin' else 'vomar-cli.exe' if system=='Windows' else 'vomar-cli')
    # Run outside the source tree with no repository PYTHONPATH or SDK environment.
    smoke_env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','VIMAR_NCS_WORKSPACE','VIMAR_BUILD_PYTHON','ZEPHYR_BASE','ANDROID_HOME')}
    version_verification={'cli':verify_cli_version(cli,desktop_version,output,smoke_env)}
    if system=='Darwin':version_verification['macos']=verify_macos_version(bundle,desktop_version)
    elif system=='Windows':
        setup=output/f'vomar-desktop-{version}-windows-{arch}-setup.exe'
        version_verification['windows']={path.name:verify_windows_version(path,desktop_version) for path in (bundle/'Vomar.exe',cli,setup)}
    run(cli,'--help',cwd=output,env=smoke_env)
    probe_exe=probe/('bin/openocd.exe' if system=='Windows' else 'bin/openocd')
    run(probe_exe,'--version',cwd=output,env=smoke_env)
    frozen_probe=bundle/('Contents/Resources' if system=='Darwin' else '_internal')/'vomar_updater/resources/probe/bin'/probe_exe.name
    run(frozen_probe,'--version',cwd=output,env=smoke_env)
    fixture=ROOT/'tools/android/test-fixtures/common-v3-synthetic'
    run(cli,'releases','verify','--path',fixture/'one-common.zip','--public-key',fixture/'public.der',cwd=output,env=smoke_env)
    gui=bundle/('Contents/MacOS/Vomar' if system=='Darwin' else 'Vomar.exe' if system=='Windows' else 'Vomar')
    run(gui,'--state',output/'smoke-private-state','--smoke-test','--screenshot',output/'gui-launch.png',cwd=output,env={**smoke_env,'QT_QPA_PLATFORM':'offscreen'})
    from .inventory import native
    native_platform=('windows' if system=='Windows' else 'macos' if system=='Darwin' else 'linux')+'-'+arch
    built=sorted(output.glob('vomar-desktop-*'))
    (output/('native-'+native_platform+'.json')).write_text(json.dumps(native(bundle,native_platform,built),indent=2)+'\n')
    (output/('package-report-'+native_platform+'.json')).write_text(json.dumps({'platform':system,'architecture':arch,'distributionVersion':version,'nativeVersion':desktop_version,'nativeVersionVerification':version_verification,'artifact':artifact.name,'sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),'size':artifact.stat().st_size,'physicalBleUsbQualification':False,'trustedOsSigning':False},indent=2)+'\n')
    return artifact


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--version',default=(ROOT/'VERSION').read_text().strip());a=p.parse_args();print(build(a.output,a.version))

if __name__=='__main__':main()
