"""PR scans must fail on missing evidence and retain complete findings."""
import importlib
import itertools
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
import runpy

import pytest
import yaml


@pytest.fixture
def repository_python_report(tmp_path):
    import coverage
    repository=tmp_path/'repository';repository.mkdir()
    files=('tools/release/manifest.py','apps/desktop-updater/src/vomar_updater/runtime.py')
    for filename in files:
        path=repository/filename;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('enabled=True\nif enabled:\n    value=7\nelse:\n    value=3\n')
    report=tmp_path/'python-coverage.xml'
    measured=coverage.Coverage(source=[str(repository)],branch=True,config_file=False,data_file=None)
    measured.start()
    try:
        for filename in files:runpy.run_path(str(repository/filename))
    finally:measured.stop()
    measured.xml_report(outfile=str(report))
    return repository,report


def test_repository_python_coverage_survives_legacy_preparation_without_changing_measures(repository_python_report,tmp_path):
    prepare=importlib.import_module('tools.release.prepare_pr_analysis')
    repository,report=repository_python_report
    original=ET.parse(report)
    measures=ET.tostring(original.find('./packages'))
    prepare.normalize_python_coverage(report,repository)
    normalized=ET.parse(report)
    assert normalized.findall('./sources/source')==[]
    assert ET.tostring(normalized.find('./packages'))==measures
    reports=tmp_path/'reports';reports.mkdir();report.rename(reports/report.name)
    sha='a'*40
    (reports/'component-versions.json').write_text(json.dumps({'commit':sha}))
    (reports/'lcov.info').write_text('SF:integrations/zigbee2mqtt/index.js\nDA:1,1\nend_of_record\n')
    for name in ('core-jacoco.xml','app-jacoco.xml'):(reports/name).write_text('<report><package name="synthetic"/></report>')
    prepare.prepare(reports,repository,sha)
    prepared=ET.parse(reports/report.name)
    assert [source.text for source in prepared.findall('./sources/source')]==[str(repository)]
    assert ET.tostring(prepared.find('./packages'))==measures
    files={item.get('filename') for item in prepared.findall('.//class')}
    assert files=={'tools/release/manifest.py','apps/desktop-updater/src/vomar_updater/runtime.py'}
    for item in prepared.findall('.//class'):
        assert (repository/item.get('filename')).is_file()
        assert any(int(line.get('hits'))>0 for line in item.findall('./lines/line'))
        assert any(line.get('condition-coverage')=='50% (1/2)' for line in item.findall('./lines/line'))


@pytest.mark.parametrize('filename',['/tmp/outside.py','../outside.py','tools/../outside.py','C:/outside.py',r'tools\outside.py','tools/missing.py'])
def test_repository_python_coverage_refuses_unsafe_or_missing_paths(repository_python_report,filename):
    prepare=importlib.import_module('tools.release.prepare_pr_analysis')
    repository,report=repository_python_report
    tree=ET.parse(report);tree.find('.//class').set('filename',filename);tree.write(report)
    original=report.read_bytes()
    with pytest.raises(ValueError,match='coverage'):prepare.normalize_python_coverage(report,repository)
    assert report.read_bytes()==original


def test_repository_python_coverage_requires_exact_measured_repository(repository_python_report):
    prepare=importlib.import_module('tools.release.prepare_pr_analysis')
    repository,report=repository_python_report
    tree=ET.parse(report);tree.find('./sources/source').text=str(repository/'apps');tree.write(report)
    original=report.read_bytes()
    with pytest.raises(ValueError,match='coverage'):prepare.normalize_python_coverage(report,repository)
    assert report.read_bytes()==original


