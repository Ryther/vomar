"""Local pre-push quality check with disposable services and no credentials.

Checks the committed HEAD against its merge base with the destination:

* Python, JavaScript and Kotlin issues introduced, compared on a disposable
  SonarQube Community server in Docker (the existing sonar_local comparison);
* firmware C: the locked clang-tidy on changed C files, reporting findings on
  changed lines (Community has no C analyzer);
* new-code coverage over changed lines with the Sonar formula and threshold.

Reports are regenerated in clean detached worktrees with the same commands as
CI, only for the languages the change touches. SonarCloud remains the
authoritative PR/main analysis; its proprietary C rules have no local
equivalent, so a clean precheck does not guarantee a clean Cloud gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

if __package__:
    from . import new_code_coverage, sonar_local
else:  # pragma: no cover - module execution only
    import new_code_coverage
    import sonar_local

ROOT = Path(__file__).resolve().parents[2]
LANGUAGES = {'python': ('.py',), 'javascript': ('.js',), 'kotlin': ('.kt', '.java'), 'c': ('.c', '.h')}
CACHE = Path(os.environ.get('VOMAR_CACHE', Path.home() / '.cache/vomar'))
# Diagnostics for actual defects. Style and portability checks that the
# reviewed firmware deliberately violates (memcpy, swappable parameters,
# signed bitwise on literals) are not imported.
CLANG_TIDY_CHECKS = ','.join([
    '-*', 'clang-analyzer-core.*', 'clang-analyzer-unix.*', 'clang-analyzer-deadcode.*',
    'clang-analyzer-security.FloatLoopCounter', 'clang-analyzer-security.ArrayBound',
    'bugprone-suspicious-memory-comparison', 'bugprone-sizeof-expression', 'bugprone-suspicious-memset-usage',
    'bugprone-not-null-terminated-result', 'bugprone-infinite-loop', 'bugprone-integer-division',
    'bugprone-misplaced-widening-cast', 'bugprone-assignment-in-if-condition', 'bugprone-branch-clone',
    'bugprone-macro-parentheses', 'bugprone-redundant-branch-condition', 'bugprone-signal-handler',
    'bugprone-suspicious-semicolon', 'bugprone-terminating-continue', 'bugprone-too-small-loop-variable',
    'bugprone-undefined-memory-manipulation', 'cert-err33-c', 'misc-redundant-expression',
])
# GCC-only options in the Zephyr compilation database that clang rejects.
GCC_ONLY = ('-fno-defer-pop', '-fno-printf-return-value', '-fno-reorder-functions', '-mfp16-format',
            '-specs', '--specs', '-flto', '-fno-lto', '-Werror', '-fdiagnostics-color', '-mtp', '-ftls-model',
            '-fno-optimize-sibling-calls', '-Wno-packed-bitfield-compat', '-fmacro-prefix-map')


def run(command, *, cwd, log, env=None, check=True):
    with log.open('a') as stream:
        stream.write('$ ' + ' '.join(map(str, command)) + '\n')
        stream.flush()
        result = subprocess.run([str(c) for c in command], cwd=cwd, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, check=False)
    if check and result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}), see {log}: {" ".join(map(str, command))}')
    return result.returncode


def git(*args, cwd=ROOT):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def changed_languages(changed, settings):
    props = new_code_coverage.properties(settings)
    sources = [s.strip() for s in props['sonar.sources'].split(',') if s.strip()]
    exclusions = [s.strip() for s in props.get('sonar.exclusions', '').split(',') if s.strip()]
    scoped = [p for p in changed if new_code_coverage.in_scope(p, sources, exclusions)]
    return {lang for lang, suffixes in LANGUAGES.items() if any(p.endswith(suffixes) for p in scoped)}, scoped


def python_environment(log):
    """Cached venv with the locked development and desktop dependencies."""
    locks = [ROOT / 'requirements-dev.lock', ROOT / 'requirements-desktop.lock']
    digest = hashlib.sha256(b''.join(p.read_bytes() for p in locks)).hexdigest()[:16]
    venv = CACHE / f'sonar-precheck/python-{digest}'
    python = venv / 'bin/python'
    if not (venv / 'complete').exists():
        shutil.rmtree(venv, ignore_errors=True)
        run([sys.executable, '-m', 'venv', venv], cwd=ROOT, log=log)
        run([python, '-m', 'pip', 'install', '-q', '--require-hashes', *sum((['-r', p] for p in locks), [])],
            cwd=ROOT, log=log)
        (venv / 'complete').write_text(digest + '\n')
    return python


def produce_reports(candidate, languages, reports, log):
    """The CI report commands, run in the clean candidate worktree."""
    notes = []
    if 'python' in languages:
        python = python_environment(log)
        env = {**os.environ, 'PYTHONPATH': f'{candidate}:{candidate}/apps/desktop-updater/src'}
        run([python, '-m', 'coverage', 'run', '--source=.', '-m', 'pytest', '-q', 'tools/release/tests',
             'tools/dev/tests', 'apps/desktop-updater/tests', '--ignore=apps/desktop-updater/tests/test_gui.py'],
            cwd=candidate, log=log, env=env)
        run([python, '-m', 'coverage', 'xml', '-o', reports / 'python-coverage.xml'], cwd=candidate, log=log, env=env)
        run([python, '-m', 'tools.release.prepare_pr_analysis', '--python-coverage', reports / 'python-coverage.xml',
             '--repository', '.'], cwd=candidate, log=log, env=env)
    if 'javascript' in languages:
        tests = sorted(str(p) for p in (candidate / 'integrations/zigbee2mqtt/test').glob('*.test.js'))
        run(['node', '--test', '--experimental-test-coverage', '--test-reporter=lcov',
             f'--test-reporter-destination={reports / "lcov.info"}', *tests], cwd=candidate, log=log)
    if 'kotlin' in languages:
        gradle = [candidate / 'apps/android-updater/gradlew', '-p', candidate / 'apps/android-updater',
                  '--dependency-verification=strict']
        run([*gradle, ':core:test', ':core:jacocoTestReport', ':app:testDebugUnitTest', ':app:jacocoDebugReport'],
            cwd=candidate, log=log)
        shutil.copy(candidate / 'apps/android-updater/core/build/reports/jacoco/test/jacocoTestReport.xml',
                    reports / 'core-jacoco.xml')
        shutil.copy(candidate / 'apps/android-updater/app/build/reports/jacoco/jacocoDebugReport/jacocoDebugReport.xml',
                    reports / 'app-jacoco.xml')
        notes.append('Android app coverage uses JVM unit tests only; CI adds emulator UI tests, '
                     'so local Kotlin coverage can be lower than CI.')
    if 'c' in languages:
        python = Path(sys.executable)
        coverage_dir = reports.parent / 'c-coverage'
        run([python, '-m', 'tools.release.c_coverage', '--output', coverage_dir], cwd=candidate, log=log)
        shutil.copy(coverage_dir / 'c-coverage.xml', reports / 'c-coverage.xml')
        build = candidate / '_test/ci-firmware'
        run([python, '-m', 'tools.release.ci_firmware', '--output', build], cwd=candidate, log=log)
        run([python, '-m', 'tools.release.capture_analysis', '--build', build, '--output', reports],
            cwd=candidate, log=log)
    return notes


def gcc_internal(path):
    """GCC's own builtin headers (arm_acle.h, stddef.h, ...), which clang rejects."""
    return re.search(r'/lib/gcc/[^/]+/[^/]+/include(-fixed)?/?$', path) is not None


