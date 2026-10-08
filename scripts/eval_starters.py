#!/usr/bin/env python
"""Grade the shipped workflows against a live model.

    uv run python scripts/eval_starters.py [--cases evals/starters.json] [--only ID] [--json out.json]

Every case runs through the same path the API uses (session, runtime, real
tools) and is judged by the test-case judge: which agent handled it, which
tools ran, and what the answer contains. The run fails when the pass rate is
below the threshold in the cases file. Needs a provider key in the
environment (or .env); costs a few cents per run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", default=str(ROOT / "evals" / "starters.json"))
    parser.add_argument("--only", help="run only this workflow id")
    parser.add_argument("--json", help="write per-case results here")
    args = parser.parse_args()

    from src.infrastructure.redis_guard import ensure_redis_or_disable

    ensure_redis_or_disable()

    from src.api.test_models import TestStatus, WorkflowTestCaseResponse
    from src.core.workflow_test_runner import get_test_runner, responding_agent

    spec = json.loads(Path(args.cases).read_text())
    threshold = float(spec.get("threshold", 0.9))
    cases = [c for c in spec["cases"] if not args.only or c["workflow_id"] == args.only]
    runner = get_test_runner()
    now = datetime.now(UTC)
    results = []

    for case in cases:
        test_case = WorkflowTestCaseResponse(
            id=uuid4(),
            workflow_id=case["workflow_id"],
            name=case["name"],
            description=None,
            input_message=case["input_message"],
            expected_agent=case.get("expected_agent"),
            expected_tools=case.get("expected_tools"),
            expected_output_contains=case.get("expected_output_contains"),
            expected_output_pattern=case.get("expected_output_pattern"),
            timeout_seconds=int(case.get("timeout_seconds", 240)),
            enabled=True,
            created_at=now,
            updated_at=now,
            created_by="eval",
            metadata={},
        )
        started = time.perf_counter()
        result, verdict, message = await runner.run_test_case(test_case)
        seconds = round(time.perf_counter() - started, 1)
        mark = "PASS" if verdict is TestStatus.PASSED else verdict.value.upper()
        print(f"{mark:6} {seconds:6.1f}s  {case['workflow_id']}: {case['name']}")
        if verdict is not TestStatus.PASSED:
            print(f"         {message}")
            if result is not None:
                print(f"         answer: {result.response[:200]!r}")
        results.append(
            {
                **case,
                "status": verdict.value,
                "message": message,
                "seconds": seconds,
                "answer": result.response if result else None,
                "agent": responding_agent(result) if result else None,
                "tools": result.tools_called if result else None,
            }
        )

    passed = sum(1 for r in results if r["status"] == TestStatus.PASSED.value)
    rate = passed / len(results) if results else 0.0
    print(f"\n{passed}/{len(results)} passed ({rate:.0%}); threshold {threshold:.0%}")
    if args.json:
        Path(args.json).write_text(json.dumps({"rate": rate, "results": results}, indent=2))
    return 0 if results and rate >= threshold else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