def test_only_expected_successful_scan_with_reports_can_pass():
    gate = importlib.import_module('tools.release.sonar_gate')
    for trusted, coverage, cloud, community, report in itertools.product(
        (True, False), ('success', 'failure', 'skipped', 'cancelled'),
        ('success', 'failure', 'skipped'), ('success', 'failure', 'skipped'),
        (True, False),
    ):
        expected = (coverage == 'success' and report and
                    ((trusted and cloud == 'success' and community == 'skipped') or
                     (not trusted and community == 'success' and cloud == 'skipped')))
        assert gate.evaluate('pull_request', trusted, coverage, cloud, community, report) == expected
    assert not gate.evaluate('unknown', True, 'success', 'success', 'skipped', True)


def test_gate_rejects_malformed_environment_flags(monkeypatch):
    gate = importlib.import_module('tools.release.sonar_gate')
    monkeypatch.setenv('SONAR_EVENT_NAME', 'pull_request')
    monkeypatch.setenv('SONAR_TRUSTED_PR', 'yes')
    with pytest.raises((SystemExit, ValueError)):
        gate.main()


def test_export_retains_all_paginated_findings_and_missing_pages_fail(tmp_path):
    report = importlib.import_module('tools.release.sonar_report')
    issue = {'key': 'one', 'component': 'project:apps/main.py', 'rule': 'python:S1',
             'message': 'first', 'flows': [{'locations': []}]}
    def fetch(path, params):
        if path.endswith('project_status'):
            return {'projectStatus': {'status': 'OK', 'conditions': []}}
        if path.endswith('/component'):
            return {'component': {'key': 'project', 'measures': []}}
        if path.endswith('/issues/search'):
            item = {**issue, 'key': str(params['p'])}
            return {'paging': {'pageIndex': params['p'], 'pageSize': 1, 'total': 2}, 'issues': [item]}
        if path.endswith('/hotspots/search'):
            assert params == {'projectKey': 'project', 'pullRequest': '8', 'p': 1, 'ps': 1}
            return {'paging': {'pageIndex': 1, 'pageSize': 1, 'total': 1},
                    'hotspots': [{'key': 'hotspot-one', 'status': 'TO_REVIEW'}]}
        field = 'components' if path.endswith('component_tree') else 'hotspots'
        return {'paging': {'pageIndex': 1, 'pageSize': 1, 'total': 0}, field: []}
    result = report.export_analysis(fetch, 'project', tmp_path, pull_request='8', page_size=1)
    assert [i['key'] for i in result['issues']] == ['1', '2']
    assert json.loads((tmp_path/'issues.json').read_text())[1]['flows'] == issue['flows']
    assert json.loads((tmp_path/'hotspots.json').read_text()) == [
        {'key': 'hotspot-one', 'status': 'TO_REVIEW'}]
    assert (tmp_path/'report.md').is_file()
    def missing(path, params):
        value = fetch(path, params)
        if path.endswith('/issues/search') and params['p'] == 2:
            value['issues'] = []
        return value
    with pytest.raises(ValueError, match='pagination'):
        report.export_analysis(missing, 'project', tmp_path/'missing', page_size=1)


def test_community_success_is_scoped_and_quality_failures_cannot_pass():
    local = importlib.import_module('tools.release.sonar_local')
    assert local.candidate_scan_ok(0, 'OK')
    assert not local.candidate_scan_ok(1, 'OK')
    assert not local.candidate_scan_ok(0, 'ERROR')
    assert not local.candidate_scan_ok(0, 'NONE')


@pytest.fixture
def coverage_inputs(tmp_path):
    reports = tmp_path/'reports'; reports.mkdir()
    candidate = tmp_path/'candidate'; candidate.mkdir()
    sha = 'a'*40
    (reports/'component-versions.json').write_text(json.dumps({'commit': sha}))
    (reports/'python-coverage.xml').write_text(
        '<coverage lines-covered="1" lines-valid="2"><sources>'
        '<source>/old/apps/desktop-updater/src/vomar_updater</source></sources>'
        '<packages><package name="core"><classes>'
        '<class filename="apps/desktop-updater/src/vomar_updater/__init__.py">'
        '<lines><line number="1" hits="1"/><line number="2" hits="0"/></lines>'
        '</class></classes></package></packages></coverage>')
    source = candidate/'apps/desktop-updater/src/vomar_updater/__init__.py'
    source.parent.mkdir(parents=True)
    source.write_text('"""Synthetic fixture."""\nVALUE = 1\n')
    (reports/'lcov.info').write_text('SF:integrations/zigbee2mqtt/index.js\nDA:1,1\nend_of_record\n')
    for name in ('core-jacoco.xml','app-jacoco.xml'):
        (reports/name).write_text('<report><package name="org/openvimar"/></report>')
    return reports, candidate, sha


