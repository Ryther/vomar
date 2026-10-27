"""Validate and remap PR coverage without executing candidate source."""
from pathlib import Path, PurePosixPath
import json
import re
import xml.etree.ElementTree as ET

REQUIRED = ('component-versions.json', 'python-coverage.xml', 'lcov.info',
            'core-jacoco.xml', 'app-jacoco.xml')


def normalize_python_coverage(report, repository):
    """Encode measured repository paths in the credential-free producer job.

    Sonar's Cobertura importer uses its project base when sources is empty.
    Leaving no source children also survives the existing trusted PR remapper.
    Coverage counts and branch data remain exactly as measured by coverage.py.
    """
    report=Path(report)
    repository=Path(repository).resolve()
    tree=ET.parse(report)
    sources=tree.findall('./sources/source')
    classes=tree.findall('./packages/package/classes/class')
    if tree.getroot().tag!='coverage' or len(sources)!=1 or sources[0].text!=str(repository) or not classes:
        raise ValueError('Python coverage must measure the exact repository root')
    for item in classes:
        filename=item.get('filename','')
        path=PurePosixPath(filename)
        if not filename or path.is_absolute() or '..' in path.parts or '\\' in filename or ':' in filename or filename!=path.as_posix():
            raise ValueError('Python coverage filename must be repository-relative')
        source=(repository/filename).resolve()
        if not source.is_relative_to(repository) or not source.is_file() or source.suffix!='.py':
            raise ValueError('Python coverage filename must identify repository source')
    for source in sources:tree.find('./sources').remove(source)
    tree.write(report,encoding='utf-8',xml_declaration=True)


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


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='Normalize credential-free repository Python coverage')
    parser.add_argument('--python-coverage',type=Path,required=True)
    parser.add_argument('--repository',type=Path,required=True)
    args=parser.parse_args()
    normalize_python_coverage(args.python_coverage,args.repository)
