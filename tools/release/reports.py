"""Validate exact-run coverage and analysis inputs before any credentialed scan."""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET

REQUIRED=('python-coverage.xml','lcov.info','core-jacoco.xml','app-jacoco.xml','c-coverage.xml','compile_commands.json','component-versions.json')

def check(root,sha):
    root=Path(root)
    for name in REQUIRED:
        p=root/name
        if p.is_symlink() or not p.is_file() or not 1<=p.stat().st_size<=100*1024*1024:raise ValueError('Missing or invalid analysis report: '+name)
    identity=json.loads((root/'component-versions.json').read_text())
    if identity.get('commit')!=sha:raise ValueError('Analysis reports do not match the exact candidate')
    for name,tag in [('python-coverage.xml','coverage'),('core-jacoco.xml','report'),('app-jacoco.xml','report'),('c-coverage.xml','coverage')]:
        node=ET.parse(root/name).getroot()
        if node.tag!=tag or not list(node):raise ValueError('Empty/invalid coverage report: '+name)
    if 'SF:' not in (root/'lcov.info').read_text():raise ValueError('Empty JavaScript coverage')
    rows=json.loads((root/'compile_commands.json').read_text())
    if type(rows) is not list or not rows:raise ValueError('Missing actual target C compilation database')
    return True
