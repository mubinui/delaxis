"""CrewAI workflow test runner."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any
from uuid import uuid4

from src.api.session_manager import SessionManager
from src.api.test_models import (
    TestStatus,
    WorkflowExecuteRequest,
    WorkflowExecuteResponse,
    WorkflowTestCaseResponse,
)
from src.config.dependency_validation import DependencyError, get_validator
from src.config.workflow_registry import get_workflow_registry


class WorkflowTestRunner:
    """Run workflows through the same CrewAI session manager used by the API."""

    def __init__(self, session_manager: SessionManager | None = None) -> None:
        self.session_manager = session_manager or SessionManager()
        self.workflow_registry = get_workflow_registry()

    async def run_workflow_test(
        self,
        workflow_id: str,
        message: str,
        user_id: str = "test-user",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = await self.session_manager.create_session(
            workflow_id=workflow_id,
            user_id=user_id,
            metadata={"test_run_id": str(uuid4()), **(metadata or {})},
        )
        return await self.session_manager.process_message(
            session_id=session.session_id,
            message=message,
            metadata=metadata,
        )

    async def execute_workflow(
        self,
        workflow_id: str,
        body: WorkflowExecuteRequest,
    ) -> WorkflowExecuteResponse:
        """Execute or dry-run a CrewAI workflow through the production session layer."""
        started = time.perf_counter()
        is_valid, error = self.validate_workflow(workflow_id)
        if not is_valid:
            return WorkflowExecuteResponse(
                workflow_id=workflow_id,
                response="",
                execution_time_ms=round((time.perf_counter() - started) * 1000),
                success=False,
                error_message=error,
                metadata={"runtime": "crewai", "validated": False},
            )

        if body.dry_run:
            return WorkflowExecuteResponse(
                workflow_id=workflow_id,
                response="Dry run passed. CrewAI workflow topology, agents, and tools are valid.",
                execution_time_ms=round((time.perf_counter() - started) * 1000),
                success=True,
                metadata={"runtime": "crewai", "dry_run": True, "validated": True},
            )

        try:
            result = await asyncio.wait_for(
                self.run_workflow_test(
                    workflow_id=workflow_id,
                    message=body.message,
                    user_id=body.metadata.get("user_id", "workflow-runner"),
                    metadata={"source": "workflow_execute", **body.metadata},
                ),
                timeout=body.timeout_seconds,
            )
            run_metadata = result.get("metadata", {})
            return WorkflowExecuteResponse(
                workflow_id=workflow_id,
                response=result.get("response", ""),
                execution_time_ms=round((time.perf_counter() - started) * 1000),
                agents_called=run_metadata.get("agents_called", []),
                tools_called=run_metadata.get("tools_called", []),
                execution_trace=run_metadata.get("trace_steps", []),
                success=True,
                metadata=run_metadata,
            )
        except TimeoutError:
            return WorkflowExecuteResponse(
                workflow_id=workflow_id,
                response="",
                execution_time_ms=round((time.perf_counter() - started) * 1000),
                success=False,
                error_message=f"Timed out after {body.timeout_seconds}s",
                metadata={"runtime": "crewai", "timed_out": True},
            )
        except Exception as exc:
            return WorkflowExecuteResponse(
                workflow_id=workflow_id,
                response="",
                execution_time_ms=round((time.perf_counter() - started) * 1000),
                success=False,
                error_message=str(exc),
                metadata={"runtime": "crewai"},
            )

    async def run_test_case(
        self, test_case: WorkflowTestCaseResponse
    ) -> tuple[WorkflowExecuteResponse | None, TestStatus, str | None]:
        """Run one test case and judge it against every expectation it declares.

        Returns the execution result, the verdict, and a message naming each
        expectation that was not met (None when the case passed).
        """
        if not test_case.enabled:
            return None, TestStatus.SKIPPED, "Test case is disabled"

        request = WorkflowExecuteRequest(
            message=test_case.input_message,
            timeout_seconds=test_case.timeout_seconds,
            metadata={"test_case_id": str(test_case.id)},
        )
        result = await self.execute_workflow(test_case.workflow_id, request)

        if not result.success:
            return result, TestStatus.ERROR, result.error_message or "Workflow run failed"

        failures = judge(test_case, result)
        if failures:
            return result, TestStatus.FAILED, "; ".join(failures)
        return result, TestStatus.PASSED, None

    def validate_workflow(self, workflow_id: str) -> tuple[bool, str | None]:
        """Validate CrewAI workflow topology and dependency references."""
        workflow = self.workflow_registry.get_workflow(workflow_id)
        if workflow is None:
            return False, f"Workflow not found: {workflow_id}"
        if not workflow.enabled:
            return False, f"Workflow is disabled: {workflow_id}"
        runtime = getattr(workflow.runtime, "value", workflow.runtime)
        if runtime != "crewai":
            return False, f"Workflow {workflow_id} is not configured for the CrewAI runtime"
        if not workflow.topology.nodes:
            return False, f"Workflow {workflow_id} has no topology nodes"
        if workflow.topology.entry_node not in {node.id for node in workflow.topology.nodes}:
            return False, f"Workflow {workflow_id} entry_node is not present in topology nodes"

        validator = get_validator()
        try:
            validator.validate_workflow_agent_references(workflow_id, workflow.get_all_agent_ids())
        except DependencyError as exc:
            return False, str(exc)

        return True, None


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def responding_agent(result: WorkflowExecuteResponse) -> str | None:
    """The agent that did the work: the last specialist to start, else the first agent.

    In a manager-led run the manager both starts and finishes, so the answer to
    "which agent handled this" is the specialist it delegated to, if any.
    """
    ids = list(result.metadata.get("agent_ids_called") or [])
    manager = result.metadata.get("manager_agent_id")
    specialists = [agent_id for agent_id in ids if agent_id != manager]
    if specialists:
        return str(specialists[-1])
    if ids:
        return str(ids[0])
    return result.agents_called[0] if result.agents_called else None


def judge(test_case: WorkflowTestCaseResponse, result: WorkflowExecuteResponse) -> list[str]:
    """Return one message per unmet expectation; an empty list is a pass."""
    failures: list[str] = []
    response = result.response or ""

    if test_case.expected_agent:
        ran = {
            _norm(name)
            for name in [*result.agents_called, *(result.metadata.get("agent_ids_called") or [])]
        }
        if _norm(test_case.expected_agent) not in ran:
            failures.append(
                f"expected agent '{test_case.expected_agent}' did not run "
                f"(ran: {', '.join(result.agents_called) or 'none'})"
            )

    if test_case.expected_tools:
        called = {_norm(tool) for tool in result.tools_called}
        missing = [tool for tool in test_case.expected_tools if _norm(tool) not in called]
        if missing:
            failures.append(
                f"expected tools not called: {', '.join(missing)} "
                f"(called: {', '.join(result.tools_called) or 'none'})"
            )

    if test_case.expected_output_contains:
        lowered = response.lower()
        absent = [
            text for text in test_case.expected_output_contains if text.lower() not in lowered
        ]
        if absent:
            failures.append("response does not contain: " + ", ".join(repr(t) for t in absent))

    if test_case.expected_output_pattern:
        try:
            if not re.search(test_case.expected_output_pattern, response, re.DOTALL):
                failures.append(
                    f"response does not match pattern {test_case.expected_output_pattern!r}"
                )
        except re.error as exc:
            failures.append(f"expected_output_pattern is not a valid regex: {exc}")

    return failures


_test_runner: WorkflowTestRunner | None = None


def get_test_runner() -> WorkflowTestRunner:
    """Return a process-wide CrewAI workflow test runner."""
    global _test_runner
    if _test_runner is None:
        _test_runner = WorkflowTestRunner()
    return _test_runner
