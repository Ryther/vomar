import copy,json
from pathlib import Path
import pytest


def manifest():
    roles=('desktop-linux-x64','desktop-windows-x64','desktop-windows-setup','desktop-macos-arm64')
    return {'commit':'a'*40,'artifacts':[{'role':r,'sha256':str(i)*64} for i,r in enumerate(roles)]}


def test_platform_evidence_must_bind_every_native_artifact_and_real_checks():
    from tools.release.evidence import native_qualification,NATIVE_CHECKS
    m=manifest();report={'schemaVersion':1,'sourceCommit':m['commit'],'platforms':{}}
    platforms={'linux-x64':{'desktop-linux-x64'},'windows-x64':{'desktop-windows-x64','desktop-windows-setup'},'macos-arm64':{'desktop-macos-arm64'}}
    for platform,roles in platforms.items():report['platforms'][platform]={'artifacts':{a['role']:a['sha256'] for a in m['artifacts'] if a['role'] in roles},'checks':dict.fromkeys(NATIVE_CHECKS,True),'evidence':'operator-owned bench record'}
    assert native_qualification(m,report)
    for change in [*(lambda q,p=p:q['platforms'].pop(p) for p in platforms),lambda q:q['platforms'].update({'macos-x64':report['platforms']['macos-arm64']}),lambda q:q['platforms']['linux-x64']['checks'].update(bluetoothPermissionsAndUpdate=False),lambda q:q['platforms']['windows-x64']['artifacts'].update({'desktop-windows-setup':'f'*64}),lambda q:q.update(sourceCommit='b'*40)]:
        q=copy.deepcopy(report);change(q)
        with pytest.raises(ValueError):native_qualification(m,q)


def test_missing_or_stale_delivered_graph_review_cannot_pass():
    from tools.release.evidence import dependency_review
    graphs=('android-runtime','firmware-sdk','native-linux-x64','native-windows-x64','native-macos-arm64')
    m=manifest();inventories={g:(g+' synthetic inventory').encode() for g in graphs}
    from tools.release.manifest import digest
    q={'schemaVersion':1,'sourceCommit':m['commit'],'reviewedAt':'2026-10-25T12:00:00Z','artifacts':{a['role']:a['sha256'] for a in m['artifacts']},'graphs':{g:{'inventorySha256':digest(raw),'status':'no-unresolved-advisories','evidence':'Reviewed vendor/security advisories and supported audit results','dispositions':[]} for g,raw in inventories.items()}}
    assert dependency_review(m,q,inventories,now='2026-10-25T12:00:00Z')
    for change in [*(lambda q,g=g:q['graphs'].pop(g) for g in graphs),lambda q:q['graphs']['firmware-sdk'].update(status='pending'),lambda q:q.update(reviewedAt='2026-01-01T12:00:00Z'),lambda q:q['graphs']['native-linux-x64'].update(inventorySha256='f'*64)]:
        value=copy.deepcopy(q);change(value)
        with pytest.raises(ValueError):dependency_review(m,value,inventories,now='2026-10-25T12:00:00Z')
    for graph in graphs:
        missing={g:raw for g,raw in inventories.items() if g!=graph}
        with pytest.raises(ValueError,match='Missing actual delivered dependency inventory'):
            dependency_review(m,q,missing,now='2026-10-25T12:00:00Z')
    extra={**inventories,'native-macos-x64':b'unsupported Intel inventory'}
    with pytest.raises(ValueError,match='Missing actual delivered dependency inventory'):
        dependency_review(m,q,extra,now='2026-10-25T12:00:00Z')


def test_pr_and_release_require_their_respective_sonar_analysis():
    root=Path(__file__).resolve().parents[3];policy=json.loads((root/'.github/required-checks.json').read_text())
    assert 'sonar-pr / Sonar required' in policy['pullRequest']
    assert 'Sonar required' in policy['release']
    assert (set(policy['pullRequest'])-{'sonar-pr / Sonar required'}) <= set(policy['release'])


def test_publisher_rejects_missing_protected_reviews_before_crypto_or_publication(tmp_path,monkeypatch):
    from tools.release import publish
    monkeypatch.setattr(publish,'validate',lambda *args:None)
    with pytest.raises(ValueError,match='Protected native qualification'):
        publish.verify_candidate(manifest(),tmp_path,tmp_path/'unused',tmp_path/'unused')
