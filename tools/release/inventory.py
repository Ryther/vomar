"""Actual delivered dependency data and supported OSV advisory queries.

No advisory database covers every vendor binary. Protected review of exact
inventories remains mandatory for the complete distribution, including these
unsupported scopes; an empty automated result is never that attestation.
"""
import argparse,json,hashlib,importlib.metadata as metadata,re,subprocess,urllib.request
from pathlib import Path
from packaging.requirements import Requirement
from .manifest import loads,digest
from .evidence import DEPENDENCY_GRAPHS
ROOT=Path(__file__).resolve().parents[2]

def commit():return subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip()

def firmware(output):
 import yaml
 projects=yaml.safe_load((ROOT/'firmware/west-lock.yml').read_text())['manifest']['projects']
 records=[{'name':r['name'],'commit':r['revision'],'url':r['url']} for r in projects]
 raw={'schemaVersion':1,'graph':'firmware-sdk','sourceCommit':commit(),'projects':records,'scope':'All active pinned public SDK repositories, including Nordic binary components; advisory coverage requires protected vendor review'}
 Path(output).write_text(json.dumps(raw,indent=2)+'\n');return raw

def _dpkg_output(arguments):
 try:result=subprocess.run(['dpkg-query',*arguments],capture_output=True,text=True,timeout=10)
 except (OSError,subprocess.TimeoutExpired):return None
 return result.stdout if result.returncode==0 else None

def _owned_system_files(name,output):
 records=[]
 for line in output.splitlines():
  owner,separator,path=line.partition(': ');source=Path(path)
  if not separator or not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9][a-z0-9-]*)?',owner) or not source.is_absolute() or source.name!=name:return None
  records.append((owner,source))
 return sorted(set(records))

def _matching_system_source(source,bundle,expected):
 try:
  resolved=source.resolve(strict=True)
  if source.is_symlink() or not source.is_file() or resolved.is_relative_to(bundle):return None
  with source.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
  return resolved if sha==expected else None
 except (OSError,RuntimeError):return None

def _system_component(bundle,entry):
 row={'path':entry['path'],'sha256':entry['sha256'],'status':'unresolved'}
 output=_dpkg_output(['--search','*/'+Path(entry['path']).name])
 if output is None:return {**row,'reason':'dpkg ownership query unavailable'}
 candidates=_owned_system_files(Path(entry['path']).name,output)
 if candidates is None:return {**row,'reason':'Unrecognized or diverted dpkg ownership metadata'}
 matches={}
 for owner,source in candidates:
  resolved=_matching_system_source(source,bundle,entry['sha256'])
  if resolved is not None:matches.setdefault((owner,resolved),source)
 if len(matches)!=1:return {**row,'reason':'Ambiguous hash-matching dpkg-owned sources' if matches else 'No hash-matching dpkg-owned system file'}
 (owner,resolved),source=next(iter(matches.items()))
 output=_dpkg_output(['--show','--showformat=${binary:Package}\t${Version}\t${db:Status-Status}\n',owner])
 fields=output.rstrip('\n').split('\t') if output is not None else []
 if len(fields)!=3 or fields[0]!=owner or not re.fullmatch(r'[0-9][A-Za-z0-9.+:~_-]*',fields[1]) or fields[2]!='installed':return {**row,'reason':'Installed dpkg package identity/version unavailable or inconsistent'}
 if _matching_system_source(source,bundle,entry['sha256'])!=resolved:return {**row,'reason':'System source changed during provenance lookup'}
 return {**row,'status':'matched','packageManager':'dpkg','package':owner,'version':fields[1],
         'sourcePath':str(resolved),'sourceSha256':entry['sha256'],'ownedPath':str(source)}

def native(bundle,platform,artifacts):
 queue=['vomar-updater','PySide6-Essentials','shiboken6','PyInstaller'];seen=set();packages=[]
 while queue:
  name=queue.pop(0);d=metadata.distribution(name);canonical=d.metadata['Name'].lower().replace('_','-')
  if canonical in seen:continue
  seen.add(canonical);packages.append({'ecosystem':'PyPI','name':d.metadata['Name'],'version':d.version})
  for dependency in d.requires or []:
   r=Requirement(dependency)
   if r.marker is None or any(r.marker.evaluate({'extra':extra}) for extra in ('','gui')):queue.append(r.name)
 files=[];bundle=Path(bundle).resolve()
 for p in sorted(bundle.rglob('*')):
  if p.is_file():
   if not p.resolve().is_relative_to(bundle):raise ValueError('Runtime inventory cannot follow external links')
   with p.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
   files.append({'path':p.relative_to(bundle).as_posix(),'size':p.stat().st_size,'sha256':sha})
 raw={'schemaVersion':1,'graph':'native-'+platform,'sourceCommit':commit(),'packages':packages,'nativeComponents':{'Qt':metadata.version('PySide6-Essentials'),'OpenOCD':'0.12.0-7'},'files':files,'artifacts':{p.name:digest(p.read_bytes()) for p in artifacts},'scope':'Exact frozen files, runtime package closure and bootloader; native system/vendor advisories require protected review'}
 if platform.startswith('linux-'):raw['systemComponents']=[_system_component(bundle,row) for row in files if Path(row['path']).name in {'libssl.so.3','libcrypto.so.3'}]
 return raw

def audit(paths,output):
 results=[];queries=[];identities=[]
 for p in paths:
  raw=loads(Path(p).read_bytes())
  for package in raw.get('packages',[]):queries.append({'package':{'ecosystem':package['ecosystem'],'name':package['name']},'version':package['version']});identities.append(package)
  for project in raw.get('projects',[]):queries.append({'commit':project['commit']});identities.append(project)
 if not queries:raise ValueError('No supported delivered packages to audit')
 for start in range(0,len(queries),100):
  request=urllib.request.Request('https://api.osv.dev/v1/querybatch',data=json.dumps({'queries':queries[start:start+100]}).encode(),headers={'Content-Type':'application/json'})
  with urllib.request.urlopen(request,timeout=90) as response:batch=loads(response.read())
  if type(batch.get('results')) is not list or len(batch['results'])!=len(queries[start:start+100]):raise ValueError('Incomplete OSV query response')
  for identity,row in zip(identities[start:start+100],batch['results']):results.append({'package':identity,'advisories':row.get('vulns',[])})
 Path(output).write_text(json.dumps({'scope':'Supported OSV packages/commits only; protected graph review remains required','results':results},indent=2)+'\n')
 if any(r['advisories'] for r in results):raise ValueError('Advisories require a fix or a protected reviewed disposition')
 return results

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['firmware','audit']);p.add_argument('--output',type=Path,required=True);p.add_argument('--input',action='append',type=Path,default=[]);a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
 if a.action=='firmware':firmware(a.output)
 else:audit(a.input,a.output)