def clang_arguments(arguments, resource=None):
    """Adapt a Zephyr GCC invocation: drop GCC-only options and replace GCC's
    internal header directory with clang's builtin headers."""
    result, skip, index = [], False, 1
    while index < len(arguments):
        arg = arguments[index]
        index += 1
        if skip:
            skip = False
            continue
        if arg == '--param':
            skip = True
            continue
        if arg.startswith('--param') or arg.split('=', 1)[0] in GCC_ONLY:
            continue
        if arg == '-isystem' and index < len(arguments) and gcc_internal(arguments[index]):
            path = arguments[index]
            index += 1
            if resource is not None and not path.rstrip('/').endswith('-fixed'):
                result.extend(['-isystem', str(resource)])
            continue
        if arg.startswith('-isystem') and len(arg) > 8 and gcc_internal(arg[8:]):
            if resource is not None and not arg.rstrip('/').endswith('-fixed'):
                result.append('-isystem' + str(resource))
            continue
        result.append(arg)
    return [arguments[0], *result]


def clang_resource():
    import clang_tidy  # the locked wheel ships the binary and builtin headers
    found = sorted((Path(clang_tidy.__file__).parent / 'data/lib/clang').glob('*/include'))
    if not found:
        raise RuntimeError('clang-tidy builtin headers are missing from the locked package')
    return found[-1]