def test_pr_reports_require_same_commit_and_remap_only_known_sources(coverage_inputs):
    prepare = importlib.import_module('tools.release.prepare_pr_analysis')
    reports, candidate, sha = coverage_inputs
    prepare.prepare(reports, candidate, sha)
    with pytest.raises(ValueError, match='commit'):
        prepare.prepare(reports, candidate, 'b'*40)
    (reports/'core-jacoco.xml').unlink()
    with pytest.raises(ValueError, match='report'):
        prepare.prepare(reports, candidate, sha)


@pytest.mark.parametrize('filename', [
    'apps/desktop-updater/src/vomar_updater/__init__.py',
    '__init__.py',
    'vomar_updater/__init__.py',
    '/old/apps/desktop-updater/src/vomar_updater/__init__.py',
])
def test_python_coverage_paths_resolve_without_losing_measures(coverage_inputs, filename):
    prepare = importlib.import_module('tools.release.prepare_pr_analysis')
    reports, candidate, sha = coverage_inputs
    path = reports/'python-coverage.xml'
    tree = ET.parse(path)
    tree.find('.//class').set('filename', filename)
    tree.write(path)
    prepare.prepare(reports, candidate, sha)
    root = ET.parse(path).getroot()
    assert [source.text for source in root.findall('./sources/source')] == [str(candidate)]
    classes = root.findall('.//class')
    assert len(classes) == 1
    assert classes[0].get('filename') == 'apps/desktop-updater/src/vomar_updater/__init__.py'
    assert (candidate/classes[0].get('filename')).is_file()
    assert root.get('lines-covered') == '1' and root.get('lines-valid') == '2'
    assert [line.attrib for line in classes[0].findall('./lines/line')] == [
        {'number': '1', 'hits': '1'}, {'number': '2', 'hits': '0'}]


def test_python_coverage_keeps_every_repository_source(coverage_inputs):
    prepare = importlib.import_module('tools.release.prepare_pr_analysis')
    reports, candidate, sha = coverage_inputs
    source = candidate/'tools/firmware/loader_runtime_contract.py'
    source.parent.mkdir(parents=True)
    source.write_text('VALUE = 1\n')
    tree = ET.parse(reports/'python-coverage.xml')
    classes = tree.find('.//classes')
    extra = ET.SubElement(classes, 'class', filename='tools/firmware/loader_runtime_contract.py')
    ET.SubElement(ET.SubElement(extra, 'lines'), 'line', number='1', hits='3')
    tree.write(reports/'python-coverage.xml')
    prepare.prepare(reports, candidate, sha)
    root = ET.parse(reports/'python-coverage.xml').getroot()
    sources = root.findall('./sources/source')
    assert [element.text for element in sources] == [str(candidate)]
    classes = root.findall('.//class')
    assert [element.get('filename') for element in classes] == [
        'apps/desktop-updater/src/vomar_updater/__init__.py',
        'tools/firmware/loader_runtime_contract.py']
    assert classes[1].find('./lines/line').attrib == {'number': '1', 'hits': '3'}


