import json
from tools.release import prepare_analysis

def test_remaps_compile_include_arguments_and_all_report_source_roots(tmp_path,monkeypatch):
    reports=tmp_path/'reports';reports.mkdir();candidate=tmp_path/'candidate';candidate.mkdir();old='/old/runner/repo'
    monkeypatch.setattr(prepare_analysis,'check',lambda *args:True)
    (reports/'build-context.json').write_text(json.dumps({'workspace':old}))
    (reports/'compile_commands.json').write_text(json.dumps([{'file':old+'/firmware/src/main.c','directory':old+'/build','arguments':['arm-zephyr-eabi-gcc','-I'+old+'/firmware/src','--sysroot='+old+'/sdk',old+'/firmware/src/main.c']}]))
    for name,raw in [('python-coverage.xml','<coverage><sources><source>'+old+'</source></sources></coverage>'),('lcov.info','SF:'+old+'/integrations/test.js\n')]: (reports/name).write_text(raw)
    prepare_analysis.prepare(reports,candidate,'a'*40)
    assert old not in (reports/'compile_commands.json').read_text()
    assert old not in (reports/'python-coverage.xml').read_text()
    assert old not in (reports/'lcov.info').read_text()


def test_capture_real_build_outside_source_uses_portable_generated_namespace(tmp_path,monkeypatch):
    from tools.release import capture_analysis
    build=tmp_path/'build';firmware=build/'typed/source/firmware/src';firmware.mkdir(parents=True)
    source=capture_analysis.ROOT/'firmware/src/dimmer_model.c';copy=firmware/source.name;copy.write_bytes(source.read_bytes())
    generated=build/'typed/generated';generated.mkdir();(generated/'contracts.h').write_text('/* synthetic generated header */\n')
    (build/'compile_commands.json').write_text(json.dumps([{'file':str(copy),'directory':str(build),'arguments':['arm-zephyr-eabi-gcc','-specs=picolibc.specs','-I'+str(generated),'-c',str(copy)]}]))
    reports=tmp_path/'reports';monkeypatch.setattr('sys.argv',['capture','--build',str(build),'--output',str(reports)])
    capture_analysis.main()
    rows=json.loads((reports/'compile_commands.json').read_text())
    assert rows[0]['file']==str(source) and str(build) not in str(rows)
    assert (reports/'build-inputs/_test/ci-firmware/typed/generated/contracts.h').is_file()
