"""PR scans must fail on missing evidence and retain complete findings."""
import importlib
import itertools
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import xml.etree.ElementTree as ET
import urllib.parse

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
    assert prepared.findall('./sources/source')==[]
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


@pytest.mark.parametrize('host,selector', [('https://sonarcloud.io','projectKey'), ('http://127.0.0.1:9000','project')])
def test_http_hotspot_scope_uses_the_backend_selector_without_changing_pr_or_pagination(monkeypatch,host,selector):
    report=importlib.import_module('tools.release.sonar_report')
    requests=[]
    def urlopen(request,timeout):
        assert timeout==30
        requests.append(request)
        return io.BytesIO(b'{"hotspots":[],"paging":{"total":0}}')
    monkeypatch.setattr(report.urllib.request,'urlopen',urlopen)
    params={'project':'synthetic-project','pullRequest':'8','p':2,'ps':25}
    assert report._http_fetch(host,'synthetic-token')('/api/hotspots/search',params)['hotspots']==[]
    parsed=urllib.parse.urlsplit(requests[0].full_url)
    assert urllib.parse.parse_qs(parsed.query)=={selector:['synthetic-project'],'pullRequest':['8'],'p':['2'],'ps':['25']}
    assert requests[0].get_header('Authorization')=='Bearer synthetic-token'
    assert params=={'project':'synthetic-project','pullRequest':'8','p':2,'ps':25}


def cloud_workflow():
    root=Path(__file__).resolve().parents[3]
    return yaml.safe_load((root/'.github/workflows/sonar-pr.yml').read_text())['jobs']['cloud']


def test_cloud_export_requires_verified_protected_code_and_keeps_current_base_settings():
    cloud=cloud_workflow()
    assert cloud['env']=={'SONAR_COMPAT_BASE_SHA':'6476b264542fa757e38aef66d541fc36c51feb27',
                          'SONAR_COMPAT_EXPORTER_SHA':'3447f132f7f16e9d97bf8b8f1dd2b2aefd02cdb5'}
    steps=cloud['steps']
    checkout=next(s for s in steps if s.get('with',{}).get('path')=='trusted-export')
    assert checkout['with']['ref']=='${{ steps.select-exporter.outputs.sha }}'
    assert checkout['with']['persist-credentials'] is False
    export=next(s for s in steps if s.get('name')=='Export complete PR findings')
    assert export['if']=="always() && steps.verify-exporter.outcome == 'success'"
    assert 'PYTHONPATH="$GITHUB_WORKSPACE/trusted-export" python -P -m tools.release.sonar_report' in export['run']
    assert 'test "$SCAN_OUTCOME" = success' in export['run']
    for step in steps:
        if step.get('id') in ('select-exporter','verify-exporter'):
            assert 'SONAR_TOKEN' not in step.get('env',{})
    scan=next(s for s in steps if s.get('id')=='scan')
    assert 'trusted/.github/sonar-pr.properties' in scan['run']
    prepare=next(s for s in steps if s.get('name')=='Validate exact candidate reports without credentials')
    assert 'PYTHONPATH=trusted python' in prepare['run']


@pytest.mark.parametrize('case',['known-base','future-base','wrong-base-checkout','non-ancestor','wrong-exporter-checkout','changed-selection'])
def test_exporter_selection_and_verification_fail_closed_on_real_git_history(tmp_path,case):
    trusted=tmp_path/'trusted';trusted.mkdir()
    def git(*args):
        return subprocess.check_output(['git','-C',str(trusted),*args],text=True,stderr=subprocess.DEVNULL).strip()
    git('init','-q');git('config','user.name','Synthetic exporter test');git('config','user.email','fixture@example.invalid')
    commits=[]
    for name in ('ancestor','known-base','future-base'):
        git('commit','--allow-empty','-qm','test: '+name);commits.append(git('rev-parse','HEAD'))
    ancestor,known,future=commits
    git('checkout','--orphan','unrelated');git('commit','--allow-empty','-qm','test: unrelated history')
    unrelated=git('rev-parse','HEAD')
    base=future if case=='future-base' else known
    git('checkout','--detach',future if case=='wrong-base-checkout' else base)
    output=tmp_path/'github-output'
    env={**os.environ,'PR_BASE_SHA':base,'SONAR_COMPAT_BASE_SHA':known,
         'SONAR_COMPAT_EXPORTER_SHA':unrelated if case=='non-ancestor' else ancestor,
         'GITHUB_OUTPUT':str(output)}
    cloud=cloud_workflow();select=next(s for s in cloud['steps'] if s.get('id')=='select-exporter')['run']
    result=subprocess.run(['bash','-e','-c',select],cwd=tmp_path,env=env,capture_output=True,text=True)
    if case in ('wrong-base-checkout','non-ancestor'):
        assert result.returncode!=0 and not output.exists()
        return
    assert result.returncode==0,result.stderr
    selected=output.read_text().strip().removeprefix('sha=')
    assert selected==(future if case=='future-base' else ancestor)
    subprocess.run(['git','clone','--quiet','--shared',str(trusted),str(tmp_path/'trusted-export')],check=True)
    checkout=future if case=='wrong-exporter-checkout' else selected
    subprocess.run(['git','-C',str(tmp_path/'trusted-export'),'checkout','--quiet','--detach',checkout],check=True)
    env['EXPORTER_SHA']=future if case=='changed-selection' else selected
    verify=next(s for s in cloud['steps'] if s.get('id')=='verify-exporter')['run']
    result=subprocess.run(['bash','-e','-c',verify],cwd=tmp_path,env=env,capture_output=True,text=True)
    receipt=tmp_path/'sonar-report/exporter-source-sha.txt'
    if case in ('wrong-exporter-checkout','changed-selection'):
        assert result.returncode!=0 and not receipt.exists()
    else:
        assert result.returncode==0,result.stderr
        assert receipt.read_text().strip()==selected


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
