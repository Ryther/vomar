"""Coverage of changed lines, computed like the Sonar new-code condition.

Community Sonar without branch analysis cannot measure new code against a
reference branch. This reads the exact-run reports used by CI and applies the
Sonar formula, (covered conditions + covered lines) / (conditions + lines),
to lines added or modified since the base commit, within the scanner scope
of sonar-project.properties. A changed source file absent from every report
counts each changed non-blank, non-comment line as uncovered: Sonar would
report the file through its zero-coverage sensor.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
THRESHOLD = 80.0
COVERED_SUFFIXES = ('.py', '.js', '.kt', '.java', '.c', '.h')


def properties(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip()
    return values


def in_scope(path, sources, exclusions):
    if not path.endswith(COVERED_SUFFIXES):
        return False
    if not any(path == s or path.startswith(s.rstrip('/') + '/') for s in sources):
        return False
    # Sonar patterns: '**/' also matches the top level.
    return not any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(path, p.replace('**/', '', 1)) for p in exclusions)


def changed_lines(repository, base, head):
    diff = subprocess.run(['git', '-C', str(repository), 'diff', '--unified=0', '--no-color', '--no-ext-diff',
                           '--find-renames', '--diff-filter=AMR', base, head],
                          capture_output=True, text=True, check=True).stdout
    result, current = {}, None
    for line in diff.splitlines():
        if line.startswith('+++ '):
            current = None if line == '+++ /dev/null' else line[6:]
        elif line.startswith('@@') and current:
            match = re.match(r'@@ -\S+ \+(\d+)(?:,(\d+))? @@', line)
            start, count = int(match.group(1)), int(match.group(2) or 1)
            result.setdefault(current, set()).update(range(start, start + count))
    return result


def _merge(table, path, line, covered, branches, covered_branches):
    old = table.setdefault(path, {}).get(line)
    if old:
        covered = covered or old[0]
        branches = max(branches, old[1])
        covered_branches = max(covered_branches, old[2])
    table[path][line] = (covered, branches, covered_branches)


def read_cobertura(path, table):
    for item in ET.parse(path).getroot().iter('class'):
        name = item.get('filename', '')
        for line in item.iter('line'):
            branches = covered_branches = 0
            condition = line.get('condition-coverage')
            if line.get('branch') == 'true' and condition:
                covered_branches, branches = map(int, re.search(r'\((\d+)/(\d+)\)', condition).groups())
            _merge(table, name, int(line.get('number')), int(line.get('hits', 0)) > 0, branches, covered_branches)


def read_lcov(path, table, marker='integrations/zigbee2mqtt/'):
    name, branches = None, {}
    for row in Path(path).read_text().splitlines():
        if row.startswith('SF:'):
            source = row[3:]
            name = source[source.index(marker):] if marker in source else source
            branches = {}
        elif row.startswith('DA:') and name:
            line, hits = row[3:].split(',')[:2]
            _merge(table, name, int(line), int(hits) > 0, 0, 0)
        elif row.startswith('BRDA:') and name:
            line, _block, _branch, taken = row[5:].split(',')
            total, covered = branches.get(int(line), (0, 0))
            branches[int(line)] = (total + 1, covered + (taken not in ('-', '0')))
        elif row == 'end_of_record' and name:
            for line, (total, covered) in branches.items():
                old = table.get(name, {}).get(line, (False, 0, 0))
                _merge(table, name, line, old[0], total, covered)
            name = None


def read_jacoco(path, table):
    """JaCoCo names sources by package; key them as '<package>/<file>'."""
    for package in ET.parse(path).getroot().iter('package'):
        for source in package.iter('sourcefile'):
            key = package.get('name') + '/' + source.get('name')
            for line in source.iter('line'):
                mb, cb = int(line.get('mb', 0)), int(line.get('cb', 0))
                _merge(table, 'jacoco:' + key, int(line.get('nr')), int(line.get('ci', 0)) > 0, mb + cb, cb)


def read_generic(path, table):
    for item in ET.parse(path).getroot().iter('file'):
        for line in item.iter('lineToCover'):
            _merge(table, item.get('path'), int(line.get('lineNumber')), line.get('covered') == 'true',
                   int(line.get('branchesToCover', 0)), int(line.get('coveredBranches', 0)))


def lookup(table, path):
    if path in table:
        return table[path]
    if path.endswith(('.kt', '.java')):
        for root in ('/src/main/kotlin/', '/src/main/java/', '/src/'):
            if root in path:
                key = 'jacoco:' + path.split(root, 1)[1]
                if key in table:
                    return table[key]
    return None


def code_line(text):
    stripped = text.strip()
    return bool(stripped) and not stripped.startswith(('#', '//', '/*', '*', '*/', '"""', "'''"))


