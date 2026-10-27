"""Compare supported PR languages on a disposable, credential-free Sonar server."""
# Adapted from Ryther/hapatchy, MIT; ecee6ed273989a984d5d4a72dfbbd610e8dea57d.

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

if __package__:
    from .sonar_report import export_analysis, introduced_issues
else:
    from sonar_report import export_analysis, introduced_issues

ROOT = Path(__file__).resolve().parents[2]
SERVER = "http://127.0.0.1:9000"
SETTINGS = ROOT / ".github/sonar-pr.properties"
REPORTS = None
IMAGES = json.loads((ROOT / ".github/sonar-community.json").read_text())
SCANNER = IMAGES["sonarsource/sonar-scanner-cli"]


def request(path: str, params: dict[str, Any] | None = None, *, post: bool = False, token: str = "") -> dict[str, Any]:
    data = urllib.parse.urlencode(params or {}).encode() if post else None
    query = "" if post or not params else "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        credentials = base64.b64encode(b"admin:admin").decode()
        headers["Authorization"] = f"Basic {credentials}"
    with urllib.request.urlopen(urllib.request.Request(SERVER + path + query, data=data, headers=headers), timeout=30) as response:
        if response.status == 204:
            return {}
        return json.load(response)


def ready() -> None:
    for _ in range(120):
        try:
            if request("/api/system/status")["status"] == "UP":
                return
        except (OSError, KeyError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError("Disposable Sonar did not become healthy")


def projects() -> None:
    ready()
    for name in ("vomar-baseline", "vomar-candidate"):
        request("/api/projects/create", {"project": name, "name": name}, post=True)


def scan(source: Path, project: str, output: Path, token: str) -> int:
    source = source.resolve()
    output = output.resolve()
    task = output / (project + "-task")
    task.mkdir(parents=True, exist_ok=True)
    task.chmod(0o777)  # Scanner container UID 1000 writes its task receipt here.
    receipt = task / "report-task.txt"
    receipt.unlink(missing_ok=True)
    command = [
        "docker", "run", "--rm", "--network", "host", "-w", str(source), "-e", "SONAR_TOKEN",
        "-e", f"SONAR_HOST_URL={SERVER}", "-v", f"{source}:{source}:ro",
        "-v", f"{task}:/sonar-task",
        "-v", f"{SETTINGS}:/settings.properties:ro",
        "-v", f"{REPORTS}:/reports:ro", SCANNER,
        f"-Dsonar.projectKey={project}", "-Dsonar.working.directory=/sonar-task",
        "-Dproject.settings=/settings.properties", "-Dsonar.scm.disabled=false",
        "-Dsonar.qualitygate.wait=true",
    ]
    if project == "vomar-candidate":
        command.extend([
            "-Dsonar.python.coverage.reportPaths=/reports/python-coverage.xml",
            "-Dsonar.javascript.lcov.reportPaths=/reports/lcov.info",
            "-Dsonar.coverage.jacoco.xmlReportPaths=/reports/core-jacoco.xml,/reports/app-jacoco.xml",
        ])
    with (output / (project + "-scanner.log")).open("w") as log:
        result = subprocess.run(command, env={**os.environ, "SONAR_TOKEN": token}, stdout=log, stderr=subprocess.STDOUT, check=False)
    if not receipt.exists():
        raise RuntimeError(f"{project} did not submit an analysis (scanner exit {result.returncode})")
    fields = {}
    for line in receipt.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    task_id = fields["ceTaskId"]
    for _ in range(60):
        state = request("/api/ce/task", {"id": task_id}, token=token)["task"]["status"]
        if state == "SUCCESS":
            return result.returncode
        if state in {"FAILED", "CANCELED"}:
            raise RuntimeError(f"{project} compute task {state}")
        time.sleep(2)
    raise RuntimeError(f"{project} compute task timed out")


def candidate_scan_ok(exit_code: int, gate_status: str) -> bool:
    return exit_code == 0 and gate_status == "OK"


def compare(base: Path, candidate: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    token_name = "ephemeral-ci-" + secrets.token_hex(4)
    token = request("/api/user_tokens/generate", {"name": token_name}, post=True)["token"]
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{token}", flush=True)
    try:
        scan_codes = {}
        for project, source in (("vomar-baseline", base), ("vomar-candidate", candidate)):
            scan_codes[project] = scan(source, project, output, token)
            export_analysis(lambda path, params: request(path, params, token=token), project, output / project, backend="community")
        before = json.loads((output / "vomar-baseline/issues.json").read_text())
        after = json.loads((output / "vomar-candidate/issues.json").read_text())
        introduced = introduced_issues(before, after)
        gate = json.loads((output / "vomar-candidate/gate.json").read_text())["projectStatus"]["status"]
        candidate_code = scan_codes["vomar-candidate"]
        (output / "introduced.json").write_text(json.dumps(introduced, indent=2) + "\n")
        lines = ["# Sonar Community PR comparison", "", f"Baseline open issues: {len(before)}", f"Candidate open issues: {len(after)}", f"Introduced issues: **{len(introduced)}**", f"Candidate quality gate: **{gate}**", f"Candidate scanner exit: **{candidate_code}**", "", "Full baseline and candidate reports, API JSON and scanner logs are included.", ""]
        for issue in introduced:
            lines.append(f"- `{issue.get('rule', '')}` · `{issue.get('component', '').partition(':')[2]}` · {issue.get('message', '')}")
        (output / "report.md").write_text("\n".join(lines) + "\n")
        if introduced:
            raise RuntimeError(f"{len(introduced)} Sonar issues introduced by this PR")
        if not candidate_scan_ok(candidate_code, gate):
            raise RuntimeError(f"Candidate Sonar scan failed (exit {candidate_code}, gate {gate})")
    finally:
        request("/api/user_tokens/revoke", {"name": token_name}, post=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--reports', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sha', required=True)
    args = parser.parse_args()
    global REPORTS
    REPORTS = args.reports.resolve()
    from .prepare_pr_analysis import prepare
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = 'vomar-sonar-' + secrets.token_hex(6)
    try:
        prepare(REPORTS, args.candidate, args.sha)
        subprocess.run([
            'docker', 'run', '--detach', '--name', name,
            '--publish', '127.0.0.1:9000:9000', '--memory=4g', '--cpus=2',
            '-e', 'SONAR_ES_BOOTSTRAP_CHECKS_DISABLE=true', IMAGES['library/sonarqube'],
        ], check=True, capture_output=True)
        projects()
        compare(args.base, args.candidate, output)
        (output/'scope.json').write_text(json.dumps({
            'sourceCommit': args.sha, 'profile': 'community-pr',
            'languages': ['python', 'javascript', 'kotlin'],
            'firmwareC': 'separate mandatory CodeQL required check',
            'fullReleaseAnalysis': False,
        }, indent=2) + '\n')
    except Exception:
        if not (output/'report.md').exists():
            (output/'report.md').write_text('# Sonar PR scan failed\n\nNo complete analysis was produced. See workflow output and scanner/server logs.\n')
        with (output/'server.log').open('w') as log:
            subprocess.run(['docker', 'logs', name], stdout=log, stderr=subprocess.STDOUT, check=False)
        raise
    finally:
        subprocess.run(['docker', 'rm', '--force', name], check=False, capture_output=True)


if __name__ == '__main__':
    main()
