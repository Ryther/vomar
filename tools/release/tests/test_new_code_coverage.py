"""New-code coverage follows the Sonar formula over changed lines only."""
import subprocess
from pathlib import Path

from tools.release import new_code_coverage as ncc


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def repository(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.email', 'test@example.invalid')
    git(repo, 'config', 'user.name', 'Test')
    (repo / 'sonar-project.properties').write_text(
        'sonar.sources=app,firmware,integrations/zigbee2mqtt,kt\nsonar.exclusions=**/tests/**\n')
    for path in ('app/a.py', 'firmware/src/x.c', 'firmware/src/x.h', 'integrations/zigbee2mqtt/c.js',
                 'kt/src/main/kotlin/org/v/K.kt', 'app/tests/t.py'):
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text('')
    git(repo, 'add', '.')
    git(repo, 'commit', '-q', '-m', 'base')
    base = git(repo, 'rev-parse', 'HEAD')
    (repo / 'app/a.py').write_text('a = 1\nif a:\n    b = 2\n')
    (repo / 'firmware/src/x.c').write_text('int f(int v)\n{\n    return v;\n}\n')
    (repo / 'firmware/src/x.h').write_text('struct s {\n    int field;\n};\nint f(int v);\n')
    (repo / 'integrations/zigbee2mqtt/c.js').write_text('const a = 1;\nif (a) {}\n')
    (repo / 'kt/src/main/kotlin/org/v/K.kt').write_text('val a = 1\n')
    (repo / 'app/tests/t.py').write_text('assert True\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-q', '-m', 'head')
    return repo, base


def reports(tmp_path, *, with_c=True):
    out = tmp_path / 'reports'
    out.mkdir()
    (out / 'python-coverage.xml').write_text(
        '<coverage><packages><package><classes><class filename="app/a.py"><lines>'
        '<line number="1" hits="1"/><line number="2" hits="1" branch="true" condition-coverage="50% (1/2)"/>'
        '<line number="3" hits="0"/></lines></class></classes></package></packages></coverage>')
    (out / 'lcov.info').write_text('SF:/ci/integrations/zigbee2mqtt/c.js\nDA:1,1\nDA:2,1\n'
                                   'BRDA:2,0,0,1\nBRDA:2,0,1,-\nend_of_record\n')
    for name in ('core-jacoco.xml', 'app-jacoco.xml'):
        (out / name).write_text('<report><package name="org/v"><sourcefile name="K.kt">'
                                '<line nr="1" mi="0" ci="3" mb="0" cb="0"/></sourcefile></package></report>')
    files = '<file path="firmware/src/x.c"><lineToCover lineNumber="3" covered="false"/></file>' if with_c else ''
    (out / 'c-coverage.xml').write_text('<coverage version="1">' + files + '</coverage>')
    return out


def test_formula_counts_lines_and_conditions_in_scope(tmp_path):
    repo, base = repository(tmp_path)
    result = ncc.measure(repo, base, 'HEAD', reports(tmp_path), repo / 'sonar-project.properties')
    rows = {row['path']: row for row in result['files']}
    assert rows['app/a.py'] == {'path': 'app/a.py', 'toCover': 5, 'covered': 3, 'estimated': False}
    assert rows['integrations/zigbee2mqtt/c.js']['toCover'] == 4
    assert rows['integrations/zigbee2mqtt/c.js']['covered'] == 3
    assert rows['kt/src/main/kotlin/org/v/K.kt']['covered'] == 1
    assert rows['firmware/src/x.c'] == {'path': 'firmware/src/x.c', 'toCover': 1, 'covered': 0, 'estimated': False}
    assert 'app/tests/t.py' not in rows and 'firmware/src/x.h' not in rows
    assert (result['covered'], result['toCover']) == (7, 11)
    assert not result['passed']


def test_unreported_c_counts_only_statements_in_function_bodies(tmp_path):
    repo, base = repository(tmp_path)
    result = ncc.measure(repo, base, 'HEAD', reports(tmp_path, with_c=False), repo / 'sonar-project.properties')
    rows = {row['path']: row for row in result['files']}
    assert rows['firmware/src/x.c'] == {'path': 'firmware/src/x.c', 'toCover': 1, 'covered': 0, 'estimated': True}
    assert 'firmware/src/x.h' not in rows


def test_c_estimate_ignores_declarations_initializers_and_comments():
    text = ['static const int table[] = {', '    1,', '};', 'struct s { int a; };', '/* if (x) */',
            'void g(void)', '{', '    // return;', '    if (x) {', '        y();', '    }', '}']
    assert [i + 1 for i, flag in enumerate(ncc.c_executable(text)) if flag] == [9, 10]
