"""An emulator command is successful only when every requested journey ran."""
from pathlib import Path
import json
import sys
import xml.etree.ElementTree as ET

import pytest

from tools.release import android_ui


def report(directory: Path, classes, *, failure=False, skipped=False, namespace=False):
    directory.mkdir(parents=True, exist_ok=True)
    prefix = '{urn:synthetic:junit}' if namespace else ''
    root = ET.Element(prefix + 'testsuite', tests=str(len(classes)), failures=str(int(failure)), errors='0')
    for index, name in enumerate(classes):
        case = ET.SubElement(root, prefix + 'testcase', classname=name, name=f'test_{index}')
        if failure and index == 0:
            ET.SubElement(case, prefix + 'failure')
        if skipped:
            ET.SubElement(case, prefix + 'skipped')
    ET.ElementTree(root).write(directory / 'TEST-synthetic.xml')


@pytest.mark.parametrize('namespace', [False, True])
def test_reports_exact_executed_journeys_and_counts(tmp_path, namespace):
    expected = ('synthetic.First', 'synthetic.Second')
    report(tmp_path, expected, namespace=namespace)
    result = android_ui.verify_results(tmp_path, expected)
    assert result['executed'] == 2
    assert result['classes'] == {name: {'executed': 1, 'skipped': 0} for name in expected}


def test_first_class_only_cannot_pass_as_a_complete_ui_run(tmp_path):
    report(tmp_path, ('synthetic.First',))
    with pytest.raises(ValueError, match='synthetic.Second'):
        android_ui.verify_results(tmp_path, ('synthetic.First', 'synthetic.Second'))


@pytest.mark.parametrize('options', [{'failure': True}, {'skipped': True}])
def test_failed_or_entirely_skipped_class_never_counts_as_executed(tmp_path, options):
    report(tmp_path, ('synthetic.First',), **options)
    with pytest.raises(ValueError):
        android_ui.verify_results(tmp_path, ('synthetic.First',))


def test_unexpected_class_and_duplicate_results_are_rejected(tmp_path):
    report(tmp_path, ('synthetic.First', 'synthetic.Other'))
    with pytest.raises(ValueError, match='Unexpected'):
        android_ui.verify_results(tmp_path, ('synthetic.First',))
    report(tmp_path, ('synthetic.First',))
    (tmp_path / 'TEST-duplicate.xml').write_bytes((tmp_path / 'TEST-synthetic.xml').read_bytes())
    with pytest.raises(ValueError, match='Duplicate'):
        android_ui.verify_results(tmp_path, ('synthetic.First',))


def test_missing_or_malformed_results_fail(tmp_path):
    with pytest.raises(ValueError, match='JUnit'):
        android_ui.verify_results(tmp_path, ('synthetic.First',))
    (tmp_path / 'TEST-malformed.xml').write_text('<testsuite>')
    with pytest.raises(ValueError, match='JUnit'):
        android_ui.verify_results(tmp_path, ('synthetic.First',))


def test_cli_writes_evidence_only_after_all_expected_classes_execute(tmp_path, monkeypatch, capsys):
    results = tmp_path / 'results'
    output = tmp_path / 'verified.json'
    report(results, android_ui.EXPECTED_CLASSES)
    monkeypatch.setattr(sys, 'argv', ['android_ui', '--results', str(results), '--output', str(output)])
    android_ui.main()
    assert json.loads(output.read_text())['executed'] == len(android_ui.EXPECTED_CLASSES)
    assert 'Verified 7 Android tests across 7 classes' in capsys.readouterr().out
    rejected = tmp_path / 'incomplete.json'
    report(results, android_ui.EXPECTED_CLASSES[:1])
    monkeypatch.setattr(sys, 'argv', ['android_ui', '--results', str(results), '--output', str(rejected)])
    with pytest.raises(ValueError, match='did not execute'):
        android_ui.main()
    assert not rejected.exists()
