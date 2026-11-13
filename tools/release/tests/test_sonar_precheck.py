"""The local precheck adapts CI data without weakening any check."""
from tools.release import sonar_precheck


def test_gcc_only_options_are_removed_for_clang_tidy():
    arguments = ['/sdk/arm-zephyr-eabi-gcc', '-Os', '--param', 'min-pagesize=0', '--param=l1-cache-size=32',
                 '-fno-defer-pop', '-mfp16-format=ieee', '-specs=picolibc.specs', '-flto', '-Werror',
                 '-fmacro-prefix-map=/a=b', '-mcpu=cortex-m4', '-I/inc', '-c', 'x.c']
    assert sonar_precheck.clang_arguments(arguments) == ['/sdk/arm-zephyr-eabi-gcc', '-Os', '-mcpu=cortex-m4',
                                                         '-I/inc', '-c', 'x.c']


def test_only_languages_in_scanner_scope_select_report_work(tmp_path):
    settings = tmp_path / 'sonar-project.properties'
    settings.write_text('sonar.sources=firmware,apps/desktop-updater/src\nsonar.exclusions=**/tests/**\n')
    changed = {'firmware/src/a.c': {1}, 'firmware/tests/t.c': {1}, 'tools/release/x.py': {1},
               'apps/desktop-updater/src/vomar_updater/y.py': {2}, 'docs/z.md': {3}}
    languages, scoped = sonar_precheck.changed_languages(changed, settings)
    assert languages == {'c', 'python'}
    assert sorted(scoped) == ['apps/desktop-updater/src/vomar_updater/y.py', 'firmware/src/a.c']
