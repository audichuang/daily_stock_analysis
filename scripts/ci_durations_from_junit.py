#!/usr/bin/env python3
"""Rebuild .github/ci-test-durations.json from the CI shards' junit reports.

Download the ``pytest-junit-*`` artifacts of one green CI run, then::

    gh run download <run-id> -p 'pytest-junit-*' -D /tmp/junit
    python scripts/ci_durations_from_junit.py --run <run-id> /tmp/junit/*/pytest-junit.xml
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DURATIONS_PATH = REPO_ROOT / ".github" / "ci-test-durations.json"


def classname_to_file(classname: str, repo_root: Path = REPO_ROOT) -> str | None:
    """Map a junit classname (``tests.test_x.TestY``) to its test module path."""
    parts = classname.split(".")
    for end in range(len(parts), 0, -1):
        candidate = "/".join(parts[:end]) + ".py"
        if (repo_root / candidate).is_file():
            return candidate
    return None


def file_durations(reports: list[Path], repo_root: Path = REPO_ROOT) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for report in reports:
        for case in ET.parse(report).iter("testcase"):
            test_file = classname_to_file(case.get("classname", ""), repo_root)
            if test_file:
                totals[test_file] += float(case.get("time") or 0)
    return {path: round(seconds, 3) for path, seconds in sorted(totals.items())}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=int, required=True, help="CI workflow run id the reports came from")
    parser.add_argument("--output", type=Path, default=DEFAULT_DURATIONS_PATH)
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()

    durations = file_durations(args.reports)
    if not durations:
        raise SystemExit("No test cases mapped to tests/*.py files")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    payload = {
        "schema_version": 1,
        "baseline": {
            "commit": commit,
            "workflow_run": args.run,
            "captured_at": datetime.date.today().isoformat(),
        },
        "durations": durations,
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(durations)} files, {sum(durations.values()):.0f}s total -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
