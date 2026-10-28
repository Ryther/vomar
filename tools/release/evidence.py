"""Protected operator evidence, separate from host checks and firmware flags."""
from datetime import datetime,timezone,timedelta
import os,re
from .manifest import exact,digest

PLATFORMS={
 'linux-x64':{'desktop-linux-x64'},
 'windows-x64':{'desktop-windows-x64','desktop-windows-setup'},
 'macos-arm64':{'desktop-macos-arm64'},
}
NATIVE_CHECKS={'filesystemTransactions','bluetoothPermissionsAndUpdate','dkDriverInstallRepairStart','stopAndRestartRecovery'}
DEPENDENCY_GRAPHS={'android-runtime','firmware-sdk',*('native-'+p for p in PLATFORMS)}

def source(report,manifest):
 if report.get('schemaVersion')!=1 or type(report['schemaVersion']) is not int or not re.fullmatch('[0-9a-f]{40}',manifest['commit']) or report.get('sourceCommit')!=manifest['commit']:raise ValueError('Evidence belongs to another exact candidate')

def note(value):
 if not isinstance(value,str) or not 8<=len(value.strip())<=4096:raise ValueError('Independent evidence reference is required')

def native_qualification(manifest,report):
 exact(report,{'schemaVersion','sourceCommit','platforms'});source(report,manifest)
 exact(report['platforms'],set(PLATFORMS));assets={a['role']:a['sha256'] for a in manifest['artifacts']}
 for platform,roles in PLATFORMS.items():
  r=report['platforms'][platform];exact(r,{'artifacts','checks','evidence'});exact(r['checks'],NATIVE_CHECKS)
  if any(v is not True for v in r['checks'].values()) or r['artifacts']!={role:assets.get(role) for role in roles} or any(role not in assets for role in roles):raise ValueError('Missing or mismatched native physical qualification: '+platform)
  note(r['evidence'])
 return True

def dependency_review(manifest,report,inventories,*,now=None,accepted_with_known_issues=False,acceptance=None):
 exact(report,{'schemaVersion','sourceCommit','reviewedAt','artifacts','graphs'});source(report,manifest)
 if report['artifacts']!={a['role']:a['sha256'] for a in manifest['artifacts']}:raise ValueError('Dependency review does not match every delivered artifact')
 try:
  reviewed=datetime.fromisoformat(report['reviewedAt'].replace('Z','+00:00'));current=datetime.fromisoformat(now.replace('Z','+00:00')) if now else datetime.now(timezone.utc)
  if reviewed.tzinfo is None or current-reviewed>timedelta(days=14) or reviewed-current>timedelta(minutes=5):raise ValueError('Dependency advisory review is stale or future-dated')
 except (TypeError,AttributeError):raise ValueError('Dated advisory review required') from None
 exact(report['graphs'],DEPENDENCY_GRAPHS)
 if set(inventories)!=DEPENDENCY_GRAPHS:raise ValueError('Missing actual delivered dependency inventory')
 for graph,raw in inventories.items():
  r=report['graphs'][graph];exact(r,{'inventorySha256','status','evidence','dispositions'})
  physical=r['status']=='reviewed-with-accepted-physical-risk'
  if r['inventorySha256']!=digest(raw) or r['status'] not in ('no-unresolved-advisories','reviewed-with-accepted-physical-risk'):raise ValueError('Graph advisory scope is missing or unresolved: '+graph)
  if physical:
   if graph!='firmware-sdk' or not accepted_with_known_issues or not isinstance(acceptance,dict) or sum(a['role']=='release-acceptance' for a in manifest['artifacts'])!=1:
    raise ValueError('Physical risk requires the explicit accepted firmware release and public owner acceptance')
   require_manual_acceptance();owner_acceptance(manifest,acceptance,now=now)
  note(r['evidence'])
  if type(r['dispositions']) is not list:raise ValueError('Explicit advisory dispositions required')
  physical_seen=False
  for d in r['dispositions']:
   if physical and d.get('status')=='accepted-physical-risk':
    exact(d,{'id','status','impact','evidence'})
    if d['id']!='SA-2025-380' or physical_seen:raise ValueError('Only the reviewed SA-2025-380 hardware risk can be accepted')
    note(d['impact']);note(d['evidence'])
    issues=[issue for issue in acceptance['knownIssues'] if issue['id']==d['id']]
    if len(issues)!=1 or any(issues[0][field]!=d[field] for field in ('impact','evidence')):
     raise ValueError('Physical risk assessment must match the public unresolved owner-accepted issue')
    physical_seen=True;continue
   exact(d,{'id','status','evidence'})
   if not isinstance(d['id'],str) or not d['id'] or d['status'] not in ('fixed','not-affected'):raise ValueError('Unresolved advisory disposition')
   note(d['evidence'])
  if physical and not physical_seen:raise ValueError('Accepted physical risk graph must disclose SA-2025-380')
 return True


