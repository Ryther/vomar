"""Validate public workflow trust boundaries before actionlint's syntax pass."""
from pathlib import Path
import re,json
import yaml
ROOT=Path(__file__).resolve().parents[2]
REQUIRED=set(json.loads((ROOT/'.github/required-checks.json').read_text())['release'])

def check():
    names=set()
    for p in (ROOT/'.github/workflows').glob('*.yml'):
        raw=p.read_text();doc=yaml.safe_load(raw)
        if 'pull_request_target' in raw:raise ValueError('No privileged execution of PR source')
        for value in re.findall(r'uses:\s*([^\s}]+)',raw):
            if not value.startswith('./') and not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}',value):raise ValueError('Unpinned Action: '+value)
        for j in doc.get('jobs',{}).values():
            if isinstance(j,dict) and 'name' in j:names.add(j['name'])
        if 'secrets: inherit' in raw:raise ValueError('Reusable validation cannot inherit credentials')
    if REQUIRED-names:raise ValueError('Missing stable checks: '+', '.join(sorted(REQUIRED-names)))
    return names
if __name__=='__main__':check();print('Workflow trust boundaries checked')
