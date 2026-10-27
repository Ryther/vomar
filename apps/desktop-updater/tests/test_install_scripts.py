import os,subprocess,shutil
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]

@pytest.mark.skipif(os.name=='nt',reason='Linux shell installer contract')
def test_per_user_install_handles_unicode_spaces_and_preserves_state(tmp_path):
    package=tmp_path/'Package space è';package.mkdir();(package/'.vomar-runtime').write_text('0.0.0')
    for name in ('vomar-cli','Vomar'):
        p=package/name;p.write_text('#!/bin/sh\nprintf ok\n');p.chmod(0o755)
    for size in (16,24,32,48,64,128,256,512):
        icon=package/f'icons/{size}x{size}/apps/org.openvimar.updater.desktop.png'
        icon.parent.mkdir(parents=True);icon.write_bytes(b'synthetic icon')
    scripts=ROOT/'apps/desktop-updater/packaging/linux'
    for name in ('install.sh','uninstall.sh'):shutil.copy2(scripts/name,package/name)
    home=tmp_path/'User è';home.mkdir();data=home/'App data';private=home/'private original';private.write_bytes(b'protected')
    env={**os.environ,'HOME':str(home),'XDG_DATA_HOME':str(data)}
    subprocess.run(['sh',str(package/'install.sh')],env=env,check=True,capture_output=True)
    cli=home/'.local/bin/vomar';assert subprocess.check_output([str(cli)],env=env)==b'ok'
    icons=data/'icons/hicolor'
    assert (icons/'256x256/apps/org.openvimar.updater.desktop.png').read_bytes()==b'synthetic icon'
    import configparser
    entry=configparser.ConfigParser(interpolation=None)
    entry.read(data/'applications/org.openvimar.updater.desktop.desktop')
    assert entry['Desktop Entry']['Icon']=='org.openvimar.updater.desktop'
    customized=icons/'32x32/apps/org.openvimar.updater.desktop.png'
    customized.write_bytes(b'user customized icon')
    assert subprocess.run(['sh',str(package/'install.sh')],env=env,capture_output=True).returncode!=0
    subprocess.run(['sh',str(package/'uninstall.sh')],env=env,check=True,capture_output=True)
    assert private.read_bytes()==b'protected' and not cli.exists() and not cli.is_symlink()
    assert not (icons/'256x256/apps/org.openvimar.updater.desktop.png').exists()
    assert customized.read_bytes()==b'user customized icon'


@pytest.mark.skipif(os.name=='nt',reason='Linux shell installer contract')
def test_install_rejects_existing_icon_without_partial_install(tmp_path):
    package=tmp_path/'package';package.mkdir();(package/'.vomar-runtime').write_text('0.0.0')
    home=tmp_path/'home';home.mkdir();data=home/'data'
    for size in (16,24,32,48,64,128,256,512):
        icon=package/f'icons/{size}x{size}/apps/org.openvimar.updater.desktop.png'
        icon.parent.mkdir(parents=True);icon.write_bytes(b'new icon')
    foreign=data/'icons/hicolor/256x256/apps/org.openvimar.updater.desktop.png'
    foreign.parent.mkdir(parents=True);foreign.write_bytes(b'existing icon')
    env={**os.environ,'HOME':str(home),'XDG_DATA_HOME':str(data)}
    script=ROOT/'apps/desktop-updater/packaging/linux/install.sh'
    for name in ('vomar-cli','Vomar'):(package/name).write_text('synthetic executable')
    shutil.copy2(script,package/'install.sh')
    result=subprocess.run(['sh',str(package/'install.sh')],env=env,capture_output=True)
    assert result.returncode!=0
    assert foreign.read_bytes()==b'existing icon'
    assert not (data/'vomar/runtime').exists()
