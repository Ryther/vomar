# Adapted from Ryther/hapatchy, MIT; ecee6ed273989a984d5d4a72dfbbd610e8dea57d.
"""Export Sonar's complete paginated findings for one CI analysis."""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]
Fetch = Callable[[str, JsonObject], JsonObject]
METRICS = "ncloc,files,coverage,line_coverage,duplicated_lines_density,bugs,vulnerabilities,code_smells,security_hotspots,reliability_rating,security_rating,sqale_rating,alert_status"
NEW_COVERAGE_METRICS = "new_coverage,new_line_coverage,new_lines_to_cover,new_uncovered_lines,new_conditions_to_cover,new_uncovered_conditions"
METRICS += "," + NEW_COVERAGE_METRICS
FILE_METRICS = "ncloc,coverage,line_coverage,duplicated_lines_density," + NEW_COVERAGE_METRICS


def _pages(fetch: Fetch, endpoint: str, params: JsonObject, field: str, size: int) -> list[JsonObject]:
    rows: list[JsonObject] = []
    page = 1
    while True:
        response = fetch(endpoint, {**params, "p": page, "ps": size})
        batch = response[field]
        rows.extend(batch)
        total = response.get("paging", {}).get("total", response.get("total"))
        if total is None or len(rows) >= total:
            return rows
        if not batch:
            raise ValueError(f"Incomplete Sonar pagination for {endpoint}")
        page += 1


