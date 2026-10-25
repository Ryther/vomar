"""Actual delivered dependency data and supported OSV advisory queries.

No advisory database covers every vendor binary. Protected review of exact
inventories remains mandatory for the complete distribution, including these
unsupported scopes; an empty automated result is never that attestation.
"""
import argparse,json,hashlib,importlib.metadata as metadata,subprocess,urllib.request
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
 return {'schemaVersion':1,'graph':'native-'+platform,'sourceCommit':commit(),'packages':packages,'nativeComponents':{'Qt':metadata.version('PySide6-Essentials'),'OpenOCD':'0.12.0-7'},'files':files,'artifacts':{p.name:digest(p.read_bytes()) for p in artifacts},'scope':'Exact frozen files, runtime package closure and bootloader; native system/vendor advisories require protected review'}

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
