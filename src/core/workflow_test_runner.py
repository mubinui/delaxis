"""CrewAI workflow test runner."""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

from src.api.session_manager import SessionManager
from src.api.test_models import WorkflowExecuteRequest, WorkflowExecuteResponse
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
            result = await self.run_workflow_test(
                workflow_id=workflow_id,
                message=body.message,
                user_id=body.metadata.get("user_id", "workflow-runner"),
                metadata={"source": "workflow_execute", **body.metadata},
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
        except Exception as exc:
            return WorkflowExecuteResponse(
                workflow_id=workflow_id,
                response="",
                execution_time_ms=round((time.perf_counter() - started) * 1000),
                success=False,
                error_message=str(exc),
                metadata={"runtime": "crewai"},
            )

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


_test_runner: WorkflowTestRunner | None = None


def get_test_runner() -> WorkflowTestRunner:
    """Return a process-wide CrewAI workflow test runner."""
    global _test_runner
    if _test_runner is None:
        _test_runner = WorkflowTestRunner()
    return _test_runner
