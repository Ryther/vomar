import json,os,shutil,subprocess,sys,tempfile
from pathlib import Path
import pytest
from tools.release.c_coverage import WRAPPER

@pytest.mark.skipif(os.name=='nt' or not shutil.which('gcc'),reason='Linux/GCC coverage collector')
def test_duplicate_source_basenames_keep_distinct_execution_maps(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';a.mkdir();b.mkdir();(a/'same.c').write_text('int value(void){return 7;}\n');(b/'same.c').write_text('int value(void);int main(void){return value()!=7;}\n')
    wrapper=tmp_path/'cc';wrapper.write_text(WRAPPER);wrapper.chmod(0o755);profile=tmp_path/'profiles';profile.mkdir()
    env={**os.environ,'VOMAR_REAL_GCC':shutil.which('gcc'),'VOMAR_C_PROFILE':str(profile),'VOMAR_C_SOURCE_ROOT':str(tmp_path)}
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


@pytest.mark.skipif(os.name=='nt' or not shutil.which('gcc'),reason='Linux/GCC coverage collector')
def test_deleted_synthetic_harness_does_not_enter_product_coverage(tmp_path):
    import sys
    import xml.etree.ElementTree as ET
    from tools.release.c_coverage import matching_notes
    product=tmp_path/'firmware';product.mkdir()
    source=product/'value.c'
    transient=tmp_path/'transient';transient.mkdir()
    harness=transient/'identity.c'
    (transient/'stub.h').write_text('static inline int stub(void){return 7;}\n')
    source.write_text('#include "stub.h"\nint value(void){return stub();}\n')
    harness.write_text('int value(void);int main(void){return value()!=7;}\n')
    wrapper=tmp_path/'cc';wrapper.write_text(WRAPPER);wrapper.chmod(0o755)
    profile=tmp_path/'profiles';profile.mkdir()
    env={**os.environ,'VOMAR_REAL_GCC':shutil.which('gcc'),
         'VOMAR_C_PROFILE':str(profile),'VOMAR_C_SOURCE_ROOT':str(product)}
    subprocess.run([str(wrapper),'-I'+str(transient),str(source),str(harness),'-o',str(tmp_path/'run')],env=env,check=True,capture_output=True)
    subprocess.run([str(tmp_path/'run')],check=True)
    shutil.rmtree(transient)
    data=list(profile.rglob('*.gcda'))
    assert len(data)==1, 'Only durable product code may contribute execution profiles'
    executed=tmp_path/'executed';executed.mkdir()
    shutil.copy2(data[0],executed/'value.gcda')
    shutil.copy2(matching_notes(data[0],profile),executed/'value.gcno')
    report=tmp_path/'coverage.xml'
    subprocess.run([sys.executable,'-m','gcovr','--root',str(product),'--sonarqube',str(report),str(executed)],check=True,capture_output=True)
    files=ET.parse(report).getroot().findall('file')
    assert len(files)==1 and Path(files[0].get('path')).name=='value.c'
    assert files[0].find('lineToCover').get('covered')=='true'


@pytest.mark.skipif(os.name=='nt' or not shutil.which('gcc'),reason='Linux/GCC coverage collector')
def test_separate_compile_and_link_retains_product_execution_profiles(tmp_path):
    source=tmp_path/'product.c';source.write_text('int main(void){return 0;}\n')
    wrapper=tmp_path/'cc';wrapper.write_text(WRAPPER);wrapper.chmod(0o755)
    profile=tmp_path/'profiles';profile.mkdir()
    env={**os.environ,'VOMAR_REAL_GCC':shutil.which('gcc'),
         'VOMAR_C_PROFILE':str(profile),'VOMAR_C_SOURCE_ROOT':str(tmp_path)}
    obj=tmp_path/'product.o'
    subprocess.run([str(wrapper),'-c',str(source),'-o',str(obj)],env=env,check=True,capture_output=True)
    subprocess.run([str(wrapper),str(obj),'-o',str(tmp_path/'run')],env=env,check=True,capture_output=True)
    subprocess.run([str(tmp_path/'run')],check=True)
    assert len(list(profile.rglob('*.gcda')))==1


def test_existing_coverage_output_is_rejected_before_running_tests(tmp_path,monkeypatch):
    from tools.release import c_coverage
    output=tmp_path/'previous';output.mkdir()
    (output/'c-coverage.xml').write_text('previous candidate')
    monkeypatch.setattr('sys.argv',['c_coverage','--output',str(output)])
    def unexpected_run(*args,**kwargs):
        pytest.fail('An existing coverage directory must be rejected before executing tests')
    monkeypatch.setattr(c_coverage.subprocess,'run',unexpected_run)
    with pytest.raises(FileExistsError):c_coverage.main()
    assert (output/'c-coverage.xml').read_text()=='previous candidate'


@pytest.mark.skipif(os.name=='nt' or not shutil.which('gcc'),reason='Linux/GCC coverage collector')
def test_harness_including_product_c_retains_real_product_coverage(tmp_path):
    import sys
    import xml.etree.ElementTree as ET
    from tools.release.c_coverage import matching_notes
    product=tmp_path/'firmware';product.mkdir()
    source=product/'provider.c';source.write_text('int value(void){return 7;}\n')
    transient=tmp_path/'transient';transient.mkdir()
    harness=transient/'temporary.c'
    harness.write_text('#include "'+str(source)+'"\nint main(void){return value()!=7;}\n')
    wrapper=tmp_path/'cc';wrapper.write_text(WRAPPER);wrapper.chmod(0o755)
    profile=tmp_path/'profiles';profile.mkdir()
    env={**os.environ,'VOMAR_REAL_GCC':shutil.which('gcc'),
         'VOMAR_C_PROFILE':str(profile),'VOMAR_C_SOURCE_ROOT':str(product)}
    subprocess.run([str(wrapper),str(harness),'-o',str(tmp_path/'run')],env=env,check=True,capture_output=True)
    subprocess.run([str(tmp_path/'run')],check=True)
    harness.unlink()
    data=list(profile.rglob('*.gcda'))
    assert len(data)==1, 'Product functions included by a synthetic harness must remain measured'
    executed=tmp_path/'executed';executed.mkdir()
    shutil.copy2(data[0],executed/'provider.gcda')
    shutil.copy2(matching_notes(data[0],profile),executed/'provider.gcno')
    report=tmp_path/'coverage.xml'
    subprocess.run([sys.executable,'-m','gcovr','--root',str(product),'--sonarqube',str(report),str(executed)],check=True,capture_output=True)
    files=ET.parse(report).getroot().findall('file')
    assert len(files)==1 and Path(files[0].get('path')).name=='provider.c'
    assert files[0].find('lineToCover').get('covered')=='true'


@pytest.mark.skipif(os.name=='nt' or not shutil.which('gcc') or not shutil.which('gcov'),reason='Linux/GCC coverage collector')
@pytest.mark.parametrize('separate_unit',[False,True])
def test_deleted_harness_keeps_product_and_inline_header_coverage(tmp_path,separate_unit):
    from tools.release.c_coverage import matching_notes
    product=tmp_path/'firmware';product.mkdir()
    header=product/'inline.h';header.write_text('static inline int inline_value(void){return 7;}\n')
    unit=product/'value.c';unit.write_text('int value(void){return 5;}\n')
    wrapper=tmp_path/'cc';wrapper.write_text(WRAPPER);wrapper.chmod(0o755)
    profile=tmp_path/'profiles';profile.mkdir()
    env={**os.environ,'VOMAR_REAL_GCC':shutil.which('gcc'),'VOMAR_C_PROFILE':str(profile),'VOMAR_C_SOURCE_ROOT':str(product)}
    with tempfile.TemporaryDirectory() as directory:
        harness=Path(directory)/'test.c'
        extra='int value(void);' if separate_unit else ''
        expected='inline_value()+value()!=12' if separate_unit else 'inline_value()!=7'
        stubs=Path(directory)/'stubs';stubs.mkdir()
        (stubs/'generated.h').write_text('static inline int generated_value(void){return 5;}\n')
        (stubs/'forced.h').write_text('#define FORCED_VALUE 3\n')
        (Path(directory)/'adjacent.h').write_text('static inline int adjacent_value(void){return 7;}\n')
        if separate_unit:unit.write_text('#include "generated.h"\nint value(void){return generated_value();}\n')
        harness.write_text('#include "inline.h"\n#include "adjacent.h"\n'+extra+'int main(void){return '+expected+' || adjacent_value()!=7 || FORCED_VALUE!=3;}\n')
        command=[str(wrapper),'-I',str(product),'-I'+str(stubs),'-include','forced.h',str(harness)]
        if separate_unit:command.append(str(unit))
        subprocess.run([*command,'-o',str(tmp_path/'run')],env=env,check=True,capture_output=True)
        subprocess.run([str(tmp_path/'run')],check=True)
    assert not harness.exists()
    executed=tmp_path/'executed';executed.mkdir()
    for data in profile.rglob('*.gcda'):
        notes=matching_notes(data,profile)
        target=executed/data.relative_to(profile);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(data,target);shutil.copy2(notes,target.with_suffix('.gcno'))
    report=tmp_path/'coverage.json'
    result=subprocess.run([sys.executable,'-m','gcovr','--root',str(tmp_path),'--filter',str(product)+'/',
                           '--include-internal-functions','--json',str(report),str(executed)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    files={row['file']:row for row in json.loads(report.read_text())['files']}
    expected_files={'firmware/inline.h','firmware/value.c'} if separate_unit else {'firmware/inline.h'}
    assert set(files)==expected_files
    for row in files.values():assert any(line['count']>0 for line in row['lines'])
