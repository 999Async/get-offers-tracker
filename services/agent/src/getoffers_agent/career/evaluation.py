"""Re-run synthetic discovery contracts and retain auditable traces.

This is a safety/behavior evaluation, not a claim about recommendation quality.
Requires the repository's dev/test installation; does not contact live accounts.
"""

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from getoffers_agent.career.discovery import VERSION
from getoffers_agent.cli import write_report
from getoffers_agent.domain.contracts import digest
from getoffers_agent.evaluation.runner import runtime_source_hash


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[5]
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Use a new output directory to keep evaluation runs immutable")
    out.mkdir(parents=True, mode=0o700)
    tests = root / "services/agent/tests/test_career_discovery.py"
    junit = out / "contracts.xml"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(tests), "-q", f"--junitxml={junit}"],
        cwd=root,
        env={**os.environ, "GETOFFERS_CAREER_EVAL_OUT": str(out)},
        check=False,
    )
    cases = []
    if junit.exists():
        for case in ET.parse(junit).iter("testcase"):
            cases.append(
                {
                    "case_id": case.attrib["name"],
                    "duration_ms": float(case.attrib["time"]) * 1000,
                    "passed": not any(
                        case.find(tag) is not None for tag in ("failure", "error", "skipped")
                    ),
                }
            )
    traces = []
    for path in sorted((out / "traces").glob("*.json")):
        events = json.loads(path.read_text())
        calls = [e for e in events if e["event_type"] == "model.completed"]
        traces.append(
            {
                "path": str(path.relative_to(out)),
                "hash": digest(events),
                "config_hash": events[0]["payload"]["config_hash"],
                "input_tokens": sum(
                    e["payload"]["response"]["usage"]["input_tokens"] for e in calls
                ),
                "output_tokens": sum(
                    e["payload"]["response"]["usage"]["output_tokens"] for e in calls
                ),
                "cost_usd": 0,
                "model": "none",
            }
        )
    report = {
        "dataset_version": "career-synthetic-contracts-v1",
        "provenance": "synthetic",
        "controller": VERSION,
        "source_hash": runtime_source_hash(),
        "cases_hash": digest(tests.read_text()),
        "cases": cases,
        "traces": traces,
        "passed": result.returncode == 0 and bool(cases) and bool(traces),
        "quality_claim": False,
        "reviewed_real_workflows": 0,
    }
    write_report(out / "report.json", report)
    print(json.dumps({"passed": report["passed"], "cases": len(cases), "traces": len(traces)}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