@pytest.mark.parametrize('filename', [
    '../outside.py', '/etc/passwd', 'missing.py', '',
    'apps/desktop-updater/src/vomar_updater/../../outside.py',
])
def test_python_coverage_rejects_unresolvable_or_escaping_sources(coverage_inputs, filename):
    prepare = importlib.import_module('tools.release.prepare_pr_analysis')
    reports, candidate, sha = coverage_inputs
    tree = ET.parse(reports/'python-coverage.xml')
    tree.find('.//class').set('filename', filename)
    tree.write(reports/'python-coverage.xml')
    with pytest.raises(ValueError, match='Python coverage source'):
        prepare.prepare(reports, candidate, sha)


def test_python_coverage_rejects_source_symlink_outside_candidate(coverage_inputs, tmp_path):
    prepare = importlib.import_module('tools.release.prepare_pr_analysis')
    reports, candidate, sha = coverage_inputs
    source = candidate/'apps/desktop-updater/src/vomar_updater/__init__.py'
    source.unlink()
    outside = tmp_path/'outside.py'
    outside.write_text('SECRET = "synthetic"\n')
    source.symlink_to(outside)
    with pytest.raises(ValueError, match='Python coverage source'):
        prepare.prepare(reports, candidate, sha)


def test_python_coverage_rejects_empty_class_list(coverage_inputs):
    prepare = importlib.import_module('tools.release.prepare_pr_analysis')
    reports, candidate, sha = coverage_inputs
    (reports/'python-coverage.xml').write_text('<coverage><packages/></coverage>')
    with pytest.raises(ValueError, match='Python coverage source'):
        prepare.prepare(reports, candidate, sha)


@pytest.mark.parametrize('stale,changed,task_status', [(False,False,'SUCCESS'), (True,False,'SUCCESS'), (False,True,'SUCCESS'), (False,False,'FAILED')])
def test_cloud_export_binds_receipt_gate_and_detects_replaced_pr_analysis(tmp_path, stale, changed, task_status):
    report = importlib.import_module('tools.release.sonar_report')
    receipt = tmp_path/'report-task.txt'
    receipt.write_text('projectKey=project\nceTaskId=task-A\n')
    sha = 'a'*40
    reads = 0
    def fetch(path, params):
        nonlocal reads
        if path == '/api/ce/task':
            return {'task': {'id': 'task-A', 'componentKey': 'project', 'pullRequest': '8',
                             'status': task_status, 'analysisId': 'analysis-A'}}
        if path == '/api/project_pull_requests/list':
            reads += 1
            revision = 'b'*40 if stale else sha
            return {'pullRequests': [{'key':'8', 'commit': {'sha':revision},
                                     'analysisDate': 'later' if changed and reads > 1 else 'original'}]}
        if path.endswith('/project_status'):
            assert params == {'analysisId': 'analysis-A'}
            return {'projectStatus': {'status': 'OK', 'conditions': []}}
        if path.endswith('/component'):
            return {'component': {'key': 'project', 'measures': []}}
        field = 'issues' if path.endswith('/issues/search') else 'hotspots' if path.endswith('/hotspots/search') else 'components'
        return {'paging': {'pageIndex': 1, 'pageSize': 500, 'total': 0}, field: []}
    if stale or changed or task_status != 'SUCCESS':
        with pytest.raises(ValueError):
            report.export_candidate(fetch, 'project', tmp_path/'out', '8', sha, receipt)
        assert not (tmp_path/'out/identity.json').exists()
    else:
        report.export_candidate(fetch, 'project', tmp_path/'out', '8', sha, receipt)
        identity = json.loads((tmp_path/'out/identity.json').read_text())
        assert identity['sourceCommit'] == sha and identity['analysisId'] == 'analysis-A'


