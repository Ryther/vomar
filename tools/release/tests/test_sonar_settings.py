"""The credentialed scan must load the protected file from its actual base."""
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT=Path(__file__).resolve().parents[3]


@pytest.mark.parametrize('candidate_kind',['missing','untrusted-file','untrusted-symlink'])
def test_actual_workflow_installs_trusted_scanner_settings_without_following_candidate_links(tmp_path,candidate_kind):
    steps=yaml.safe_load((ROOT/'.github/workflows/sonar.yml').read_text())['jobs']['analyze']['steps']
    install=next((step for step in steps if step.get('name')=='Install protected scanner settings'),None)
    assert install is not None, 'Main scan must install the protected settings in its selected project root'
    trusted=tmp_path/'trusted';trusted.mkdir();candidate=tmp_path/'candidate';candidate.mkdir()
    config=b'sonar.projectKey=synthetic-project\nsonar.organization=synthetic-org\nsonar.sources=firmware,apps\n'
    (trusted/'sonar-project.properties').write_bytes(config)
    external=tmp_path/'external.properties';external.write_text('unchanged external file\n')
    dest=candidate/'sonar-project.properties'
    if candidate_kind=='untrusted-file':dest.write_text('sonar.projectKey=untrusted-project\nsonar.host.url=https://untrusted.invalid\n')
    elif candidate_kind=='untrusted-symlink':dest.symlink_to(external)
    subprocess.run(['bash','-e','-c',install['run']],cwd=tmp_path,check=True,capture_output=True,text=True)
    scan=next(step for step in steps if step.get('name')=='Scan source using only protected settings')
    assert scan['with']['projectBaseDir']=='candidate'
    assert '-Dproject.settings=' not in scan['with']['args'], 'The scan must use the installed protected project-root settings'
    actual=tmp_path/scan['with']['projectBaseDir']/'sonar-project.properties'
    assert actual.is_file() and not actual.is_symlink() and actual.read_bytes()==config
    assert external.read_text()=='unchanged external file\n'
    assert scan['env']['SONAR_TOKEN']=='${{ secrets.SONAR_TOKEN }}'
    assert '-Dsonar.cfamily.compile-commands=' in scan['with']['args']
