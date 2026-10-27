"""Verify actual JUnit evidence for the synthetic Android CI journeys."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

EXPECTED_CLASSES = tuple('org.openvimar.updater.' + name for name in (
    'InitialInstallUiTest', 'InitialInstallAndroidAdapterTest', 'BleTrialUiTest',
    'AutomaticConnectionUiTest', 'AutomaticNetworkConnectionTest',
    'NativeFleetUiTest', 'SavedConnectionPersistenceTest', 'MqttCleartextPolicyTest',
))


def verify_results(directory: Path, expected_classes=EXPECTED_CLASSES):
    expected = set(expected_classes)
    if not expected:
        raise ValueError('Expected Android test classes are required')
    files = sorted(Path(directory).rglob('TEST-*.xml'))
    if not files:
        raise ValueError('Missing Android JUnit results')
    counts = {name: {'executed': 0, 'skipped': 0} for name in sorted(expected)}
    seen = set()
    for path in files:
        try:
            root = ET.parse(path).getroot()
        except ET.ParseError as error:
            raise ValueError('Malformed Android JUnit results') from error
        for element in root.iter():
            tag = element.tag.rsplit('}', 1)[-1]
            if tag == 'testsuite' and any(int(element.get(field, '0')) for field in ('failures', 'errors')):
                raise ValueError('Failed Android JUnit suite')
            if tag != 'testcase':
                continue
            name = element.get('classname', '')
            if name not in expected:
                raise ValueError('Unexpected Android test class: ' + name)
            key = (name, element.get('name', ''))
            if key in seen:
                raise ValueError('Duplicate Android JUnit testcase')
            seen.add(key)
            outcomes = {child.tag.rsplit('}', 1)[-1] for child in element}
            if outcomes & {'failure', 'error'}:
                raise ValueError('Failed Android test: ' + name)
            counts[name]['skipped' if 'skipped' in outcomes else 'executed'] += 1
    missing = sorted(name for name, count in counts.items() if count['executed'] == 0)
    if missing:
        raise ValueError('Android test classes did not execute: ' + ', '.join(missing))
    return {'schemaVersion': 1, 'executed': sum(c['executed'] for c in counts.values()),
            'skipped': sum(c['skipped'] for c in counts.values()), 'classes': counts}


def verify_coverage(directory: Path):
    files = sorted(directory.rglob('*.ec'))
    if not files or any(path.stat().st_size == 0 for path in files):
        raise ValueError('Missing or empty Android device coverage')
    return [{'file': str(path.relative_to(directory)), 'size': path.stat().st_size,
             'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--coverage-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = verify_results(args.results)
    result['deviceCoverage'] = verify_coverage(args.coverage_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(f"Verified {result['executed']} Android tests across {len(result['classes'])} classes")


if __name__ == '__main__':
    main()