def owner_acceptance(manifest,report,*,now=None):
 """Bind a deliberate experimental release decision, never physical proof."""
 from .manifest import REQUIRED_ROLES
 from tools.firmware.ota_release import REQUIRED_CHECKS,SPLIT_REQUIRED_CHECKS
 exact(report,{'schemaVersion','kind','sourceCommit','distributionVersion','acceptedAt','acceptedBy',
               'statement','artifacts','knownIssues','firmwarePurpose','firmwareChecks','nativeChecks'})
 source(report,manifest)
 if report['kind']!='accepted-with-known-issues' or report['distributionVersion']!=manifest['distributionVersion']:
  raise ValueError('Acceptance must name the exact experimental distribution')
 if not isinstance(report['acceptedBy'],str) or not 1<=len(report['acceptedBy'].strip())<=200:raise ValueError('Owner identity is required')
 note(report['statement'])
 try:
  accepted=datetime.fromisoformat(report['acceptedAt'].replace('Z','+00:00'))
  current=datetime.fromisoformat(now.replace('Z','+00:00')) if now else datetime.now(timezone.utc)
  if accepted.tzinfo is None or current-accepted>timedelta(days=14) or accepted-current>timedelta(minutes=5):
   raise ValueError('Owner acceptance is stale or future-dated')
 except (TypeError,AttributeError):raise ValueError('Dated owner acceptance required') from None
 payloads={a['role']:a['sha256'] for a in manifest['artifacts'] if a['role']!='release-acceptance'}
 if payloads.keys()!=REQUIRED_ROLES|{'source-sbom'} or report['artifacts']!=payloads:
  raise ValueError('Owner acceptance does not match all eleven frozen payload hashes')
 flags=set(REQUIRED_CHECKS)|set(SPLIT_REQUIRED_CHECKS)|{'commonFirstFlashVerified','stockRestoreVerified'}
 exact(report['firmwareChecks'],flags)
 if report['firmwarePurpose']!='qualification-candidate' or any(v is not False for v in report['firmwareChecks'].values()):
  raise ValueError('Experimental acceptance cannot claim firmware qualification')
 exact(report['nativeChecks'],set(PLATFORMS))
 for checks in report['nativeChecks'].values():
  exact(checks,NATIVE_CHECKS)
  if any(v is not False for v in checks.values()):raise ValueError('Experimental acceptance must disclose unverified native checks')
 issues=report['knownIssues']
 if type(issues) is not list or not 1<=len(issues)<=32:raise ValueError('Known unresolved firmware issue must be disclosed')
 ids=set()
 for issue in issues:
  exact(issue,{'id','status','impact','evidence'})
  if not isinstance(issue['id'],str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,79}',issue['id']) or issue['id'] in ids or issue['status']!='unresolved':
   raise ValueError('Explicit unique unresolved issue required')
  ids.add(issue['id']);note(issue['impact']);note(issue['evidence'])
 if 'APS-105-5241' not in ids:raise ValueError('The known APS-105-5241 assert must be disclosed')
 return True


def require_manual_acceptance():
 if os.environ.get('GITHUB_ACTIONS')=='true' and os.environ.get('GITHUB_EVENT_NAME')!='workflow_dispatch':
  raise ValueError('Experimental release requires an explicit manual workflow_dispatch')
