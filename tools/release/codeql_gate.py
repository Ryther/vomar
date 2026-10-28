"""Block high/critical CodeQL findings, not merely failed analysis jobs."""
from __future__ import annotations

import argparse
import math
from pathlib import Path
import re
import urllib.parse

from .manifest import loads

CATEGORIES = {'/language:' + language for language in (
    'python', 'javascript-typescript', 'actions', 'java-kotlin', 'c-cpp')}


def check_sarif(directory):
    files = sorted(Path(directory).rglob('*.sarif'))
    if not files:
        raise ValueError('Missing CodeQL SARIF report')
    count = 0
    blocked = 0
    for path in files:
        report = loads(path.read_bytes())
        if report.get('version') != '2.1.0' or not report.get('runs'):
            raise ValueError('Incomplete CodeQL SARIF report')
        for run in report['runs']:
            driver = run['tool']['driver']
            if driver.get('name') != 'CodeQL' or type(run.get('results')) is not list:
                raise ValueError('Expected complete CodeQL SARIF results')
            for result in run['results']:
                reference = result.get('rule', {})
                component = reference.get('toolComponent', {})
                rules = (run['tool']['extensions'][component['index']] if 'index' in component else driver).get('rules', [])
                by_id = {rule['id']: rule for rule in rules}
                rule_id = result.get('ruleId', reference.get('id'))
                if rule_id not in by_id:
                    raise ValueError('CodeQL result has no matching rule')
                rule = by_id[rule_id]
                level = result.get('level', rule.get('defaultConfiguration', {}).get('level', 'warning'))
                severity = rule.get('properties', {}).get('security-severity')
                score = 0.0 if severity is None else float(severity)
                if not math.isfinite(score) or not 0 <= score <= 10:
                    raise ValueError('Invalid CodeQL security severity')
                count += 1
                blocked += int(score >= 7 or level == 'error')
    if blocked:
        raise ValueError(f'CodeQL blocking findings: {blocked} high/critical security or error results')
    return count


def _pages(fetch, endpoint):
    for page in range(1, 11):
        rows = fetch(endpoint + '&per_page=100&page=' + str(page))
        if type(rows) is not list or len(rows) > 100:
            raise ValueError('Invalid CodeQL API result page')
        yield from rows
        if len(rows) < 100:
            return
    raise ValueError('CodeQL API result exceeds bounded pagination')


def check_remote(fetch, sha):
    if not re.fullmatch('[0-9a-f]{40}', sha):
        raise ValueError('Full candidate SHA required')
    ref = urllib.parse.quote('refs/heads/main', safe='')
    # The analyses API returns newest first. Never substitute an older success
    # when the most recent analysis of a required category is stale or failed.
    latest = {}
    for row in _pages(fetch, 'code-scanning/analyses?ref=' + ref + '&tool_name=CodeQL'):
        if not isinstance(row, dict):
            raise ValueError('Invalid CodeQL analysis')
        category = row.get('category')
        if row.get('tool', {}).get('name') == 'CodeQL' and category in CATEGORIES:
            latest.setdefault(category, row)
            if latest.keys() == CATEGORIES:
                break
    if latest.keys() != CATEGORIES:
        raise ValueError('Missing required exact-candidate CodeQL analysis categories')
    if any(row.get('ref') != 'refs/heads/main' or row.get('commit_sha') != sha or
           row.get('error') != '' for row in latest.values()):
        raise ValueError('CodeQL analysis is stale, incomplete or failed')
    blocked = 0
    for row in _pages(fetch, 'code-scanning/alerts?ref=' + ref + '&tool_name=CodeQL&state=open'):
        if not isinstance(row, dict) or row.get('state') != 'open' or row.get('tool', {}).get('name') != 'CodeQL':
            raise ValueError('Invalid open CodeQL alert')
        rule = row.get('rule', {})
        security = rule.get('security_severity_level')
        if security not in (None, 'low', 'medium', 'high', 'critical') or rule.get('severity') not in ('note', 'warning', 'error'):
            raise ValueError('Invalid CodeQL alert severity')
        blocked += int(security in ('high', 'critical') or rule['severity'] == 'error')
    if blocked:
        raise ValueError(f'CodeQL blocking findings: {blocked} open high/critical security or error alerts')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sarif', required=True, type=Path)
    args = parser.parse_args()
    count = check_sarif(args.sarif)
    print(f'CodeQL findings gate passed: {count} results, zero high/critical security or error findings')


if __name__ == '__main__':
    main()
