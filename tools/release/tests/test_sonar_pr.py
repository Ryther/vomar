"""PR scans must fail on missing evidence and retain complete findings."""
import importlib
import itertools
import json
from pathlib import Path

import pytest


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
            assert params == {'project': 'project', 'pullRequest': '8', 'p': 1, 'ps': 1}
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


def test_pr_reports_require_same_commit_and_remap_only_known_sources(tmp_path):
    prepare = importlib.import_module('tools.release.prepare_pr_analysis')
    reports = tmp_path/'reports'; reports.mkdir()
    candidate = tmp_path/'candidate'; candidate.mkdir()
    sha = 'a'*40
    (reports/'component-versions.json').write_text(json.dumps({'commit': sha}))
    (reports/'python-coverage.xml').write_text('<coverage><sources><source>/old/apps/desktop-updater/src/vomar_updater</source></sources><packages><package name="core"/></packages></coverage>')
    (reports/'lcov.info').write_text('SF:integrations/zigbee2mqtt/index.js\nDA:1,1\nend_of_record\n')
    for name in ('core-jacoco.xml','app-jacoco.xml'):
        (reports/name).write_text('<report><package name="org/openvimar"/></report>')
    prepare.prepare(reports, candidate, sha)
    assert str(candidate/'apps/desktop-updater/src/vomar_updater') in (reports/'python-coverage.xml').read_text()
    with pytest.raises(ValueError, match='commit'):
        prepare.prepare(reports, candidate, 'b'*40)
    (reports/'core-jacoco.xml').unlink()
    with pytest.raises(ValueError, match='report'):
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
