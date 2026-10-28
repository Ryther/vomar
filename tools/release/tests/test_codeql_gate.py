import copy
import importlib.util
import json
from pathlib import Path

import pytest

SHA = 'a' * 40
CATEGORIES = ['python', 'javascript-typescript', 'actions', 'java-kotlin', 'c-cpp']


def gate():
    assert importlib.util.find_spec('tools.release.codeql_gate'), 'Missing blocking CodeQL findings gate'
    from tools.release import codeql_gate
    return codeql_gate


def sarif(severity='7.5'):
    return {'version': '2.1.0', 'runs': [{'tool': {'driver': {'name': 'CodeQL', 'rules': [
        {'id': 'js/file-system-race', 'properties': {'security-severity': severity}}]}},
        'results': [{'ruleId': 'js/file-system-race', 'ruleIndex': 0, 'level': 'warning'}]}]}


def test_successful_scan_with_high_or_critical_findings_fails_even_if_suppressed(tmp_path):
    for severity in ['7.0', '7.5', '9.8']:
        report = sarif(severity)
        report['runs'][0]['results'][0]['suppressions'] = [{'kind': 'external', 'status': 'accepted'}]
        p = tmp_path / 'javascript.sarif'; p.write_text(json.dumps(report))
        with pytest.raises(ValueError, match='CodeQL blocking findings'):
            gate().check_sarif(tmp_path)


def test_medium_findings_and_empty_successful_scan_pass(tmp_path):
    p = tmp_path / 'actions.sarif'; p.write_text(json.dumps(sarif('6.5')))
    assert gate().check_sarif(tmp_path) == 1
    report = sarif(); report['runs'][0]['results'] = []
    p.write_text(json.dumps(report)); assert gate().check_sarif(tmp_path) == 0


@pytest.mark.parametrize('damage', ['missing-report', 'malformed', 'no-runs', 'missing-results', 'bad-severity', 'missing-rule'])
def test_absent_or_incomplete_codeql_data_cannot_pass(tmp_path, damage):
    report = sarif()
    if damage == 'no-runs': report['runs'] = []
    if damage == 'missing-results': del report['runs'][0]['results']
    if damage == 'bad-severity': report['runs'][0]['tool']['driver']['rules'][0]['properties']['security-severity'] = 'NaN'
    if damage == 'missing-rule': report['runs'][0]['tool']['driver']['rules'] = []
    if damage != 'missing-report':
        (tmp_path / 'scan.sarif').write_text('{' if damage == 'malformed' else json.dumps(report))
    with pytest.raises((ValueError, KeyError)):
        gate().check_sarif(tmp_path)


def remote(sha=SHA, alerts=None, missing=None, error=''):
    analyses = [{'tool': {'name': 'CodeQL'}, 'category': '/language:' + c,
                 'ref': 'refs/heads/main', 'commit_sha': sha, 'error': error}
                for c in CATEGORIES if c != missing]
    def fetch(path):
        if path.startswith('code-scanning/analyses?'): return analyses
        if path.startswith('code-scanning/alerts?'): return alerts or []
        raise AssertionError(path)
    return fetch


def test_publication_requires_fresh_successful_analyses_in_every_language():
    assert gate().check_remote(remote(), SHA)
    for fetch in [remote(sha='b' * 40), remote(missing='c-cpp'), remote(error='Extraction failed')]:
        with pytest.raises(ValueError): gate().check_remote(fetch, SHA)


def test_publication_checks_all_pages_and_blocks_preexisting_high_alerts():
    calls = []
    medium = {'number': 2, 'state': 'open', 'tool': {'name': 'CodeQL'},
              'rule': {'security_severity_level': 'medium', 'severity': 'warning'}}
    high = {**medium, 'number': 1, 'rule': {'security_severity_level': 'high', 'severity': 'warning'}}
    def fetch(path):
        calls.append(path)
        if path.startswith('code-scanning/analyses?'): return remote()(path)
        if path.endswith('page=1'): return [copy.deepcopy(medium) for _ in range(100)]
        return [high]
    with pytest.raises(ValueError, match='CodeQL blocking findings'):
        gate().check_remote(fetch, SHA)
    assert any(p.endswith('page=2') for p in calls)


def test_publication_cannot_ignore_api_errors_or_malformed_alerts():
    def denied(path): raise PermissionError('Synthetic missing security-events permission')
    with pytest.raises(PermissionError): gate().check_remote(denied, SHA)
    for alert in [{}, {'number': 1, 'state': 'open', 'tool': {'name': 'CodeQL'}, 'rule': {}}]:
        with pytest.raises(ValueError): gate().check_remote(remote(alerts=[alert]), SHA)


def test_modern_codeql_rule_extension_is_checked_instead_of_empty_driver(tmp_path):
    report=sarif('7.7');run=report['runs'][0]
    rules=run['tool']['driver'].pop('rules')
    run['tool']['extensions']=[{'name':'codeql/javascript-queries','rules':rules}]
    result=run['results'][0];result.pop('ruleIndex')
    result['rule']={'id':result['ruleId'],'index':0,'toolComponent':{'index':0}}
    path=tmp_path/'javascript.sarif';path.write_text(json.dumps(report))
    with pytest.raises(ValueError,match='CodeQL blocking findings'):gate().check_sarif(tmp_path)
    rules[0]['properties']['security-severity']='5.0';path.write_text(json.dumps(report))
    assert gate().check_sarif(tmp_path)==1


def test_workflow_cli_returns_failure_for_high_and_success_for_medium(tmp_path):
    import subprocess,sys
    path=tmp_path/'scan.sarif'
    for severity,expected in [('7.7',1),('5.0',0)]:
        path.write_text(json.dumps(sarif(severity)))
        result=subprocess.run([sys.executable,'-m','tools.release.codeql_gate','--sarif',str(tmp_path)],capture_output=True,text=True)
        assert result.returncode==expected
        assert ('CodeQL blocking findings' in result.stderr) if expected else ('zero high/critical' in result.stdout)


def test_non_security_error_findings_also_block(tmp_path):
    report=sarif();rule=report['runs'][0]['tool']['driver']['rules'][0]
    rule['properties']={};report['runs'][0]['results'][0]['level']='error'
    (tmp_path/'scan.sarif').write_text(json.dumps(report))
    with pytest.raises(ValueError,match='CodeQL blocking findings'):gate().check_sarif(tmp_path)


def test_newer_failed_analysis_cannot_be_replaced_with_older_success():
    def fetch(path):
        if path.startswith('code-scanning/analyses?'):
            latest=remote()(path);bad={**latest[0],'error':'Analysis failed'}
            return [bad,*latest]
        return []
    with pytest.raises(ValueError,match='stale, incomplete or failed'):gate().check_remote(fetch,SHA)


@pytest.mark.parametrize('rows',[{},[{}]*101])
def test_invalid_api_pages_fail_closed(rows):
    with pytest.raises(ValueError,match='Invalid CodeQL API result page'):
        gate().check_remote(lambda path:rows,SHA)
