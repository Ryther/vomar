"""Exact-revision Sonar security gate, adapted from HAPatchY (Ryther, MIT)."""
from __future__ import annotations
import argparse
import base64
import json
import os
import re
import time
import urllib.parse
import urllib.request


class PendingAnalysis(ValueError):pass


def check(fetch,sha,project,branch='main'):
    if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('Full candidate SHA required')
    def revision():
        rows=fetch('/api/project_analyses/search',{'project':project,'branch':branch,'ps':1})['analyses']
        return rows[0].get('revision') if rows else None
    if revision()!=sha:raise PendingAnalysis('Sonar analysis is missing or stale')
    scope={'branch':branch}
    if fetch('/api/qualitygates/project_status',{'projectKey':project,**scope})['projectStatus']['status']!='OK':raise ValueError('Sonar quality status is not OK')
    for path,params in [('/api/issues/search',{'componentKeys':project,'impactSoftwareQualities':'SECURITY','resolved':'false','ps':1,**scope}),('/api/hotspots/search',{'projectKey':project,'status':'TO_REVIEW','ps':1,**scope})]:
        n=fetch(path,params)['paging']['total']
        if type(n) is not int or n!=0:raise ValueError('Open security issues or unreviewed hotspots')
    if revision()!=sha:raise ValueError('Sonar revision changed during security inspection')
    return True


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--sha',required=True);p.add_argument('--project',default='Ryther_vomar');p.add_argument('--wait-seconds',type=int,default=600);a=p.parse_args()
    token=os.environ.get('SONAR_TOKEN')
    if not token:raise SystemExit('SONAR_TOKEN is required in a protected trusted job')
    def fetch(path,params):
        request=urllib.request.Request('https://sonarcloud.io'+path+'?'+urllib.parse.urlencode(params),headers={'Authorization':'Basic '+base64.b64encode((token+':').encode()).decode()})
        with urllib.request.urlopen(request,timeout=20) as r:return json.load(r)
    deadline=time.monotonic()+a.wait_seconds
    while True:
        try:check(fetch,a.sha,a.project);break
        except PendingAnalysis:
            if time.monotonic()>=deadline:raise
            time.sleep(min(15,max(0,deadline-time.monotonic())))
    print('Exact candidate security gate passed')

if __name__=='__main__':main()