def _write_json(directory: Path, name: str, value: Any) -> None:
    (directory / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _fingerprint(issue: JsonObject) -> tuple[str, str, str]:
    # Sonar embeds its project key before the first colon in component paths.
    component = issue.get("component", "").partition(":")[2]
    return issue.get("rule", ""), component, issue.get("hash", issue.get("message", ""))


def introduced_issues(before: list[JsonObject], after: list[JsonObject]) -> list[JsonObject]:
    remaining = Counter(_fingerprint(issue) for issue in before)
    introduced = []
    for issue in after:
        fingerprint = _fingerprint(issue)
        if remaining[fingerprint]:
            remaining[fingerprint] -= 1
        else:
            introduced.append(issue)
    return introduced


def export_analysis(
    fetch: Fetch, project: str, directory: Path, *, pull_request: str = "", page_size: int = 500,
    backend: str = "cloud",
) -> JsonObject:
    """Write unabridged raw data and a readable index; reject missing PR analyses."""
    if backend not in {"cloud", "community"}:
        raise ValueError("Unsupported Sonar report backend")
    hotspot_project_parameter = "projectKey" if backend == "cloud" else "project"
    directory.mkdir(parents=True, exist_ok=True)
    scope: JsonObject = {"pullRequest": pull_request} if pull_request else {}
    gate = fetch("/api/qualitygates/project_status", {"projectKey": project, **scope})
    if pull_request and gate["projectStatus"]["status"] == "NONE":
        raise ValueError("Pull-request quality gate not computed; analysis is not ready")
    measures = fetch("/api/measures/component", {"component": project, "metricKeys": METRICS, **scope})
    issues = _pages(fetch, "/api/issues/search", {"componentKeys": project, "resolved": "false", **scope}, "issues", page_size)
    files = _pages(fetch, "/api/measures/component_tree", {"component": project, "metricKeys": FILE_METRICS, "qualifiers": "FIL", **scope}, "components", page_size)
    hotspots = _pages(fetch, "/api/hotspots/search", {hotspot_project_parameter: project, **scope}, "hotspots", page_size)
    for name, value in (("gate.json", gate), ("measures.json", measures), ("issues.json", issues), ("files.json", files), ("hotspots.json", hotspots)):
        _write_json(directory, name, value)
    status = gate["projectStatus"]["status"]
    lines = ["# Sonar analysis report", "", f"Project: `{project}`", f"Scope: {'PR #' + pull_request if pull_request else 'overall branch'}", f"Quality gate: **{status}**", f"Open issues: **{len(issues)}**", f"Security hotspots: **{len(hotspots)}**", "", "The JSON files retain full API records, including issue flows and file measures.", "", "## Quality gate conditions", ""]
    for condition in gate["projectStatus"].get("conditions", []):
        lines.append(f"- `{condition.get('metricKey', '')}`: **{condition.get('status', '')}** · actual {condition.get('actualValue', 'unknown')} · threshold {condition.get('comparator', '')} {condition.get('errorThreshold', 'unknown')}")
    lines.extend(["", "## Open issues", ""])
    for issue in issues:
        location = issue.get("component", "").partition(":")[2]
        line = issue.get("line")
        position = f"{location}:{line}" if line else location
        lines.append(f"- `{issue.get('key', '')}` · `{issue.get('rule', '')}` · {position} · {issue.get('message', '').replace(chr(10), ' ')}")
    if not issues:
        lines.append("No open issues in this scope.")
    (directory / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"gate": gate, "issues": issues, "files": files, "hotspots": hotspots}


def _http_fetch(base_url: str, token: str) -> Fetch:
    if not (base_url == "https://sonarcloud.io" or base_url == "http://127.0.0.1:9000"):
        raise ValueError("Unsupported Sonar API endpoint")

    def fetch(path: str, params: JsonObject) -> JsonObject:
        url = base_url + path + "?" + urllib.parse.urlencode(params)
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
            result: JsonObject = json.load(response)
        return result

    return fetch


def export_candidate(fetch: Fetch, project: str, directory: Path, pull_request: str,
                     sha: str, receipt: Path) -> JsonObject:
    """Bind a Cloud report to its compute task and reject replaced PR state."""
    if not re.fullmatch('[0-9a-f]{40}', sha) or not pull_request.isdigit():
        raise ValueError('Exact candidate SHA and PR number are required')
    fields = dict(line.split('=', 1) for line in receipt.read_text().splitlines() if '=' in line)
    task_id = fields.get('ceTaskId')
    if fields.get('projectKey') != project or not task_id:
        raise ValueError('Scanner receipt belongs to another project or has no task')
    task = fetch('/api/ce/task', {'id': task_id})['task']
    if (task.get('id') != task_id or task.get('componentKey') != project or
            str(task.get('pullRequest')) != pull_request or task.get('status') != 'SUCCESS' or
            not task.get('analysisId')):
        raise ValueError('Candidate compute task is incomplete or belongs to another scope')

    def current():
        rows = fetch('/api/project_pull_requests/list', {'project': project})['pullRequests']
        matches = [row for row in rows if str(row.get('key')) == pull_request]
        if len(matches) != 1 or matches[0].get('commit', {}).get('sha') != sha or not matches[0].get('analysisDate'):
            raise ValueError('Latest PR analysis does not match the candidate commit')
        return matches[0]['analysisDate']

    before = current()
    gate = fetch('/api/qualitygates/project_status', {'analysisId': task['analysisId']})
    def bound_fetch(path, params):
        return gate if path == '/api/qualitygates/project_status' else fetch(path, params)
    result = export_analysis(bound_fetch, project, directory, pull_request=pull_request)
    if current() != before:
        raise ValueError('PR analysis changed during report export')
    _write_json(directory, 'identity.json', {
        'sourceCommit': sha, 'taskId': task_id, 'analysisId': task['analysisId'],
        'pullRequest': pull_request, 'analysisDate': before,
        'languages': ['python', 'javascript', 'kotlin'],
        'firmwareC': 'separate mandatory CodeQL required check',
        'fullReleaseAnalysis': False,
    })
    if gate['projectStatus']['status'] != 'OK':
        raise ValueError('Candidate analysis quality gate failed')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="https://sonarcloud.io")
    parser.add_argument("--backend", choices=("cloud", "community"), default="cloud")
    parser.add_argument("--project", required=True)
    parser.add_argument("--pull-request", default="")
    parser.add_argument("--sha")
    parser.add_argument("--task-file", type=Path)
    args = parser.parse_args()
    if args.pull_request and args.backend != "cloud":
        parser.error("PR export requires Cloud backend")
    fetch = _http_fetch(args.host, os.environ.get("SONAR_TOKEN", ""))
    if args.pull_request:
        if not args.sha or not args.task_file:
            parser.error('PR export requires --sha and --task-file')
        export_candidate(fetch, args.project, Path('sonar-report'), args.pull_request,
                         args.sha, args.task_file)
        return
    export_analysis(
        fetch,
        args.project,
        Path("sonar-report"),
        pull_request=args.pull_request,
        backend=args.backend,
    )


if __name__ == "__main__":
    main()
