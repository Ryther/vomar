# Adapted from Ryther/hapatchy, MIT; ecee6ed273989a984d5d4a72dfbbd610e8dea57d.
"""Fail closed when the scanner selected for an event did not produce a report."""

from __future__ import annotations

import os


def _flag(name: str) -> bool:
    value = os.environ[name]
    if value not in {"true", "false"}:
        raise SystemExit(f"Invalid {name} value")
    return value == "true"


def evaluate(
    event_name: str,
    trusted_pr: bool,
    coverage: str,
    cloud: str,
    community: str,
    report_present: bool,
) -> bool:
    """Return whether coverage and the event's sole expected scanner passed."""
    if coverage != "success" or not report_present:
        return False
    if event_name in {"push", "workflow_dispatch"}:
        return cloud == "success" and community == "skipped"
    if event_name == "pull_request":
        if trusted_pr:
            return cloud == "success" and community == "skipped"
        return community == "success" and cloud == "skipped"
    return False


def main() -> None:
    """Evaluate explicit GitHub job outcomes without using a privileged token."""
    if not evaluate(
        os.environ["SONAR_EVENT_NAME"],
        _flag("SONAR_TRUSTED_PR"),
        os.environ["SONAR_COVERAGE_RESULT"],
        os.environ["SONAR_CLOUD_RESULT"],
        os.environ["SONAR_COMMUNITY_RESULT"],
        _flag("SONAR_REPORT_PRESENT"),
    ):
        raise SystemExit("Required Sonar scan or report is missing or unsuccessful")


if __name__ == "__main__":
    main()
