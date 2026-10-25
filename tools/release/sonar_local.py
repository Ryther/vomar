"""Disposable credential-free local Sonar lane; unsupported languages fail closed."""
import argparse,base64,json,secrets,subprocess,time,urllib.request,urllib.parse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--candidate',type=Path,required=True);p.add_argument('--reports',type=Path,required=True);a=p.parse_args()
 images=json.loads((ROOT/'.github/sonar-community.json').read_text());name='vomar-sonar-'+secrets.token_hex(6);token=None
 def call(path,data=None):
  headers={'Authorization':'Basic '+base64.b64encode(b'admin:admin').decode()}
  req=urllib.request.Request('http://127.0.0.1:9000'+path,data=urllib.parse.urlencode(data).encode() if data is not None else None,headers=headers)
  with urllib.request.urlopen(req,timeout=10) as r:return json.load(r)
 try:
  subprocess.run(['docker','run','--detach','--name',name,'--publish','127.0.0.1:9000:9000','-e','SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true',images['library/sonarqube']],check=True,capture_output=True)
  deadline=time.monotonic()+180
  while True:
   try:
    if call('/api/system/status').get('status')=='UP':break
   except OSError:pass
   if time.monotonic()>deadline:raise TimeoutError('Disposable Sonar did not become ready')
   time.sleep(2)
  call('/api/projects/create',{'project':'vomar-local','name':'Vomar local analysis'})
  token=call('/api/user_tokens/generate',{'name':'ephemeral-local'})['token']
  import os
  env={**os.environ,'SONAR_TOKEN':token}
  # Only ephemeral local credentials, read-only mounts and protected settings.
  result=subprocess.run(['docker','run','--rm','--network','host','-e','SONAR_TOKEN','-v',str(a.candidate.resolve())+':/usr/src:ro','-v',str(a.reports.resolve())+':/reports:ro','-v',str(ROOT/'sonar-project.properties')+':/settings.properties:ro',images['sonarsource/sonar-scanner-cli'],'-Dsonar.host.url=http://127.0.0.1:9000','-Dsonar.working.directory=/tmp/scannerwork','-Dproject.settings=/settings.properties','-Dsonar.projectKey=vomar-local','-Dsonar.python.coverage.reportPaths=/reports/python-coverage.xml','-Dsonar.javascript.lcov.reportPaths=/reports/lcov.info','-Dsonar.coverage.jacoco.xmlReportPaths=/reports/core-jacoco.xml,/reports/app-jacoco.xml'],env=env)
  report={'profile':'disposable-community','scannerExit':result.returncode,'reusableCloudCredential':False,'unsupportedRequiredAnalyzers':['c-cpp'],'complete':False}
  (a.reports/'local-sonar-capabilities.json').write_text(json.dumps(report,indent=2)+'\n')
  raise SystemExit('Community C/C++ analysis is unavailable. Partial local analysis cannot satisfy the full required release gate; use supported protected main analysis.')
 finally:subprocess.run(['docker','rm','--force',name],check=False,capture_output=True)
if __name__=='__main__':main()
