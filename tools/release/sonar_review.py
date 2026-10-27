"""Manually reviewed false positives for exact main analysis; no scan exclusions."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import urllib.error
import urllib.parse
import urllib.request

PROJECT='Ryther_vomar'
BRANCH='main'
HOST='https://sonarcloud.io'
MAX_INPUT=65536
MAX_RECORDS=10
REPORT=Path('_test/sonar-review/report.json')
INPUT=Path('_test/sonar-review/review.json')
# Only the concrete boundaries independently reviewed for this release.
SCOPE={
 ('pythonsecurity:S8707','Ryther_vomar:apps/desktop-updater/src/vomar_updater/adapters/filesystem.py'):'apps/desktop-updater/src/vomar_updater/adapters/filesystem.py',
 ('pythonbugs:S2259','Ryther_vomar:apps/desktop-updater/src/vomar_updater/adapters/mqtt.py'):'apps/desktop-updater/src/vomar_updater/adapters/mqtt.py',
 ('pythonsecurity:S8707','Ryther_vomar:apps/desktop-updater/src/vomar_updater/core/packages.py'):'apps/desktop-updater/src/vomar_updater/core/packages.py',
 ('pythonsecurity:S8707','Ryther_vomar:apps/desktop-updater/src/vomar_updater/core/storage.py'):'apps/desktop-updater/src/vomar_updater/core/storage.py',
 ('pythonsecurity:S8707','Ryther_vomar:apps/desktop-updater/src/vomar_updater/service.py'):'apps/desktop-updater/src/vomar_updater/service.py',
 ('pythonsecurity:S2083','Ryther_vomar:tools/firmware/build_ota_migration.py'):'tools/firmware/build_ota_migration.py',
 ('pythonsecurity:S8705','Ryther_vomar:tools/firmware/validate_recovery.py'):'tools/firmware/validate_recovery.py',
}


class ReviewError(ValueError):
    """A named, non-secret review failure safe to retain in the checkpoint."""


def _sha(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{40}',value):raise ReviewError('Full lowercase candidate SHA required')
    return value


def _pairs(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ReviewError('Duplicate JSON field')
        result[key]=value
    return result


def parse_review(raw,sha):
    _sha(sha)
    if not isinstance(raw,str) or len(raw.encode('utf-8'))>MAX_INPUT:raise ReviewError('Review JSON exceeds its bound')
    try:value=json.loads(raw,object_pairs_hook=_pairs)
    except (json.JSONDecodeError,UnicodeError):raise ReviewError('Malformed review JSON') from None
    if type(value) is not dict or set(value)!={'schemaVersion','sourceCommit','issues'}:raise ReviewError('Wrong review document fields')
    if type(value['schemaVersion']) is not int or value['schemaVersion']!=1 or value['sourceCommit']!=sha:raise ReviewError('Review belongs to another exact candidate')
    records=value['issues']
    if type(records) is not list or not 1<=len(records)<=MAX_RECORDS:raise ReviewError('Review requires one to ten explicit issues')
    seen=set()
    for record in records:
        if type(record) is not dict or set(record)!={'issueKey','rule','component','issueHash','fileSha256','disposition','rationale'}:raise ReviewError('Wrong issue review fields')
        if not all(isinstance(v,str) for v in record.values()):raise ReviewError('Issue review values must be strings')
        key=record['issueKey']
        if not re.fullmatch('[A-Za-z0-9_-]{8,128}',key) or key in seen:raise ReviewError('Invalid or duplicate issue key')
        seen.add(key)
        if (record['rule'],record['component']) not in SCOPE:raise ReviewError('Issue is outside the reviewed rule/component scope')
        if record['disposition']!='falsepositive':raise ReviewError('Only the falsepositive transition is supported')
        if not re.fullmatch('[0-9a-f]{32}',record['issueHash']) or not re.fullmatch('[0-9a-f]{64}',record['fileSha256']):raise ReviewError('Exact issue and source hashes required')
        rationale=record['rationale']
        if not 40<=len(rationale)<=4000 or any(ord(c)<32 and c not in '\n\t' for c in rationale):raise ReviewError('Bounded substantive review rationale required')
    return value


def _ordinary(path):
    path=Path(path).absolute()
    for part in (path,*path.parents):
        if part.is_symlink():raise ReviewError('Symlink path forbidden')
    return path


def _save(path,value):
    path=_ordinary(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.next')
    # A trusted fixed report path, independent of candidate/review content.
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
        if os.name!='nt':
            directory=os.open(path.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
    finally:temporary.unlink(missing_ok=True)


def _git(candidate,*args):
    try:return subprocess.check_output(['git','-C',str(candidate),*args],stderr=subprocess.DEVNULL)
    except (OSError,subprocess.CalledProcessError):raise ReviewError('Candidate Git evidence unavailable') from None


def _source(candidate,sha,record):
    relative=SCOPE[(record['rule'],record['component'])]
    path=_ordinary(candidate/relative)
    try:
        if not stat.S_ISREG(path.stat().st_mode):raise ReviewError('Candidate source is not an ordinary file')
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:raise ReviewError('Candidate source is missing or unreadable') from None
    tree=_git(candidate,'ls-tree','-z',sha,'--',relative).split(b'\0')
    expected_suffix=b'\t'+relative.encode()
    if len(tree)!=2 or not tree[0].endswith(expected_suffix) or tree[0].split(b' ',1)[0] not in (b'100644',b'100755'):raise ReviewError('Candidate source Git mode/path mismatch')
    committed=hashlib.sha256(_git(candidate,'cat-file','blob',sha+':'+relative)).hexdigest()
    if actual!=record['fileSha256'] or actual!=committed:raise ReviewError('Candidate source is stale or differs from the reviewed Git blob')


def _revision(api,sha):
    response=api.get('/api/project_analyses/search',{'project':PROJECT,'branch':BRANCH,'ps':1})
    rows=response.get('analyses')
    if type(rows) is not list or not rows or rows[0].get('revision')!=sha:raise ReviewError('Latest main analysis is missing or stale')
    return {'revision':sha,'analysisKey':rows[0].get('key')}


def _falsepositive(issue):
    return issue.get('resolution')=='FALSE-POSITIVE' and issue.get('status') in ('RESOLVED','CLOSED')


def _issue(api,record):
    response=api.get('/api/issues/search',{'componentKeys':PROJECT,'branch':BRANCH,'issues':record['issueKey'],'ps':2,'additionalFields':'transitions'})
    rows=response.get('issues');total=response.get('paging',{}).get('total')
    if type(total) is not int or total!=1 or type(rows) is not list or len(rows)!=1:raise ReviewError('Reviewed issue has no unique live main match')
    issue=rows[0]
    for name,expected in [('key',record['issueKey']),('rule',record['rule']),('component',record['component']),('hash',record['issueHash']),('project',PROJECT)]:
        if issue.get(name)!=expected:raise ReviewError('Live issue identity or fingerprint differs from review')
    if not _falsepositive(issue):
        if issue.get('status') not in ('OPEN','CONFIRMED','REOPENED') or issue.get('resolution') is not None:raise ReviewError('Live issue is not an unresolved reviewable finding')
        if 'falsepositive' not in issue.get('transitions',[]):raise ReviewError('Falsepositive transition unavailable; Administer Issues permission is required')
    return {k:issue.get(k) for k in ('key','rule','component','hash','project','status','resolution')}


def _initial(sha,apply):
    return {'schemaVersion':1,'project':PROJECT,'branch':BRANCH,'sourceCommit':sha if isinstance(sha,str) and re.fullmatch('[0-9a-f]{40}',sha) else None,'mode':'apply' if apply else 'dry-run','status':'started','mayHaveApplied':False,'records':[]}


def execute(candidate,sha,raw,api,output,*,apply=False):
    """Preflight the entire batch, then checkpoint each exact permitted transition."""
    if Path(output).absolute().is_relative_to(Path(candidate).absolute()):raise ReviewError('Report cannot modify the candidate checkout')
    report=_initial(sha,apply);_save(output,report)
    try:
        if type(apply) is not bool:raise ReviewError('Apply must be a literal boolean')
        document=parse_review(raw,sha);candidate=_ordinary(candidate)
        if _git(candidate,'rev-parse','--verify','HEAD').decode().strip()!=sha:raise ReviewError('Candidate checkout HEAD differs from requested SHA')
        report['inputSha256']=hashlib.sha256(raw.encode()).hexdigest()
        report['records']=[{'review':r,'state':'pending-preflight'} for r in document['issues']]
        report['status']='preflighting';_save(output,report)
        report['analysis']=_revision(api,sha)
        for row in report['records']:
            _source(candidate,sha,row['review']);row['before']=_issue(api,row['review']);row['state']='already-falsepositive' if _falsepositive(row['before']) else 'preflight-verified';_save(output,report)
        _revision(api,sha)
        if not apply:
            report['status']='dry-run-complete';_save(output,report);return report
        report['status']='applying';_save(output,report)
        for row in report['records']:
            _source(candidate,sha,row['review']);live=_issue(api,row['review']);_revision(api,sha)
            if _falsepositive(live):row['state']='already-falsepositive';_save(output,report);continue
            row['state']='apply-intent';report['mayHaveApplied']=True;_save(output,report)
            api.transition(row['review']['issueKey'])
            row['after']=_issue(api,row['review'])
            if not _falsepositive(row['after']):raise ReviewError('Falsepositive transition did not pass live readback')
            row['state']='confirmed-falsepositive';_save(output,report)
            _revision(api,sha)
        report['status']='applied';_save(output,report);return report
    except BaseException as error:
        report['status']='failed';report['error']=str(error) if isinstance(error,ReviewError) else type(error).__name__;_save(output,report)
        if isinstance(error,ReviewError):raise
        raise ReviewError('Review failed; inspect the retained checkpoint') from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        return None


class SonarApi:
    """Fixed Sonar endpoint; token appears only in the authorization header."""
    def __init__(self,token):
        if not isinstance(token,str) or not token:raise ReviewError('Protected SONAR_TOKEN is required')
        self._authorization='Basic '+base64.b64encode((token+':').encode()).decode()
        self._opener=urllib.request.build_opener(_NoRedirect())
    def _request(self,path,params,post=False):
        permitted={('/api/project_analyses/search',False),('/api/issues/search',False),('/api/issues/do_transition',True)}
        if (path,post) not in permitted:raise ReviewError('Unsupported Sonar operation')
        encoded=urllib.parse.urlencode(params).encode();url=HOST+path
        request=urllib.request.Request(url if post else url+'?'+encoded.decode(),data=encoded if post else None,headers={'Authorization':self._authorization,'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'})
        try:
            with self._opener.open(request,timeout=20) as response:
                raw=response.read(2*1024*1024+1)
            if len(raw)>2*1024*1024:raise ReviewError('Sonar response exceeds its bound')
            result=json.loads(raw)
            if type(result) is not dict:raise ReviewError('Malformed Sonar response')
            return result
        except urllib.error.HTTPError as error:raise ReviewError('Sonar HTTP request failed: '+str(error.code)) from None
        except (OSError,ValueError):raise ReviewError('Sonar request or JSON response failed') from None
    def get(self,path,params):return self._request(path,params)
    def transition(self,key):return self._request('/api/issues/do_transition',{'issue':key,'transition':'falsepositive'},True)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sha',required=True);parser.add_argument('--apply',choices=('true','false'),default='false');parser.add_argument('--stage-input',action='store_true')
    args=parser.parse_args(argv);report=_initial(args.sha,args.apply=='true');_save(REPORT,report)
    try:
        if args.stage_input:
            document=parse_review(os.environ.get('SONAR_REVIEW_JSON',''),args.sha)
            _save(INPUT,document);report['status']='input-validated';_save(REPORT,report);return 0
        if (os.environ.get('GITHUB_REPOSITORY')!='Ryther/vomar' or os.environ.get('GITHUB_REF')!='refs/heads/main' or os.environ.get('GITHUB_EVENT_NAME')!='workflow_dispatch'):raise ReviewError('Review requires manual dispatch from protected repository main')
        workflow_sha=_sha(os.environ.get('TRUSTED_WORKFLOW_SHA'))
        if INPUT.is_symlink() or INPUT.stat().st_size>MAX_INPUT:raise ReviewError('Staged review input is invalid')
        raw=INPUT.read_text(encoding='utf-8')
        api=SonarApi(os.environ.get('SONAR_TOKEN'))
        result=execute(Path('candidate'),args.sha,raw,api,REPORT,apply=args.apply=='true')
        result['trustedWorkflowSha']=workflow_sha;result['helperSha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();_save(REPORT,result)
        print('Reviewed main issues: '+result['status']);return 0
    except BaseException as error:
        if REPORT.exists():report=json.loads(REPORT.read_text())
        report['status']='failed';report['error']=str(error) if isinstance(error,ReviewError) else type(error).__name__;_save(REPORT,report)
        print('Sonar review failed; inspect the retained report');return 1


if __name__=='__main__':raise SystemExit(main())
