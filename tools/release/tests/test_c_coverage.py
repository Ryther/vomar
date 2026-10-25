import os,shutil,subprocess
from pathlib import Path
import pytest
from tools.release.c_coverage import WRAPPER

@pytest.mark.skipif(os.name=='nt' or not shutil.which('gcc'),reason='Linux/GCC coverage collector')
def test_duplicate_source_basenames_keep_distinct_execution_maps(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';a.mkdir();b.mkdir();(a/'same.c').write_text('int value(void){return 7;}\n');(b/'same.c').write_text('int value(void);int main(void){return value()!=7;}\n')
    wrapper=tmp_path/'cc';wrapper.write_text(WRAPPER);wrapper.chmod(0o755);profile=tmp_path/'profiles';profile.mkdir()
    env={**os.environ,'VOMAR_REAL_GCC':shutil.which('gcc'),'VOMAR_C_PROFILE':str(profile)}
    subprocess.run([str(wrapper),str(a/'same.c'),str(b/'same.c'),'-o',str(tmp_path/'run')],env=env,check=True,capture_output=True)
    subprocess.run([str(tmp_path/'run')],check=True)
    data=list(profile.rglob('*.gcda'));assert len(data)==2
    for p in data:assert p.read_bytes()[8:12]==p.with_suffix('.gcno').read_bytes()[8:12]


def test_older_gcc_mangled_profile_names_find_exact_matching_map(tmp_path):
    from tools.release.c_coverage import matching_notes
    profile=tmp_path/'profiles';run=profile/'invocation';run.mkdir(parents=True)
    notes=run/'tmp/build/test.gcno';notes.parent.mkdir(parents=True);notes.write_bytes(b'oncgB42*same-map')
    data=run/'#tmp#build#test.gcda';data.write_bytes(b'adcgB42*same-map')
    assert matching_notes(data,profile)==notes
    notes.write_bytes(b'oncgB42*bad!-map')
    with pytest.raises(ValueError):matching_notes(data,profile)
