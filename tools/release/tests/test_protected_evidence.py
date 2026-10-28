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


def accepted_release():
    from tools.release.manifest import REQUIRED_ROLES
    from tools.release.evidence import NATIVE_CHECKS,PLATFORMS
    from tools.firmware.ota_release import REQUIRED_CHECKS,SPLIT_REQUIRED_CHECKS
    m={'commit':'a'*40,'distributionVersion':'2.0.0','artifacts':[
        {'role':role,'sha256':f'{index:064x}'} for index,role in enumerate(sorted(REQUIRED_ROLES|{'source-sbom'}))]}
    q={'schemaVersion':1,'kind':'accepted-with-known-issues','sourceCommit':m['commit'],
       'distributionVersion':'2.0.0','acceptedAt':'2026-10-27T12:00:00Z','acceptedBy':'Repository owner',
       'statement':'I accept the listed experimental firmware issue and the explicitly unverified native checks.',
       'artifacts':{a['role']:a['sha256'] for a in m['artifacts']},
       'knownIssues':[{'id':'APS-105-5241','status':'unresolved','impact':'The Zigbee stack can assert and restart.',
                      'evidence':'Private exact-build retained CRC-verified assert and caller evidence.'}],
       'firmwarePurpose':'qualification-candidate',
       'firmwareChecks':dict.fromkeys((*REQUIRED_CHECKS,*SPLIT_REQUIRED_CHECKS,'commonFirstFlashVerified','stockRestoreVerified'),False),
       'nativeChecks':{platform:dict.fromkeys(NATIVE_CHECKS,False) for platform in PLATFORMS}}
    return m,q


def test_acceptance_binds_actual_payloads_without_claiming_physical_qualification():
    from tools.release.evidence import owner_acceptance
    m,q=accepted_release()
    assert owner_acceptance(m,q,now='2026-10-27T12:00:00Z')
    # The acceptance file is bound by the manifest, avoiding a self-hash cycle.
    m['artifacts'].append({'role':'release-acceptance','sha256':'f'*64})
    assert owner_acceptance(m,q,now='2026-10-27T12:00:00Z')


@pytest.mark.parametrize('damage',['source','version','payload','issue','date','future','firmware','native','owner','purpose'])
def test_acceptance_rejects_unbound_or_misleading_owner_claims(damage):
    from tools.release.evidence import owner_acceptance
    m,q=accepted_release()
    if damage=='source':q['sourceCommit']='b'*40
    elif damage=='version':q['distributionVersion']='1.0.0'
    elif damage=='payload':q['artifacts']['android-apk']='f'*64
    elif damage=='issue':q['knownIssues']=[]
    elif damage=='date':q['acceptedAt']='2026-01-01T00:00:00Z'
    elif damage=='future':q['acceptedAt']='2026-10-28T00:00:00Z'
    elif damage=='firmware':q['firmwareChecks']['stockRestoreVerified']=True
    elif damage=='native':q['nativeChecks']['windows-x64']['bluetoothPermissionsAndUpdate']=True
    elif damage=='owner':q['acceptedBy']=''
    else:q['firmwarePurpose']='qualified'
    with pytest.raises(ValueError):owner_acceptance(m,q,now='2026-10-27T12:00:00Z')


def test_experimental_release_mode_requires_manual_github_dispatch(monkeypatch):
    from tools.release.evidence import require_manual_acceptance
    monkeypatch.setenv('GITHUB_ACTIONS','true')
    for event in ('workflow_run','push','pull_request',''):
        monkeypatch.setenv('GITHUB_EVENT_NAME',event)
        with pytest.raises(ValueError,match='manual workflow_dispatch'):require_manual_acceptance()
    monkeypatch.setenv('GITHUB_EVENT_NAME','workflow_dispatch');require_manual_acceptance()
    monkeypatch.delenv('GITHUB_ACTIONS');monkeypatch.setenv('GITHUB_EVENT_NAME','push');require_manual_acceptance()