def test_failed_cloud_gate_exports_complete_findings_before_failing(tmp_path):
    report = importlib.import_module('tools.release.sonar_report')
    receipt = tmp_path/'report-task.txt'
    receipt.write_text('projectKey=project\nceTaskId=task-A\n')
    issue = {'key': 'one', 'component': 'project:apps/main.py', 'rule': 'python:S1',
             'message': 'first', 'flows': [{'locations': []}]}
    def fetch(path, params):
        if path == '/api/ce/task':
            return {'task': {'id': 'task-A', 'componentKey': 'project', 'pullRequest': '8',
                             'status': 'SUCCESS', 'analysisId': 'analysis-A'}}
        if path == '/api/project_pull_requests/list':
            return {'pullRequests': [{'key': '8', 'commit': {'sha': 'a'*40},
                                     'analysisDate': 'original'}]}
        if path.endswith('/project_status'):
            assert params == {'analysisId': 'analysis-A'}
            return {'projectStatus': {'status': 'ERROR', 'conditions': [
                {'metricKey': 'new_coverage', 'status': 'ERROR', 'actualValue': '15.8',
                 'errorThreshold': '80'}]}}
        if path.endswith('/component'):
            assert 'new_coverage' in params['metricKeys'].split(',')
            return {'component': {'key': 'project', 'measures': []}}
        if path.endswith('/issues/search'):
            return {'paging': {'pageIndex': 1, 'pageSize': 500, 'total': 1}, 'issues': [issue]}
        if path.endswith('/component_tree'):
            assert {'new_lines_to_cover', 'new_uncovered_lines', 'new_uncovered_conditions'} <= set(params['metricKeys'].split(','))
        field = 'hotspots' if path.endswith('/hotspots/search') else 'components'
        return {'paging': {'pageIndex': 1, 'pageSize': 500, 'total': 0}, field: []}
    output = tmp_path/'out'
    with pytest.raises(ValueError, match='quality gate failed'):
        report.export_candidate(fetch, 'project', output, '8', 'a'*40, receipt)
    assert json.loads((output/'gate.json').read_text())['projectStatus']['status'] == 'ERROR'
    assert json.loads((output/'issues.json').read_text()) == [issue]
    assert json.loads((output/'identity.json').read_text())['sourceCommit'] == 'a'*40
    summary = (output/'report.md').read_text()
    assert '**ERROR**' in summary
    assert 'new_coverage' in summary and '15.8' in summary and '80' in summary
    for name in ('measures.json', 'files.json', 'hotspots.json'):
        assert (output/name).is_file()


@pytest.mark.parametrize('export_status,scan_outcome,expected', [
    (1, 'failure', 1), (0, 'failure', 1), (0, 'success', 0),
])
def test_cloud_workflow_summarizes_reports_even_when_export_fails(
        tmp_path, export_status, scan_outcome, expected):
    workflow = yaml.safe_load((Path(__file__).resolve().parents[3]/
                               '.github/workflows/sonar-pr.yml').read_text())
    step = next(step for step in workflow['jobs']['cloud']['steps']
                if step.get('name') == 'Export complete PR findings')
    receipt = tmp_path/'sonar-report/task/report-task.txt'
    receipt.parent.mkdir(parents=True)
    receipt.write_text('projectKey=project\nceTaskId=task-A\n')
    binary = tmp_path/'bin/python'
    binary.parent.mkdir()
    binary.write_text('#!/bin/sh\nprintf "# Synthetic gate report\\n" > sonar-report/report.md\n'
                      'exit "$EXPORT_STATUS"\n')
    binary.chmod(0o755)
    summary = tmp_path/'step-summary.md'
    result = subprocess.run(['bash', '-e', '-c', step['run']], cwd=tmp_path,
                            env={'PATH': str(binary.parent)+os.pathsep+os.defpath,
                                 'EXPORT_STATUS': str(export_status), 'PR_NUMBER': '8',
                                 'SCAN_OUTCOME': scan_outcome, 'CANDIDATE_SHA': 'a'*40,
                                 'GITHUB_STEP_SUMMARY': str(summary)},
                            capture_output=True, text=True)
    assert summary.read_text() == '# Synthetic gate report\n'
    assert result.returncode == expected


