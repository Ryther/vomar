import os,subprocess,shutil
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]

@pytest.mark.skipif(os.name=='nt',reason='Linux shell installer contract')
def test_per_user_install_handles_unicode_spaces_and_preserves_state(tmp_path):
    package=tmp_path/'Package space è';package.mkdir();(package/'.vomar-runtime').write_text('0.0.0')
    for name in ('vomar','Vomar'):
        p=package/name;p.write_text('#!/bin/sh\nprintf ok\n');p.chmod(0o755)
    scripts=ROOT/'apps/desktop-updater/packaging/linux'
    for name in ('install.sh','uninstall.sh'):shutil.copy2(scripts/name,package/name)
    home=tmp_path/'User è';home.mkdir();data=home/'App data';private=home/'private original';private.write_bytes(b'protected')
    env={**os.environ,'HOME':str(home),'XDG_DATA_HOME':str(data)}
    subprocess.run(['sh',str(package/'install.sh')],env=env,check=True,capture_output=True)
    cli=home/'.local/bin/vomar';assert subprocess.check_output([str(cli)],env=env)==b'ok'
    assert subprocess.run(['sh',str(package/'install.sh')],env=env,capture_output=True).returncode!=0
    subprocess.run(['sh',str(package/'uninstall.sh')],env=env,check=True,capture_output=True)
    assert private.read_bytes()==b'protected' and not cli.exists()
