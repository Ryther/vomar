"""Validate and remap PR coverage without executing candidate source."""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET

REQUIRED = ('component-versions.json', 'python-coverage.xml', 'lcov.info',
            'core-jacoco.xml', 'app-jacoco.xml')


def prepare(reports, candidate, sha):
    reports = Path(reports).resolve()
    candidate = Path(candidate).resolve()
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Full candidate commit required')
    for name in REQUIRED:
        path = reports/name
        if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= 100*1024*1024:
            raise ValueError('Missing or invalid PR analysis report: '+name)
    if json.loads((reports/'component-versions.json').read_text()).get('commit') != sha:
        raise ValueError('PR coverage belongs to another commit')
    for name, tag in (('python-coverage.xml','coverage'), ('core-jacoco.xml','report'), ('app-jacoco.xml','report')):
        tree = ET.parse(reports/name)
        if tree.getroot().tag != tag or not list(tree.getroot()):
            raise ValueError('Empty or invalid PR coverage report: '+name)
        if name == 'python-coverage.xml':
            for source in tree.findall('./sources/source'):
                # Coverage's --source=vomar_updater records the package root.
                source.text = str(candidate/'apps/desktop-updater/src/vomar_updater')
            tree.write(reports/name, encoding='utf-8', xml_declaration=True)
    lcov = reports/'lcov.info'
    lines = lcov.read_text().splitlines()
    if not any(line.startswith('SF:') for line in lines):
        raise ValueError('Missing JavaScript coverage sources')
    for index, line in enumerate(lines):
        if line.startswith('SF:'):
            path = line[3:]
            marker = 'integrations/zigbee2mqtt/'
            if marker not in path or '..' in Path(path).parts:
                raise ValueError('Unexpected JavaScript coverage source')
            lines[index] = 'SF:'+str(candidate/path[path.index(marker):])
    lcov.write_text('\n'.join(lines)+'\n')
