"""PR scans must fail on missing evidence and retain complete findings."""
import importlib
import itertools
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml


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
        field = 'components' if path.endswith('component_tree') else 'hotspots'
        return {'paging': {'pageIndex': 1, 'pageSize': 1, 'total': 0}, field: []}
    result = report.export_analysis(fetch, 'project', tmp_path, pull_request='8', page_size=1)
    assert [i['key'] for i in result['issues']] == ['1', '2']
    assert json.loads((tmp_path/'issues.json').read_text())[1]['flows'] == issue['flows']
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
