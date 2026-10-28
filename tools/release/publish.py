"""Exact-candidate, complete-draft GitHub publisher (HAPatchY invariants, MIT).

Dry-run is the default. Published assets are immutable; differing bytes never
trigger deletion or replacement. This module never executes candidate source.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request
import urllib.error
import zipfile
from .manifest import loads,validate,digest
from .security_gate import check as security_check
from .codeql_gate import check_remote as codeql_check
from tools.firmware.package_common_android_update_v3 import validate_common_v3_bundle
from tools.firmware.ota_release import REQUIRED_CHECKS,SPLIT_REQUIRED_CHECKS
from cryptography.hazmat.primitives import serialization

CHECKS=set(loads((Path(__file__).resolve().parents[2]/'.github/required-checks.json').read_bytes())['release'])
ACCEPTED_RELEASE_NOTICE='Experimental firmware: APS-105-5241 remains unresolved; firmware and native physical qualification checks are unverified.'


def require_accepted_notice(release):
    if not isinstance(release.get('body'),str) or ACCEPTED_RELEASE_NOTICE not in release['body']:
        raise ValueError('Accepted release draft must disclose its experimental firmware and unverified qualification')


def select_draft(releases,tag,sha):
    matches=[r for r in releases if r.get('tag_name')==tag]
    if len(matches)!=1:raise ValueError('Missing or ambiguous release draft')
    r=matches[0]
    if r.get('draft') is not True or r.get('prerelease') is True or r.get('target_commitish')!=sha:raise ValueError('Draft target is not the immutable candidate SHA')
    return r


def reconcile_assets(remote,release,files):
    existing=remote.assets(release);names=[a['name'] for a in existing]
    if len(set(names))!=len(names):raise ValueError('Ambiguous duplicate remote assets')
    if set(names)-files.keys():raise ValueError('Draft contains unreviewed extra assets')
    for name,path in sorted(files.items()):
        raw=path.read_bytes();found=[a for a in existing if a['name']==name]
        if found:
            if found[0]['size']!=len(raw) or remote.download(found[0])!=raw:raise ValueError('Existing draft asset differs; create a new candidate')
        else:remote.upload(release,name,raw)
    actual=remote.assets(release)
    if {a['name'] for a in actual}!=set(files):raise ValueError('Draft upload is incomplete')
    for asset in actual:
        if digest(remote.download(asset))!=digest(files[asset['name']].read_bytes()):raise ValueError('Remote uploaded asset readback mismatch')


def qualification(package,report,source_sha):
    q=loads(report)
    if not re.fullmatch('[0-9a-f]{40}',source_sha) or q.get('sourceCommit')!=source_sha:raise ValueError('Physical qualification belongs to another source revision')
    flags=(*REQUIRED_CHECKS,*SPLIT_REQUIRED_CHECKS,'commonFirstFlashVerified','stockRestoreVerified')
    if any(q.get(k) is not True for k in flags):raise ValueError('Thirteen literal physical qualification checks are required')
    if digest(report)!=package['qualificationSha256'] or q.get('schemaVersion')!=3 or q.get('layoutVersion')!=2 or q.get('model')!='VIMAR30805' or q.get('loaderContracts')!=package['loaderContracts']:raise ValueError('Qualification is not bound to the exact signed release')
    return q


def verify_candidate(manifest,directory,qualification_path,public_key,android_tools=None,*,native_evidence=None,dependency_evidence=None,accepted_with_known_issues=False,acceptance_path=None):
    validate(manifest,directory)
    from .evidence import native_qualification,dependency_review,owner_acceptance,require_manual_acceptance,DEPENDENCY_GRAPHS
    assets={a['role']:a for a in manifest['artifacts']}
    accepted_approval=None
    if accepted_with_known_issues:
        require_manual_acceptance()
        expected_files={a['filename'] for a in manifest['artifacts']}|{'release-manifest.json','SHA256SUMS'}
        if len(expected_files)!=14 or {p.name for p in directory.iterdir()}!=expected_files or any(p.is_symlink() or not p.is_file() for p in directory.iterdir()):
            raise ValueError('Accepted distribution requires exactly fourteen reviewed regular files')
        if not acceptance_path or 'release-acceptance' not in assets:raise ValueError('Protected owner acceptance and its published asset are required')
        accepted_raw=Path(acceptance_path).read_bytes();accepted_approval=loads(accepted_raw);owner_acceptance(manifest,accepted_approval)
        approval=assets['release-acceptance']
        if approval['filename']!=f'vomar-release-acceptance-{manifest["distributionVersion"]}.json' or (directory/approval['filename']).read_bytes()!=accepted_raw:
            raise ValueError('Published owner acceptance differs from protected approval')
        if not dependency_evidence:raise ValueError('Protected delivered dependency review remains required')
    else:
        if 'release-acceptance' in assets:raise ValueError('Experimental release requires explicit accepted-with-known-issues mode')
        if not native_evidence or not dependency_evidence:raise ValueError('Protected native qualification and delivered dependency review are required')
        native_qualification(manifest,loads(Path(native_evidence).read_bytes()))
    if 'source-sbom' not in assets:raise ValueError('Delivered dependency inventories are missing')
    from tools.firmware.bounded_zip import read_member
    with zipfile.ZipFile(directory/assets['source-sbom']['filename']) as archive:
        names=[g+'.json' for g in DEPENDENCY_GRAPHS]
        if len(archive.infolist())!=len(names) or set(archive.namelist())!=set(names):raise ValueError('Missing/ambiguous delivered inventory graph')
        inventories={g:read_member(archive,archive.getinfo(g+'.json'),8*1024*1024) for g in DEPENDENCY_GRAPHS}
    for graph,raw in inventories.items():
        data=loads(raw)
        if data.get('graph')!=graph or data.get('sourceCommit')!=manifest['commit']:raise ValueError('Inventory source identity mismatch')
        if graph.startswith('native-'):
            from .evidence import PLATFORMS
            expected={a['filename']:a['sha256'] for a in manifest['artifacts'] if a['role'] in PLATFORMS[graph[7:]]}
            if data.get('artifacts')!=expected or not data.get('files') or not data.get('packages'):raise ValueError('Native inventory does not describe the delivered bundle')
    dependency_review(manifest,loads(Path(dependency_evidence).read_bytes()),inventories,
        accepted_with_known_issues=accepted_with_known_issues,acceptance=accepted_approval)
    raw=(directory/assets['firmware-common']['filename']).read_bytes()
    key=serialization.load_pem_public_key(Path(public_key).read_bytes())
    if accepted_with_known_issues:
        from tools.firmware.package_common_android_update_v3 import _validate_common_v3_bundle
        package=_validate_common_v3_bundle(raw,key,expected_purpose='qualification-candidate')
    else:package=validate_common_v3_bundle(raw,key)
    if package['main']['version']!=manifest['components']['firmware'] or assets['firmware-common']['componentVersion']!=package['main']['version']:raise ValueError('Firmware version identity mismatch')
    if not accepted_with_known_issues:
        if qualification_path is None:raise ValueError('Protected physical qualification is required')
        q=qualification(package,Path(qualification_path).read_bytes(),manifest['commit'])
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        expected={n:package[n]['fileSha256'] for n in ('main','recovery','migration','stockRestore','stockBootstrap') if n in package};expected['loader']=digest(z.read('loader.bin'))
        ota=package.get('zigbeeOta')
        if not ota:raise ValueError('Distribution requires its signed Zigbee carrier')
        expected['zigbeeOta']=ota['fileSha256']
        if not accepted_with_known_issues and q.get('components')!=expected:raise ValueError('Physical evidence component set mismatch')
        carrier=(directory/assets['zigbee-ota']['filename']).read_bytes()
        if len(carrier)!=ota['size'] or digest(carrier)!=ota['fileSha256'] or carrier!=z.read('main.ota'):raise ValueError('Distribution OTA bytes differ from signed firmware')
    if 'desktop-windows-setup' not in assets:raise ValueError('Per-user Windows installer is missing')
    if manifest['distributionVersion']=='0.0.0':raise ValueError('Bootstrap version cannot be published as a distribution')
    if not android_tools:raise ValueError('Pinned Android build-tools are required for independent APK verification')
    from .assemble import audit_apk
    import subprocess
    apk=directory/assets['android-apk']['filename'];audit_apk(apk,android_tools,manifest['components']['android'],assets['android-apk']['androidVersionCode'])
    report=subprocess.run([str(Path(android_tools)/'apksigner'),'verify','--verbose','--print-certs',str(apk)],capture_output=True,text=True,check=True).stdout
    certificates=re.findall(r'Signer #[0-9]+ certificate SHA-256 digest: ([0-9a-fA-F]+)',report)
    pinned=loads((Path(__file__).with_name('signing-identities.json')).read_bytes())
    if certificates!=[pinned['androidCertificateSha256']]:raise ValueError('APK signer continuity mismatch')
    suffix='-qualification-candidate' if accepted_with_known_issues else ''
    if assets['firmware-common']['filename']!=f'vomar-firmware-{manifest["distributionVersion"]}{suffix}.zip':raise ValueError('Noncanonical firmware name')
    if accepted_with_known_issues and assets['zigbee-ota']['filename']!=f'vomar-firmware-{manifest["distributionVersion"]}-qualification-candidate.ota':raise ValueError('Noncanonical experimental OTA name')
    return package


class GitHub:
    def __init__(self,repo,token,*,checks_token=None):
        if not re.fullmatch('[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('Invalid GitHub repository')
        self.repo=repo;self.token=token;self.checks_token=checks_token
    def request(self,path,method='GET',body=None,*,raw=False,upload=False):
        host='uploads.github.com' if upload else 'api.github.com'
        url='https://'+host+'/repos/'+self.repo+'/'+path
        headers={'Accept':'application/octet-stream' if raw else 'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'Vomar-release'}
        if self.token:headers['Authorization']='Bearer '+self.token
        if body is not None:
            headers['Content-Type']='application/octet-stream' if upload else 'application/json'
            if not upload:body=json.dumps(body).encode()
        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,req,fp,code,msg,h,newurl):
                p=urllib.parse.urlsplit(newurl)
                if p.scheme!='https' or p.hostname not in ('release-assets.githubusercontent.com','objects.githubusercontent.com','github.com','api.github.com'):raise ValueError('Unexpected GitHub redirect')
                result=super().redirect_request(req,fp,code,msg,h,newurl)
                if p.hostname!='api.github.com':result.remove_header('Authorization')
                return result
        req=urllib.request.Request(url,data=body,method=method,headers=headers)
        with urllib.request.build_opener(Redirect()).open(req,timeout=120) as r:
            data=r.read()
            return data if raw else loads(data) if data else None
    def releases(self):return self.request('releases?per_page=100')
    def assets(self,release):return self.request(f'releases/{release}/assets?per_page=100')
    def download(self,asset):return self.request(f'releases/assets/{asset["id"]}',raw=True)
    def upload(self,release,name,raw):return self.request(f'releases/{release}/assets?name='+urllib.parse.quote(name,safe=''),'POST',raw,upload=True)
    def checks(self,sha):return GitHub(self.repo,self.checks_token).request(f'commits/{sha}/check-runs?per_page=100&filter=latest')
    def code_scanning(self,path):
        if not self.checks_token:raise ValueError('Code scanning read credential required')
        if not path.startswith('code-scanning/'):raise ValueError('Expected CodeQL API path')
        return GitHub(self.repo,self.checks_token).request(path)
    def tag_sha(self,tag):
        value=self.request('git/ref/tags/'+urllib.parse.quote(tag,safe=''))['object']
        if value['type']=='tag':value=self.request('git/tags/'+value['sha'])['object']
        if value['type']!='commit':raise ValueError('Tag must resolve to a commit')
        return value['sha']
    def pin_draft(self,tag,sha):
        matches=[r for r in self.releases() if r.get('tag_name')==tag]
        if len(matches)!=1 or matches[0].get('draft') is not True:raise ValueError('Expected one unpublished draft')
        draft=matches[0];target=draft.get('target_commitish')
        if target not in (sha,'main'):raise ValueError('Draft is pinned to another candidate')
        if target=='main':
            if self.request('commits/main')['sha']!=sha:raise ValueError('Mutable draft target advanced; no candidate retargeting')
            draft=self.request(f'releases/{draft["id"]}','PATCH',{'target_commitish':sha})
        try:existing=self.tag_sha(tag)
        except urllib.error.HTTPError as error:
            if error.code!=404:raise
            self.request('git/refs','POST',{'ref':'refs/tags/'+tag,'sha':sha});existing=self.tag_sha(tag)
        if existing!=sha:raise ValueError('Existing tag differs from exact candidate')
        return draft
    def publish(self,release):return self.request(f'releases/{release}','PATCH',{'draft':False,'make_latest':'true'})


def verify_checks(value,sha):
    rows=value.get('check_runs')
    if type(rows) is not list or value.get('total_count',0)>100:raise ValueError('Missing/oversized check result set')
    success={r['name'] for r in rows if r.get('head_sha')==sha and r.get('status')=='completed' and r.get('conclusion')=='success' and r.get('app',{}).get('slug')=='github-actions'}
    if CHECKS-success:raise ValueError('Missing exact-candidate required checks: '+', '.join(sorted(CHECKS-success)))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',default='Ryther/vomar');p.add_argument('--directory',type=Path,required=True);p.add_argument('--qualification',type=Path);p.add_argument('--public-key',type=Path,required=True);p.add_argument('--android-tools',type=Path);p.add_argument('--native-qualification',type=Path);p.add_argument('--dependency-review',type=Path,required=True);p.add_argument('--publish',action='store_true');p.add_argument('--accepted-with-known-issues',action='store_true');p.add_argument('--acceptance',type=Path);a=p.parse_args()
    if a.accepted_with_known_issues:
        from .evidence import require_manual_acceptance
        require_manual_acceptance()
        if not a.acceptance:p.error('--accepted-with-known-issues requires --acceptance')
        if a.qualification or a.native_qualification:p.error('Experimental acceptance cannot use qualified firmware/native reports')
    elif a.acceptance or not a.qualification or not a.native_qualification:
        p.error('Qualified publication requires --qualification and --native-qualification; --acceptance requires explicit experimental mode')
    manifest=loads((a.directory/'release-manifest.json').read_bytes());verify_options={'native_evidence':a.native_qualification,'dependency_evidence':a.dependency_review,'accepted_with_known_issues':a.accepted_with_known_issues,'acceptance_path':a.acceptance}
    verify_candidate(manifest,a.directory,a.qualification,a.public_key,a.android_tools,**verify_options)
    paths={x['filename']:a.directory/x['filename'] for x in manifest['artifacts']};paths['release-manifest.json']=a.directory/'release-manifest.json';paths['SHA256SUMS']=a.directory/'SHA256SUMS'
    expected=''.join(digest(path.read_bytes())+'  '+name+'\n' for name,path in sorted(paths.items()) if name!='SHA256SUMS')
    if paths['SHA256SUMS'].read_text()!=expected:raise ValueError('Checksums do not describe the complete immutable asset set')
    if not a.publish:print('Dry run passed locally; no GitHub state changed. Exact remote checks and security are rechecked during publication.');return
    token=os.environ.get('GH_TOKEN')
    if not token:raise ValueError('Protected publication credential required')
    remote=GitHub(a.repo,token,checks_token=os.environ.get('GH_CHECKS_TOKEN'));verify_checks(remote.checks(manifest['commit']),manifest['commit'])
    codeql_check(remote.code_scanning,manifest['commit'])
    sonar_token=os.environ.get('SONAR_TOKEN')
    if not sonar_token:raise ValueError('Exact Sonar security verification credential required')
    def fetch(path,params):
        req=urllib.request.Request('https://sonarcloud.io'+path+'?'+urllib.parse.urlencode(params),headers={'Authorization':'Bearer '+sonar_token})
        with urllib.request.urlopen(req,timeout=30) as r:return loads(r.read())
    security_check(fetch,manifest['commit'],'Ryther_vomar');draft=remote.pin_draft(manifest['tag'],manifest['commit']);select_draft([draft],manifest['tag'],manifest['commit'])
    if a.accepted_with_known_issues:require_accepted_notice(draft)
    reconcile_assets(remote,draft['id'],paths)
    # Recheck mutable external gates immediately before the single publish mutation.
    current_draft=select_draft(remote.releases(),manifest['tag'],manifest['commit'])
    if a.accepted_with_known_issues:require_accepted_notice(current_draft)
    verify_checks(remote.checks(manifest['commit']),manifest['commit'])
    if remote.tag_sha(manifest['tag'])!=manifest['commit']:raise ValueError('Tag changed during upload')
    security_check(fetch,manifest['commit'],'Ryther_vomar')
    if a.accepted_with_known_issues:verify_candidate(manifest,a.directory,a.qualification,a.public_key,a.android_tools,**verify_options)
    codeql_check(remote.code_scanning,manifest['commit'])
    remote.publish(draft['id'])

if __name__=='__main__':main()
