"""Protected operator evidence, separate from host checks and firmware flags."""
from datetime import datetime,timezone,timedelta
import re
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

def dependency_review(manifest,report,inventories,*,now=None):
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
  if r['inventorySha256']!=digest(raw) or r['status']!='no-unresolved-advisories':raise ValueError('Graph advisory scope is missing or unresolved: '+graph)
  note(r['evidence'])
  if type(r['dispositions']) is not list:raise ValueError('Explicit advisory dispositions required')
  for d in r['dispositions']:
   exact(d,{'id','status','evidence'})
   if not isinstance(d['id'],str) or not d['id'] or d['status'] not in ('fixed','not-affected'):raise ValueError('Unresolved advisory disposition')
   note(d['evidence'])
 return True