def clang_tidy(candidate, scoped, changed, reports, output, log):
    """Locked clang-tidy on changed C files; findings on changed lines only."""
    rows = json.loads((reports / 'compile_commands.json').read_text())
    database = output / 'clang-tidy'
    database.mkdir(exist_ok=True)
    tool = Path(sys.executable).with_name('clang-tidy')
    resource = clang_resource()
    entries, sources = [], set()
    for row in rows:
        path = Path(row['file']).resolve()
        if path.is_relative_to(candidate):
            relative = path.relative_to(candidate).as_posix()
            if relative in scoped and relative.endswith('.c') and relative not in sources:
                sources.add(relative)
                entries.append({**row, 'arguments': clang_arguments(row['arguments'], resource)})
    (database / 'compile_commands.json').write_text(json.dumps(entries))
    unbuilt = sorted(p for p in scoped if p.endswith('.c') and p not in sources)
    findings = []
    pattern = re.compile(r'^(?P<path>/[^:]+):(?P<line>\d+):(?P<col>\d+): (?P<kind>warning|error): (?P<message>.*) \[(?P<check>[^\]]+)\]$')
    for source in sorted(sources):
        result = subprocess.run([str(tool), '-p', str(database), f'--checks={CLANG_TIDY_CHECKS}', '--quiet',
                                 '--extra-arg=--target=arm-none-eabi', '--extra-arg=-Wno-unknown-warning-option',
                                 str(candidate / source)], capture_output=True, text=True, check=False)
        with log.open('a') as stream:
            stream.write(result.stdout + result.stderr)
        for line in result.stdout.splitlines():
            match = pattern.match(line)
            if not match:
                continue
            path = Path(match['path']).resolve()
            if match['kind'] == 'error':
                # A translation unit that does not compile was not analyzed.
                relative = path.relative_to(candidate).as_posix() if path.is_relative_to(candidate) else str(path)
                findings.append({'path': relative, 'line': int(match['line']), 'check': match['check'],
                                 'message': 'not analyzed: ' + match['message']})
                continue
            if not path.is_relative_to(candidate):
                continue
            relative = path.relative_to(candidate).as_posix()
            if int(match['line']) in changed.get(relative, ()):
                findings.append({'path': relative, 'line': int(match['line']), 'check': match['check'],
                                 'message': match['message']})
    return findings, unbuilt


