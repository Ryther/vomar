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


def test_guide_in_persistent_parent_symlink_survives_recreation(tmp_path):
    from tools.dev.bootstrap import install_guide
    source=tmp_path/'repo'/'SKILL.md';source.parent.mkdir();source.write_text('canonical')
    state=tmp_path/'volumes'/'agents'/'claude';state.mkdir(parents=True)
    home=tmp_path/'home';home.mkdir();(home/'.claude').symlink_to(state,target_is_directory=True)
    dest=home/'.claude'/'skills'/'SKILL.md'
    install_guide(source,dest)
    assert dest.read_text()=='canonical'
    install_guide(source,dest)
    assert dest.resolve()==source.resolve()


def test_guide_repairs_only_the_known_broken_legacy_alias(tmp_path):
    import os
    from tools.dev.bootstrap import install_guide
    source=tmp_path/'repo'/'SKILL.md';source.parent.mkdir();source.write_text('canonical')
    state=tmp_path/'volumes'/'agents'/'claude';state.mkdir(parents=True)
    home=tmp_path/'home';home.mkdir();(home/'.claude').symlink_to(state,target_is_directory=True)
    dest=home/'.claude'/'skills'/'SKILL.md';dest.parent.mkdir()
    dest.symlink_to(os.path.relpath(source,dest.parent))
    assert not dest.exists()
    install_guide(source,dest)
    assert dest.read_text()=='canonical'
    dest.unlink();dest.symlink_to('user-customized-missing-skill.md')
    with pytest.raises(ValueError,match='User skill'):
        install_guide(source,dest)
    assert os.readlink(dest)=='user-customized-missing-skill.md'


def test_image_bootstrap_can_run_from_shallow_container_copy(tmp_path):
    import subprocess,shutil
    root=tmp_path/'tmp';root.mkdir();script=root/'bootstrap.py'
    shutil.copy2(Path(__file__).parents[1]/'bootstrap.py',script)
    p=subprocess.run([__import__('sys').executable,str(script),'help'],capture_output=True,text=True)
    assert 'IndexError' not in p.stderr


def test_private_workspace_files_never_enter_docker_build_context():
    import pathspec
    policy=pathspec.PathSpec.from_lines('gitignore',(Path(__file__).resolve().parents[3]/'.dockerignore').read_text().splitlines())
    for p in ['.claude/settings.json','_test/protected-original.zip','work/private/key.pem','.devcontainer/post-create.sh','.env']:
        assert policy.match_file(p),p
    for p in ['.devcontainer/Dockerfile','.devcontainer/toolchain.json','tools/dev/bootstrap.py','.devcontainer/assistants/package-lock.json']:
        assert not policy.match_file(p),p
