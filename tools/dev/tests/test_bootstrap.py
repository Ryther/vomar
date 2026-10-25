import io
import tarfile
import zipfile
from pathlib import Path
import pytest


def test_extraction_rejects_traversal_and_links(tmp_path):
    from tools.dev.bootstrap import unpack
    for name in ('../escape', '/absolute', 'safe/../../escape'):
        p = tmp_path/'bad.zip'
        with zipfile.ZipFile(p,'w') as z: z.writestr(name,b'no')
        with pytest.raises(ValueError): unpack(p,tmp_path/'out')
    p=tmp_path/'link.tar.xz'
    with tarfile.open(p,'w:xz') as t:
        i=tarfile.TarInfo('link');i.type=tarfile.SYMTYPE;i.linkname='/etc/passwd';t.addfile(i)
    with pytest.raises((ValueError,tarfile.FilterError)): unpack(p,tmp_path/'out')


def test_guide_fallback_never_overwrites_user_skill(tmp_path):
    from tools.dev.bootstrap import install_guide
    source=tmp_path/'source.md';source.write_text('canonical')
    dest=tmp_path/'skills'/'SKILL.md'
    install_guide(source,dest,symlink=False)
    assert dest.read_text()=='canonical'
    dest.write_text('user customized')
    with pytest.raises(ValueError): install_guide(source,dest,symlink=False)


def test_image_bootstrap_can_run_from_shallow_container_copy(tmp_path):
    import subprocess,shutil
    root=tmp_path/'tmp';root.mkdir();script=root/'bootstrap.py'
    shutil.copy2(Path(__file__).parents[1]/'bootstrap.py',script)
    p=subprocess.run([__import__('sys').executable,str(script),'help'],capture_output=True,text=True)
    assert 'IndexError' not in p.stderr