@pytest.mark.parametrize('backend,project_parameter', [('cloud', 'projectKey'), ('community', 'project')])
def test_hotspot_export_uses_backend_protocol_and_retains_every_page(tmp_path, backend, project_parameter):
    report = importlib.import_module('tools.release.sonar_report')
    hotspots = [{'key': f'hotspot-{number}', 'component': 'project:apps/main.py',
                 'securityCategory': 'weak-cryptography', 'message': f'Finding {number}',
                 'textRange': {'startLine': number, 'endLine': number}}
                for number in range(1, 504)]
    def fetch(path, params):
        if path.endswith('/project_status'):
            return {'projectStatus': {'status': 'OK', 'conditions': []}}
        if path.endswith('/component'):
            return {'component': {'key': 'project', 'measures': []}}
        if path.endswith('/hotspots/search'):
            assert params == {project_parameter: 'project', 'p': params['p'], 'ps': 500}
            start = (params['p']-1)*500
            return {'paging': {'pageIndex': params['p'], 'pageSize': 500, 'total': 503},
                    'hotspots': hotspots[start:start+500]}
        field = 'issues' if path.endswith('/issues/search') else 'components'
        return {'paging': {'pageIndex': 1, 'pageSize': 500, 'total': 0}, field: []}
    result = report.export_analysis(fetch, 'project', tmp_path/backend, backend=backend)
    assert result['hotspots'] == hotspots
    assert json.loads((tmp_path/backend/'hotspots.json').read_text()) == hotspots
    assert 'Security hotspots: **503**' in (tmp_path/backend/'report.md').read_text()
    def missing(path, params):
        response = fetch(path, params)
        if path.endswith('/hotspots/search') and params['p'] == 2:
            response['hotspots'] = []
        return response
    with pytest.raises(ValueError, match='Incomplete Sonar pagination'):
        report.export_analysis(missing, 'project', tmp_path/'missing', backend=backend)


def test_hotspot_export_rejects_unknown_backend(tmp_path):
    report = importlib.import_module('tools.release.sonar_report')
    def fetch(path, params):
        raise RuntimeError('An unknown backend must fail before any API call')
    with pytest.raises(ValueError, match='backend'):
        report.export_analysis(fetch, 'project', tmp_path, backend='unsupported')


@pytest.mark.parametrize('backend_flags,project_parameter', [([], 'projectKey'), (['--backend', 'community'], 'project')])
def test_report_cli_selects_hotspot_protocol_explicitly_for_custom_host(tmp_path, monkeypatch, backend_flags, project_parameter):
    report = importlib.import_module('tools.release.sonar_report')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('SONAR_TOKEN', raising=False)
    def fetch(path, params):
        if path.endswith('/project_status'):
            return {'projectStatus': {'status': 'OK', 'conditions': []}}
        if path.endswith('/component'):
            return {'component': {'key': 'project', 'measures': []}}
        if path.endswith('/hotspots/search'):
            assert params == {project_parameter: 'project', 'p': 1, 'ps': 500}
            return {'paging': {'pageIndex': 1, 'pageSize': 500, 'total': 1},
                    'hotspots': [{'key': 'synthetic-hotspot'}]}
        field = 'issues' if path.endswith('/issues/search') else 'components'
        return {'paging': {'pageIndex': 1, 'pageSize': 500, 'total': 0}, field: []}
    def http_fetch(host, token):
        assert host == 'http://127.0.0.1:43210' and token == ''
        return fetch
    monkeypatch.setattr(report, '_http_fetch', http_fetch)
    monkeypatch.setattr('sys.argv', ['sonar_report', '--host', 'http://127.0.0.1:43210',
                                    '--project', 'project', *backend_flags])
    report.main()
    assert json.loads((tmp_path/'sonar-report/hotspots.json').read_text()) == [{'key': 'synthetic-hotspot'}]