C_STATEMENT = re.compile(r'^(if|else|for|while|do|switch|case|default|return|break|continue|goto)\b')


def c_executable(text):
    """Approximate gcov executable lines: statements inside function bodies.

    Declarations, struct/enum/initializer bodies, macros and comments are not
    executable. A brace opens a function body when the text since the previous
    top-level declaration ends with a parameter list.
    """
    flags, depth, function_depth, pending, comment = [], 0, None, '', False
    for raw in text:
        line = re.sub(r'"(?:\\.|[^"\\])*"', '""', raw)
        if comment:
            end = line.find('*/')
            line = '' if end < 0 else line[end + 2:]
            comment = end < 0
        line = re.sub(r'/\*.*?\*/', '', re.sub(r'//.*', '', line))
        if '/*' in line:
            line, comment = line[:line.index('/*')], True
        stripped = line.strip()
        inside = function_depth is not None and depth > function_depth
        flags.append(inside and bool(stripped) and not stripped.startswith('#') and stripped not in ('{', '}', '};')
                     and (stripped.endswith(';') or bool(C_STATEMENT.match(stripped)) or stripped.endswith(')')))
        if stripped.startswith('#'):
            continue
        for char in line:
            if char == '{':
                if function_depth is None and depth == 0 and re.search(r'\)\s*$', pending) and '=' not in pending \
                        and not re.search(r'\b(struct|union|enum)\b', pending.split('(')[0]):
                    function_depth = 0
                depth += 1
                pending = ''
            elif char == '}':
                depth -= 1
                if function_depth is not None and depth == function_depth:
                    function_depth = None
            elif char == ';' and depth == 0:
                pending = ''
            elif depth == 0:
                pending += char
        if depth == 0:
            pending += ' '
    return flags


def measure(repository, base, head, reports, settings):
    props = properties(settings)
    sources = [s.strip() for s in props['sonar.sources'].split(',') if s.strip()]
    exclusions = [s.strip() for s in props.get('sonar.exclusions', '').split(',') if s.strip()]
    table = {}
    reports = Path(reports)
    # A missing report leaves that language unmeasured: changed files then
    # count as uncovered, never as covered.
    for name, reader in (('python-coverage.xml', read_cobertura), ('lcov.info', read_lcov),
                         ('core-jacoco.xml', read_jacoco), ('app-jacoco.xml', read_jacoco),
                         ('c-coverage.xml', read_generic)):
        if (reports / name).is_file():
            reader(reports / name, table)
    files, total, covered = [], 0, 0
    for path, lines in sorted(changed_lines(repository, base, head).items()):
        if not in_scope(path, sources, exclusions):
            continue
        measured = lookup(table, path)
        if measured is None:
            text = subprocess.run(['git', '-C', str(repository), 'show', f'{head}:{path}'],
                                  capture_output=True, text=True, check=True).stdout.splitlines()
            if path.endswith(('.c', '.h')):
                executable = c_executable(text)
                uncovered = sum(1 for n in lines if n <= len(text) and executable[n - 1])
            else:
                uncovered = sum(1 for n in lines if n <= len(text) and code_line(text[n - 1]))
            row = {'path': path, 'toCover': uncovered, 'covered': 0, 'estimated': True}
        else:
            to_cover = hit = 0
            for n in lines:
                if n in measured:
                    line_covered, branches, branch_hits = measured[n]
                    to_cover += 1 + branches
                    hit += int(line_covered) + branch_hits
            row = {'path': path, 'toCover': to_cover, 'covered': hit, 'estimated': False}
        if row['toCover']:
            files.append(row)
            total += row['toCover']
            covered += row['covered']
    percent = 100.0 if not total else 100.0 * covered / total
    return {'base': base, 'head': head, 'toCover': total, 'covered': covered,
            'coverage': round(percent, 2), 'threshold': THRESHOLD, 'passed': percent >= THRESHOLD, 'files': files}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--head', default='HEAD')
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--repository', type=Path, default=ROOT)
    parser.add_argument('--settings', type=Path, default=ROOT / 'sonar-project.properties')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = measure(args.repository, args.base, args.head, args.reports, args.settings)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + '\n')
    for row in sorted(result['files'], key=lambda r: r['covered'] - r['toCover'])[:15]:
        mark = ' (no report: estimated)' if row['estimated'] else ''
        print(f"{row['covered']:>5}/{row['toCover']:<5} {row['path']}{mark}")
    print(f"New-code coverage {result['coverage']}% ({result['covered']}/{result['toCover']}); threshold {THRESHOLD}%")
    raise SystemExit(0 if result['passed'] else 1)


if __name__ == '__main__':
    main()