def physical_risk_review():
    from tools.release.evidence import DEPENDENCY_GRAPHS
    from tools.release.manifest import digest
    m,approval=accepted_release()
    issue={'id':'SA-2025-380','status':'unresolved',
           'impact':'Physical access and dedicated voltage fault equipment may defeat nRF52840 CC310 AES confidentiality; no physical fault resistance is claimed.',
           'evidence':'Nordic SA-2025-380-v1_0.pdf and exact-build CC3XX configuration, independently reviewed.'}
    approval['knownIssues'].append(issue)
    m['artifacts'].append({'role':'release-acceptance','sha256':'f'*64})
    inventories={g:(g+' synthetic inventory').encode() for g in DEPENDENCY_GRAPHS}
    q={'schemaVersion':1,'sourceCommit':m['commit'],'reviewedAt':'2026-10-27T12:00:00Z',
       'artifacts':{a['role']:a['sha256'] for a in m['artifacts']},
       'graphs':{g:{'inventorySha256':digest(raw),'status':'no-unresolved-advisories',
                    'evidence':'Synthetic independent review fixture only','dispositions':[]} for g,raw in inventories.items()}}
    q['graphs']['firmware-sdk'].update(status='reviewed-with-accepted-physical-risk',
        dispositions=[{**issue,'status':'accepted-physical-risk'}])
    return m,q,inventories,approval


def test_explicit_physical_risk_requires_the_bound_public_owner_acceptance(monkeypatch):
    from tools.release.evidence import dependency_review
    monkeypatch.setenv('GITHUB_ACTIONS','true');monkeypatch.setenv('GITHUB_EVENT_NAME','workflow_dispatch')
    m,q,inventories,approval=physical_risk_review()
    assert dependency_review(m,q,inventories,now='2026-10-27T12:00:00Z',
        accepted_with_known_issues=True,acceptance=approval)


@pytest.mark.parametrize('damage',['qualified','missing-owner','wrong-graph','wrong-id','missing-issue',
    'impact','evidence','stale-owner','owner-source','owner-payload','missing-public-asset',
    'stale-review','inventory','artifact','concealed-status','empty-disposition','software-advisory'])
def test_physical_risk_is_not_a_general_advisory_waiver(damage,monkeypatch):
    from tools.release.evidence import dependency_review
    monkeypatch.setenv('GITHUB_ACTIONS','true');monkeypatch.setenv('GITHUB_EVENT_NAME','workflow_dispatch')
    m,q,inventories,approval=physical_risk_review();accepted=True
    graph=q['graphs']['firmware-sdk'];disposition=graph['dispositions'][0]
    if damage=='qualified':accepted=False
    elif damage=='missing-owner':approval=None
    elif damage=='wrong-graph':
        q['graphs']['native-linux-x64'].update(status=graph['status'],dispositions=graph['dispositions'])
        graph.update(status='no-unresolved-advisories',dispositions=[])
    elif damage=='wrong-id':disposition['id']='SA-2026-540'
    elif damage=='missing-issue':approval['knownIssues'].pop()
    elif damage=='impact':approval['knownIssues'][-1]['impact']='A different unreviewed physical impact claim.'
    elif damage=='evidence':approval['knownIssues'][-1]['evidence']='Another unreviewed evidence reference.'
    elif damage=='stale-owner':approval['acceptedAt']='2026-01-01T00:00:00Z'
    elif damage=='owner-source':approval['sourceCommit']='b'*40
    elif damage=='owner-payload':approval['artifacts']['firmware-common']='f'*64
    elif damage=='missing-public-asset':m['artifacts'].pop();q['artifacts'].pop('release-acceptance')
    elif damage=='stale-review':q['reviewedAt']='2026-01-01T00:00:00Z'
    elif damage=='inventory':graph['inventorySha256']='f'*64
    elif damage=='artifact':q['artifacts']['android-apk']='f'*64
    elif damage=='concealed-status':graph['status']='no-unresolved-advisories'
    elif damage=='empty-disposition':graph['dispositions']=[]
    else:disposition['id']='CVE-2026-105924'
    with pytest.raises(ValueError):dependency_review(m,q,inventories,now='2026-10-27T12:00:00Z',
        accepted_with_known_issues=accepted,acceptance=approval)


def test_physical_risk_cannot_enable_automatic_publication(monkeypatch):
    from tools.release.evidence import dependency_review
    m,q,inventories,approval=physical_risk_review()
    monkeypatch.setenv('GITHUB_ACTIONS','true');monkeypatch.setenv('GITHUB_EVENT_NAME','push')
    with pytest.raises(ValueError,match='manual workflow_dispatch'):
        dependency_review(m,q,inventories,now='2026-10-27T12:00:00Z',
            accepted_with_known_issues=True,acceptance=approval)