def test_report_cli_rejects_community_pr_export(tmp_path, monkeypatch, capsys):
    report = importlib.import_module('tools.release.sonar_report')
    monkeypatch.setattr('sys.argv', ['sonar_report', '--backend', 'community',
                                    '--project', 'project', '--pull-request', '8',
                                    '--sha', 'a'*40, '--task-file', str(tmp_path/'receipt')])
    with pytest.raises(SystemExit) as stopped:
        report.main()
    assert stopped.value.code == 2
    assert 'PR export requires Cloud backend' in capsys.readouterr().err


@pytest.mark.parametrize('hotspot_parameter,export_status', [('project', '0'), ('projectKey', '0'), ('project', '1')])
def test_cloud_workflow_adapts_only_protected_hotspot_requests(tmp_path, hotspot_parameter, export_status):
    import sys
    workflow = yaml.safe_load((Path(__file__).resolve().parents[3]/
                               '.github/workflows/sonar-pr.yml').read_text())
    step = next(step for step in workflow['jobs']['cloud']['steps']
                if step.get('name') == 'Export complete PR findings')
    package = tmp_path/'trusted/tools/release'
    package.mkdir(parents=True)
    for parent in (package, package.parent):
        (parent/'__init__.py').write_text('')
    (package/'sonar_report.py').write_text('''
import json
import os
from pathlib import Path

def _http_fetch(host, token):
    assert host == "https://sonarcloud.io" and token == ""
    def fetch(path, params):
        if path == "/api/hotspots/search":
            assert params == {"projectKey": "Ryther_vomar", "pullRequest": "8", "p": 2, "ps": 500}
        else:
            assert path == "/api/issues/search"
            assert params == {"componentKeys": "Ryther_vomar", "resolved": "false", "pullRequest": "8", "p": 1, "ps": 500}
        with Path("calls.jsonl").open("a") as output:
            output.write(json.dumps({"path": path, "params": params})+"\\n")
        return {}
    return fetch

def export_candidate(fetch, project, directory, pull_request, sha, receipt):
    assert project == "Ryther_vomar" and pull_request == "8" and sha == "a"*40
    assert directory == Path("sonar-report") and receipt == Path("sonar-report/task/report-task.txt")
    assert receipt.read_text() == "projectKey=Ryther_vomar\\nceTaskId=task-A\\n"
    fetch("/api/hotspots/search", {os.environ["HOTSPOT_PARAMETER"]: project, "pullRequest": pull_request, "p": 2, "ps": 500})
    fetch("/api/issues/search", {"componentKeys": project, "resolved": "false", "pullRequest": pull_request, "p": 1, "ps": 500})
    (directory/"report.md").write_text("# Protected exporter report\\n")
    if os.environ["EXPORT_STATUS"] != "0":
        raise ValueError("Synthetic protected exporter failure")
''')
    candidate = tmp_path/'candidate/tools/release'
    candidate.mkdir(parents=True)
    (candidate/'sonar_report.py').write_text('raise AssertionError("Candidate helper must never execute")\n')
    receipt = tmp_path/'sonar-report/task/report-task.txt'
    receipt.parent.mkdir(parents=True)
    receipt.write_text('projectKey=Ryther_vomar\nceTaskId=task-A\n')
    summary = tmp_path/'summary.md'
    result = subprocess.run(['bash', '-e', '-c', step['run']], cwd=tmp_path,
                            env={'PATH': str(Path(sys.executable).parent)+os.pathsep+os.defpath,
                                 'SONAR_TOKEN': '', 'PR_NUMBER': '8', 'CANDIDATE_SHA': 'a'*40,
                                 'SCAN_OUTCOME': 'success', 'EXPORT_STATUS': export_status,
                                 'HOTSPOT_PARAMETER': hotspot_parameter,
                                 'GITHUB_STEP_SUMMARY': str(summary)}, capture_output=True, text=True)
    calls = [json.loads(line) for line in (tmp_path/'calls.jsonl').read_text().splitlines()]
    assert [call['path'] for call in calls] == ['/api/hotspots/search', '/api/issues/search']
    assert summary.read_text() == '# Protected exporter report\n'
    assert result.returncode == int(export_status)
