"""Validate and remap PR coverage without executing candidate source."""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET

REQUIRED = ('component-versions.json', 'python-coverage.xml', 'lcov.info',
            'core-jacoco.xml', 'app-jacoco.xml')


def _python_sources(tree, candidate):
    """Normalize Cobertura filenames to one checked candidate-relative root."""
    package = Path('apps/desktop-updater/src/vomar_updater')
    classes = tree.findall('.//class')
    if not classes:
        raise ValueError('Missing Python coverage sources')
    for entry in classes:
        name = entry.get('filename', '')
        path = Path(name)
        if not name or '..' in path.parts or '\\' in name:
            raise ValueError('Unexpected Python coverage source: '+name)
        if path.is_absolute():
            if path.is_relative_to(candidate):
                path = path.relative_to(candidate)
            else:
                # Absolute paths from the coverage producer's checkout are data.
                marker = '/'+package.as_posix()+'/'
                if marker not in name:
                    raise ValueError('Unexpected Python coverage source: '+name)
                path = package/name.split(marker, 1)[1]
        choices = [candidate/path, candidate/package.parent/path, candidate/package/path]
        matches = [choice for choice in choices
                   if choice.resolve().is_relative_to(candidate) and choice.is_file()]
        if len(matches) != 1:
            raise ValueError('Unresolvable or ambiguous Python coverage source: '+name)
        entry.set('filename', matches[0].relative_to(candidate).as_posix())
    root = tree.getroot()
    for old in root.findall('sources'):
        root.remove(old)
    sources = ET.Element('sources')
    ET.SubElement(sources, 'source').text = str(candidate)
    root.insert(0, sources)


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
            _python_sources(tree, candidate)
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