def community(base, candidate, reports, output, log):
    """The existing disposable SonarQube comparison on a private network."""
    name = 'vomar-sonar-' + secrets.token_hex(6)
    network = name + '-net'
    images = sonar_local.IMAGES
    self_container = os.environ.get('HOSTNAME') if Path('/.dockerenv').exists() else None
    subprocess.run(['docker', 'network', 'create', network], check=True, capture_output=True)
    connected = False
    try:
        server = ['docker', 'run', '--detach', '--name', name, '--network', network, '--network-alias', 'sonarqube',
                  '--memory=4g', '--cpus=2', '-e', 'SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true']
        if self_container:
            subprocess.run(['docker', 'network', 'connect', network, self_container], check=True, capture_output=True)
            connected = True
            sonar_local.SERVER = 'http://sonarqube:9000'
        else:
            server += ['--publish', '127.0.0.1::9000']
        subprocess.run([*server, images['library/sonarqube']], check=True, capture_output=True)
        if not self_container:
            port = subprocess.run(['docker', 'port', name, '9000'], check=True, capture_output=True,
                                  text=True).stdout.split(':')[-1].strip()
            sonar_local.SERVER = f'http://127.0.0.1:{port}'
        sonar_local.SCANNER_NETWORK = network
        sonar_local.SCANNER_SERVER = 'http://sonarqube:9000'
        sonar_local.REPORTS = reports
        sonar_local.projects()
        try:
            sonar_local.compare(base, candidate, output / 'sonar')
            return []
        except RuntimeError as error:
            introduced = output / 'sonar/introduced.json'
            return json.loads(introduced.read_text()) if introduced.exists() else [{'message': str(error)}]
    finally:
        with log.open('a') as stream:
            subprocess.run(['docker', 'logs', name], stdout=stream, stderr=subprocess.STDOUT, check=False)
        subprocess.run(['docker', 'rm', '--force', name], check=False, capture_output=True)
        if connected:
            subprocess.run(['docker', 'network', 'disconnect', network, self_container], check=False,
                           capture_output=True)
        subprocess.run(['docker', 'network', 'rm', network], check=False, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base', default='origin/main', help='Destination ref; its merge base is compared')
    parser.add_argument('--keep', action='store_true', help='Keep the clean worktrees after the run')
    args = parser.parse_args()
    if git('status', '--porcelain', '--untracked-files=normal'):
        raise SystemExit('Commit or remove local changes first: the precheck analyzes committed HEAD only.')
    head = git('rev-parse', 'HEAD')
    base = git('merge-base', args.base, 'HEAD')
    # Keep paths short: Zephyr/ninja derive file names from the source path and
    # exceed the 255-byte limit beneath a long worktree directory.
    output = ROOT / '_test/pc' / head[:8]
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    log = output / 'precheck.log'
    reports = output / 'reports'
    reports.mkdir()
    changed = new_code_coverage.changed_lines(ROOT, base, head)
    languages, scoped = changed_languages(changed, ROOT / 'sonar-project.properties')
    worktrees = {'base': output / 'b', 'candidate': output / 'c'}
    git('worktree', 'add', '--detach', str(worktrees['base']), base)
    git('worktree', 'add', '--detach', str(worktrees['candidate']), head)
    summary = {'head': head, 'base': base, 'languages': sorted(languages), 'notes': []}
    completed = False
    try:
        candidate = worktrees['candidate'].resolve()
        summary['notes'] += produce_reports(candidate, languages, reports, log)
        coverage = new_code_coverage.measure(ROOT, base, head, reports, ROOT / 'sonar-project.properties')
        summary['coverage'] = coverage
        summary['clangTidy'], summary['unbuiltC'] = ([], [])
        if 'c' in languages:
            summary['clangTidy'], summary['unbuiltC'] = clang_tidy(candidate, scoped, changed, reports, output, log)
        summary['introduced'] = []
        if languages & {'python', 'javascript', 'kotlin'}:
            summary['introduced'] = community(worktrees['base'].resolve(), candidate, reports, output, log)
        completed = True
    finally:
        # A failed step keeps its worktrees and build logs for diagnosis.
        if completed and not args.keep:
            for path in worktrees.values():
                subprocess.run(['git', '-C', str(ROOT), 'worktree', 'remove', '--force', str(path)],
                               check=False, capture_output=True)
    failures = []
    if not summary['coverage']['passed']:
        failures.append(f"new-code coverage {summary['coverage']['coverage']}% < {new_code_coverage.THRESHOLD}%")
    if summary['clangTidy']:
        failures.append(f"{len(summary['clangTidy'])} clang-tidy findings on changed C lines")
    if summary['introduced']:
        failures.append(f"{len(summary['introduced'])} Sonar Community issues introduced")
    summary['passed'] = not failures
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(f'Languages: {", ".join(sorted(languages)) or "none in Sonar scope"}')
    print(f"New-code coverage: {summary['coverage']['coverage']}% "
          f"({summary['coverage']['covered']}/{summary['coverage']['toCover']})")
    for finding in summary['clangTidy']:
        print(f"clang-tidy {finding['path']}:{finding['line']} [{finding['check']}] {finding['message']}")
    for issue in summary['introduced']:
        print(f"Sonar {issue.get('rule', '')} {issue.get('component', '')} {issue.get('message', '')}")
    for path in summary['unbuiltC']:
        print(f'Note: {path} is not compiled by any CI firmware profile; clang-tidy did not analyze it.')
    for note in summary['notes']:
        print('Note: ' + note)
    print(f'Report: {output / "summary.json"}')
    if failures:
        raise SystemExit('Precheck failed: ' + '; '.join(failures))
    print('Precheck passed. SonarCloud on the PR remains authoritative for C rules.')


if __name__ == '__main__':
    main()
