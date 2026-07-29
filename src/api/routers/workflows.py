"""Workflow management endpoints."""

import json
from pathlib import Path
from typing import Any, List, Optional, Set
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.api.models import (
    WorkflowCreateRequest,
    WorkflowResponse,
    WorkflowUpdateRequest,
    WorkflowValidationError,
    WorkflowValidationResponse,
)
from src.api.test_models import (
    TestStatus,
    WorkflowExecuteRequest,
    WorkflowExecuteResponse,
    WorkflowTestCaseCreate,
    WorkflowTestCaseResponse,
    WorkflowTestCaseUpdate,
    WorkflowTestResultResponse,
    WorkflowTestRunResponse,
    TestRunRequest,
)
from src.api.workflow_diagnostics import Diagnostic, diagnose_graph
from src.api.workflow_validation import validate_workflow
from src.audit_logging import get_logger
from src.config.dependency_validation import DependencyError, get_validator
from src.config.workflow_models import WorkflowConfig
from src.config.config_loader import get_config_loader
from src.core.workflow_test_runner import get_test_runner
from src.api.session_manager import get_session_manager

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/workflows", tags=["workflows"])


def _get_workflows_config_path() -> Path:
    """Get the path to the workflows configuration file."""
    return Path("configs") / "workflows.json"


def _load_workflows_config() -> dict:
    """Load workflows configuration from file using config loader."""
    try:
        loader = get_config_loader()
        return loader.get_config("workflows")
    except FileNotFoundError:
        return {"version": "1.0", "workflows": []}


def _save_workflows_config(config: dict) -> None:
    """Save workflows configuration to file."""
    config_path = _get_workflows_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)
    
    # Trigger reload in config loader
    try:
        loader = get_config_loader()
        loader._reload_single_file(config_path)
    except Exception as e:
        logger.warning(f"Failed to reload config in loader: {e}")


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
    request: Request,
    body: WorkflowCreateRequest,
) -> WorkflowResponse:
    """
    Create a new workflow configuration.
    
    Args:
        request: FastAPI request object
        body: Workflow creation request
        
    Returns:
        Created workflow configuration
        
    Requirements: 1.1, 2.1
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Creating workflow",
        request_id=request_id,
        workflow_id=body.id,
    )
    
    try:
        # Load existing config
        config = _load_workflows_config()
        
        # Check if workflow already exists
        if any(w["id"] == body.id for w in config["workflows"]):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Workflow already exists: {body.id}",
            )
        
        # Validate agent references
        workflow_dict = body.model_dump()
        workflow_config = WorkflowConfig(**workflow_dict)
        agent_ids = workflow_config.get_all_agent_ids()
        
        validator = get_validator()
        try:
            validator.validate_workflow_agent_references(body.id, agent_ids)
        except DependencyError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "type": "dependency_error",
                    "message": str(e),
                    "dependencies": {
                        "missing": e.missing,
                        "available": e.available,
                    },
                },
            )
        
        # Add new workflow
        config["workflows"].append(workflow_dict)
        
        # Save config
        _save_workflows_config(config)
        
        logger.info(
            "Created workflow",
            request_id=request_id,
            workflow_id=body.id,
        )
        
        return WorkflowResponse(**workflow_dict)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to create workflow",
            request_id=request_id,
            workflow_id=body.id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create workflow: {str(e)}",
        )


@router.get("", response_model=List[WorkflowResponse])
async def list_workflows(
    request: Request,
) -> List[WorkflowResponse]:
    """
    List all workflow configurations.
    
    Args:
        request: FastAPI request object
        
    Returns:
        List of workflow configurations
        
    Requirements: 1.1, 2.1
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Listing workflows",
        request_id=request_id,
    )
    
    try:
        config = _load_workflows_config()
        return [WorkflowResponse(**workflow) for workflow in config["workflows"]]
        
    except Exception as e:
        logger.error(
            "Failed to list workflows",
            request_id=request_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list workflows: {str(e)}",
        )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    request: Request,
    workflow_id: str,
) -> WorkflowResponse:
    """
    Get workflow configuration by ID.
    
    Args:
        request: FastAPI request object
        workflow_id: Workflow identifier
        
    Returns:
        Workflow configuration
        
    Requirements: 1.1, 2.1
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Getting workflow",
        request_id=request_id,
        workflow_id=workflow_id,
    )
    
    try:
        config = _load_workflows_config()
        
        # Find workflow
        workflow = next((w for w in config["workflows"] if w["id"] == workflow_id), None)
        
        if workflow is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow not found: {workflow_id}",
            )
        
        return WorkflowResponse(**workflow)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to get workflow",
            request_id=request_id,
            workflow_id=workflow_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get workflow: {str(e)}",
        )


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    request: Request,
    workflow_id: str,
    body: WorkflowUpdateRequest,
) -> WorkflowResponse:
    """
    Update workflow configuration.
    
    Args:
        request: FastAPI request object
        workflow_id: Workflow identifier
        body: Workflow update request
        
    Returns:
        Updated workflow configuration
        
    Requirements: 1.1, 2.1
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Updating workflow",
        request_id=request_id,
        workflow_id=workflow_id,
    )
    
    try:
        config = _load_workflows_config()
        
        # Find workflow
        workflow_idx = next(
            (i for i, w in enumerate(config["workflows"]) if w["id"] == workflow_id),
            None
        )
        
        if workflow_idx is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow not found: {workflow_id}",
            )
        
        # Update workflow
        workflow = config["workflows"][workflow_idx]
        update_data = body.model_dump(exclude_unset=True)
        workflow.update(update_data)
        
        # Validate agent references if workflow structure changed
        workflow_config = WorkflowConfig(**workflow)
        agent_ids = workflow_config.get_all_agent_ids()
        
        validator = get_validator()
        try:
            validator.validate_workflow_agent_references(workflow_id, agent_ids)
        except DependencyError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "type": "dependency_error",
                    "message": str(e),
                    "dependencies": {
                        "missing": e.missing,
                        "available": e.available,
                    },
                },
            )
        
        # Save config
        _save_workflows_config(config)
        
        logger.info(
            "Updated workflow",
            request_id=request_id,
            workflow_id=workflow_id,
        )
        
        return WorkflowResponse(**workflow)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to update workflow",
            request_id=request_id,
            workflow_id=workflow_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update workflow: {str(e)}",
        )


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
    request: Request,
    workflow_id: str,
) -> None:
    """
    Delete workflow configuration.
    
    Args:
        request: FastAPI request object
        workflow_id: Workflow identifier
        
    Requirements: 1.1, 2.1
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Deleting workflow",
        request_id=request_id,
        workflow_id=workflow_id,
    )
    
    try:
        config = _load_workflows_config()
        
        # Find and remove workflow
        original_count = len(config["workflows"])
        config["workflows"] = [w for w in config["workflows"] if w["id"] != workflow_id]
        
        if len(config["workflows"]) == original_count:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Workflow not found: {workflow_id}",
            )
        
        # Save config
        _save_workflows_config(config)
        
        logger.info(
            "Deleted workflow",
            request_id=request_id,
            workflow_id=workflow_id,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to delete workflow",
            request_id=request_id,
            workflow_id=workflow_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete workflow: {str(e)}",
        )


# ============================================================================
# Standalone Workflow Execution (n8n-style)
# ============================================================================

@router.post("/{workflow_id}/execute", response_model=WorkflowExecuteResponse)
async def execute_workflow(
    request: Request,
    workflow_id: str,
    body: WorkflowExecuteRequest,
) -> WorkflowExecuteResponse:
    """
    Execute a workflow standalone without session lifecycle.
    
    This endpoint runs a workflow with a single input/output, similar to n8n's
    execute workflow functionality. No session is created or persisted.
    
    Use this for:
    - Testing workflows independently
    - One-shot workflow execution
    - Integration with external systems
    - Dry-run validation
    
    Args:
        request: FastAPI request object
        workflow_id: Workflow identifier
        body: Execution request with message and options
        
    Returns:
        Execution response with result and trace
        
    Requirements: 1.1, 2.1, Testing
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Executing workflow standalone",
        request_id=request_id,
        workflow_id=workflow_id,
        dry_run=body.dry_run,
    )
    
    try:
        test_runner = get_test_runner()
        result = await test_runner.execute_workflow(workflow_id, body)
        
        logger.info(
            "Workflow execution completed",
            request_id=request_id,
            workflow_id=workflow_id,
            success=result.success,
            execution_time_ms=result.execution_time_ms,
        )
        
        return result
        
    except Exception as e:
        logger.error(
            "Workflow execution failed",
            request_id=request_id,
            workflow_id=workflow_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow execution failed: {str(e)}",
        )


@router.post("/{workflow_id}/execute/stream")
async def stream_workflow_execution(
    request: Request,
    workflow_id: str,
    body: WorkflowExecuteRequest,
) -> StreamingResponse:
    """Execute a workflow and stream real-time agent/tool deltas as SSE."""
    request_id = getattr(request.state, "request_id", None)

    async def event_stream():
        session_manager = get_session_manager()
        conversation = await session_manager.create_session(
            workflow_id=workflow_id,
            user_id="live-runner",
            metadata={"source": "workflow_live_run", **body.metadata},
        )
        async for delta in session_manager.stream_message(
            session_id=conversation.session_id,
            message=body.message,
            max_turns=None,
            metadata={"workflow_id": workflow_id, "source": "workflow_live_run", **body.metadata},
            correlation_id=request_id,
        ):
            yield delta.to_sse()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class GraphValidateRequest(BaseModel):
    """A canvas graph, saved or not.

    Deliberately loose: a node being built may have no agent assigned yet, and
    that is one of the things worth reporting rather than a reason to reject
    the request.
    """

    nodes: list[dict[str, Any]] = Field(default_factory=list)
    connections: list[dict[str, Any]] = Field(default_factory=list)
    entry_node: str | None = None
    topology: dict[str, Any] | None = None
    probe_imports: bool = False


class GraphValidateResponse(BaseModel):
    valid: bool
    diagnostics: list[Diagnostic] = Field(default_factory=list)


def _library_snapshot() -> tuple[list[dict], list[dict], list[dict]]:
    """Agents, tools and providers as plain dicts for the diagnostics engine."""
    from src.config.config_loader import get_config_loader

    loader = get_config_loader()
    try:
        agents = loader.get_agents()
    except Exception:
        agents = []
    try:
        tools = loader.get_tools()
    except Exception:
        tools = []
    try:
        providers = loader.get_api_providers()
    except Exception:
        providers = []
    return agents, tools, providers


def _diagnose_saved_workflow(workflow_id: str, probe_imports: bool = False) -> list[Diagnostic]:
    """Diagnostics for a workflow already on disk."""
    from src.config.config_loader import get_config_loader

    try:
        workflow = get_config_loader().get_workflow_by_id(workflow_id)
    except Exception:
        workflow = None
    if not workflow:
        return []
    topology = workflow.get("topology") or {}
    agents, tools, providers = _library_snapshot()
    return diagnose_graph(
        topology.get("nodes") or [],
        topology.get("connections") or topology.get("edges") or [],
        agents=agents,
        tools=tools,
        providers=providers,
        entry_node=topology.get("entry_node"),
        topology=topology,
        probe_imports=probe_imports,
    )


@router.post("/validate-graph", response_model=GraphValidateResponse)
async def validate_graph(request: Request, body: GraphValidateRequest) -> GraphValidateResponse:
    """Diagnose a graph that has not been saved yet.

    The per-workflow endpoint only works on persisted workflows, so the canvas
    had no way to check work in progress.
    """
    agents, tools, providers = _library_snapshot()
    diagnostics = diagnose_graph(
        body.nodes,
        body.connections,
        agents=agents,
        tools=tools,
        providers=providers,
        entry_node=body.entry_node,
        topology=body.topology,
        probe_imports=body.probe_imports,
    )
    return GraphValidateResponse(
        valid=not any(d.severity == "error" for d in diagnostics),
        diagnostics=diagnostics,
    )


@router.post("/{workflow_id}/validate", response_model=WorkflowValidationResponse)
async def validate_workflow_config(
    request: Request,
    workflow_id: str,
) -> WorkflowValidationResponse:
    """
    Validate a workflow configuration without executing.
    
    Checks:
    - Workflow exists and is enabled
    - All referenced agents exist
    - All referenced tools exist
    - Topology is valid
    
    Args:
        request: FastAPI request object
        workflow_id: Workflow identifier
        
    Returns:
        Validation result
        
    Requirements: 1.1, 2.1
    """
    request_id = getattr(request.state, "request_id", None)
    
    logger.info(
        "Validating workflow",
        request_id=request_id,
        workflow_id=workflow_id,
    )
    
    try:
        test_runner = get_test_runner()
        is_valid, error = test_runner.validate_workflow(workflow_id)

        # validate_workflow returns a plain string; the response model expects
        # structured errors. Feeding the raw string in raised inside Pydantic
        # and surfaced as a 500 for every invalid workflow.
        errors = (
            [WorkflowValidationError(field="workflow", message=error, error_type="validation_error")]
            if error
            else []
        )
        warnings = [
            d.message
            for d in _diagnose_saved_workflow(workflow_id)
            if d.severity in {"warning", "info"}
        ]
        blocking = [
            WorkflowValidationError(
                field=d.field or "workflow", message=d.message, error_type=d.code
            )
            for d in _diagnose_saved_workflow(workflow_id)
            if d.severity == "error"
        ]
        for extra in blocking:
            if all(e.message != extra.message for e in errors):
                errors.append(extra)

        return WorkflowValidationResponse(
            valid=is_valid and not errors,
            errors=errors,
            warnings=warnings,
        )
        
    except Exception as e:
        logger.error(
            "Workflow validation failed",
            request_id=request_id,
            workflow_id=workflow_id,
            error=str(e),
            exc_info=True,
        )
        return WorkflowValidationResponse(
            valid=False,
            errors=[
                WorkflowValidationError(
                    field="workflow", message=str(e), error_type="validation_error"
                )
            ],
            warnings=[],
        )


# ============================================================================
# Workflow Test Case Management
# ============================================================================

# In-memory storage for test cases (will be replaced with DB when migration runs)
_test_cases: dict[str, dict] = {}
_test_results: dict[str, dict] = {}
_test_runs: dict[str, dict] = {}


@router.post("/{workflow_id}/test-cases", response_model=WorkflowTestCaseResponse, status_code=status.HTTP_201_CREATED)
async def create_test_case(
    request: Request,
    workflow_id: str,
    body: WorkflowTestCaseCreate,
) -> WorkflowTestCaseResponse:
    """
    Create a test case for a workflow.
    
    Args:
        request: FastAPI request object
        workflow_id: Workflow identifier
        body: Test case creation request
        
    Returns:
        Created test case
    """
    from datetime import datetime
    from uuid import uuid4
    
    request_id = getattr(request.state, "request_id", None)
    
    # Validate workflow exists
    config = _load_workflows_config()
    if not any(w["id"] == workflow_id for w in config["workflows"]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow not found: {workflow_id}",
        )
    
    # Create test case
    test_case_id = uuid4()
    now = datetime.utcnow()
    
    test_case = {
        "id": test_case_id,
        "workflow_id": workflow_id,
        "name": body.name,
        "description": body.description,
        "input_message": body.input_message,
        "expected_agent": body.expected_agent,
        "expected_tools": body.expected_tools,
        "expected_output_contains": body.expected_output_contains,
        "expected_output_pattern": body.expected_output_pattern,
        "timeout_seconds": body.timeout_seconds,
        "enabled": body.enabled,
        "created_at": now,
        "updated_at": now,
        "created_by": None,
        "metadata": body.metadata,
    }
    
    _test_cases[str(test_case_id)] = test_case
    
    logger.info(
        "Created test case",
        request_id=request_id,
        workflow_id=workflow_id,
        test_case_id=str(test_case_id),
    )
    
    return WorkflowTestCaseResponse(**test_case)


@router.get("/{workflow_id}/test-cases", response_model=List[WorkflowTestCaseResponse])
async def list_test_cases(
    request: Request,
    workflow_id: str,
    enabled_only: bool = False,
) -> List[WorkflowTestCaseResponse]:
    """
    List test cases for a workflow.
    
    Args:
        request: FastAPI request object
        workflow_id: Workflow identifier
        enabled_only: If true, only return enabled test cases
        
    Returns:
        List of test cases
    """
    cases = [
        WorkflowTestCaseResponse(**tc)
        for tc in _test_cases.values()
        if tc["workflow_id"] == workflow_id
        and (not enabled_only or tc["enabled"])
    ]
    return cases


@router.get("/{workflow_id}/test-cases/{test_case_id}", response_model=WorkflowTestCaseResponse)
async def get_test_case(
    request: Request,
    workflow_id: str,
    test_case_id: str,
) -> WorkflowTestCaseResponse:
    """Get a specific test case."""
    if test_case_id not in _test_cases:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case not found: {test_case_id}",
        )
    
    tc = _test_cases[test_case_id]
    if tc["workflow_id"] != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case not found in workflow: {workflow_id}",
        )
    
    return WorkflowTestCaseResponse(**tc)


@router.put("/{workflow_id}/test-cases/{test_case_id}", response_model=WorkflowTestCaseResponse)
async def update_test_case(
    request: Request,
    workflow_id: str,
    test_case_id: str,
    body: WorkflowTestCaseUpdate,
) -> WorkflowTestCaseResponse:
    """Update a test case."""
    from datetime import datetime
    
    if test_case_id not in _test_cases:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case not found: {test_case_id}",
        )
    
    tc = _test_cases[test_case_id]
    if tc["workflow_id"] != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case not found in workflow: {workflow_id}",
        )
    
    # Update fields
    update_data = body.model_dump(exclude_unset=True)
    tc.update(update_data)
    tc["updated_at"] = datetime.utcnow()
    
    return WorkflowTestCaseResponse(**tc)


@router.delete("/{workflow_id}/test-cases/{test_case_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(
    request: Request,
    workflow_id: str,
    test_case_id: str,
) -> None:
    """Delete a test case."""
    if test_case_id not in _test_cases:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case not found: {test_case_id}",
        )
    
    tc = _test_cases[test_case_id]
    if tc["workflow_id"] != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case not found in workflow: {workflow_id}",
        )
    
    del _test_cases[test_case_id]


# ============================================================================
# Workflow Test Execution
# ============================================================================

@router.post("/{workflow_id}/test-cases/{test_case_id}/run", response_model=WorkflowTestResultResponse)
async def run_test_case(
    request: Request,
    workflow_id: str,
    test_case_id: str,
) -> WorkflowTestResultResponse:
    """
    Run a single test case.
    
    Args:
        request: FastAPI request object
        workflow_id: Workflow identifier
        test_case_id: Test case identifier
        
    Returns:
        Test result
    """
    from datetime import datetime
    from uuid import uuid4
    
    request_id = getattr(request.state, "request_id", None)
    
    if test_case_id not in _test_cases:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case not found: {test_case_id}",
        )
    
    tc = _test_cases[test_case_id]
    if tc["workflow_id"] != workflow_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Test case not found in workflow: {workflow_id}",
        )
    
    test_case = WorkflowTestCaseResponse(**tc)
    
    logger.info(
        "Running test case",
        request_id=request_id,
        workflow_id=workflow_id,
        test_case_id=test_case_id,
        test_name=test_case.name,
    )
    
    # Run the test
    test_runner = get_test_runner()
    result_id = uuid4()
    started_at = datetime.utcnow()
    
    try:
        exec_result, status_result, error_msg = await test_runner.run_test_case(test_case)
        
        completed_at = datetime.utcnow()
        execution_time_ms = exec_result.execution_time_ms if exec_result else 0
        
        result = {
            "id": result_id,
            "test_case_id": UUID(test_case_id),
            "workflow_id": workflow_id,
            "status": status_result,
            "actual_response": exec_result.response if exec_result else None,
            "actual_agent": exec_result.agents_called[0] if exec_result and exec_result.agents_called else None,
            "actual_tools": exec_result.tools_called if exec_result else None,
            "execution_time_ms": execution_time_ms,
            "error_message": error_msg,
            "execution_trace": exec_result.execution_trace if exec_result else None,
            "started_at": started_at,
            "completed_at": completed_at,
            "run_by": None,
            "run_id": None,
            "metadata": {},
        }
        
        _test_results[str(result_id)] = result
        
        logger.info(
            "Test case completed",
            request_id=request_id,
            test_case_id=test_case_id,
            status=status_result.value,
            execution_time_ms=execution_time_ms,
        )
        
        return WorkflowTestResultResponse(**result)
        
    except Exception as e:
        logger.error(
            "Test case execution failed",
            request_id=request_id,
            test_case_id=test_case_id,
            error=str(e),
            exc_info=True,
        )
        
        result = {
            "id": result_id,
            "test_case_id": UUID(test_case_id),
            "workflow_id": workflow_id,
            "status": TestStatus.ERROR,
            "actual_response": None,
            "actual_agent": None,
            "actual_tools": None,
            "execution_time_ms": int((datetime.utcnow() - started_at).total_seconds() * 1000),
            "error_message": str(e),
            "execution_trace": None,
            "started_at": started_at,
            "completed_at": datetime.utcnow(),
            "run_by": None,
            "run_id": None,
            "metadata": {},
        }
        
        _test_results[str(result_id)] = result
        return WorkflowTestResultResponse(**result)


@router.post("/{workflow_id}/test", response_model=WorkflowTestRunResponse)
async def run_workflow_tests(
    request: Request,
    workflow_id: str,
    body: Optional[TestRunRequest] = None,
) -> WorkflowTestRunResponse:
    """
    Run all test cases for a workflow.
    
    Args:
        request: FastAPI request object
        workflow_id: Workflow identifier
        body: Optional test run configuration
        
    Returns:
        Test run summary
    """
    from datetime import datetime
    from uuid import uuid4
    
    request_id = getattr(request.state, "request_id", None)
    
    # Get test cases for this workflow
    test_cases = [
        WorkflowTestCaseResponse(**tc)
        for tc in _test_cases.values()
        if tc["workflow_id"] == workflow_id and tc["enabled"]
    ]
    
    if not test_cases:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No enabled test cases found for workflow: {workflow_id}",
        )
    
    run_id = uuid4()
    started_at = datetime.utcnow()
    
    logger.info(
        "Starting test run",
        request_id=request_id,
        workflow_id=workflow_id,
        run_id=str(run_id),
        test_count=len(test_cases),
    )
    
    # Run all tests
    test_runner = get_test_runner()
    passed = 0
    failed = 0
    errors = 0
    skipped = 0
    
    for tc in test_cases:
        try:
            exec_result, status_result, error_msg = await test_runner.run_test_case(tc)
            
            if status_result == TestStatus.PASSED:
                passed += 1
            elif status_result == TestStatus.FAILED:
                failed += 1
            elif status_result == TestStatus.ERROR:
                errors += 1
            elif status_result == TestStatus.SKIPPED:
                skipped += 1
                
        except Exception as e:
            logger.error(
                "Test case error",
                test_case_id=str(tc.id),
                error=str(e),
            )
            errors += 1
    
    completed_at = datetime.utcnow()
    total = len(test_cases)
    
    # Determine overall status
    if errors > 0:
        run_status = TestStatus.ERROR
    elif failed > 0:
        run_status = TestStatus.FAILED
    elif passed == total:
        run_status = TestStatus.PASSED
    else:
        run_status = TestStatus.PASSED
    
    run = {
        "id": run_id,
        "workflow_id": workflow_id,
        "name": body.name if body else f"Test run {run_id}",
        "total_tests": total,
        "passed_tests": passed,
        "failed_tests": failed,
        "error_tests": errors,
        "skipped_tests": skipped,
        "status": run_status,
        "started_at": started_at,
        "completed_at": completed_at,
        "run_by": None,
        "metadata": body.metadata if body else {},
    }
    
    _test_runs[str(run_id)] = run
    
    logger.info(
        "Test run completed",
        request_id=request_id,
        workflow_id=workflow_id,
        run_id=str(run_id),
        passed=passed,
        failed=failed,
        errors=errors,
    )
    
    return WorkflowTestRunResponse(**run)


@router.get("/{workflow_id}/test-results", response_model=List[WorkflowTestResultResponse])
async def list_test_results(
    request: Request,
    workflow_id: str,
    limit: int = 50,
) -> List[WorkflowTestResultResponse]:
    """
    List recent test results for a workflow.
    
    Args:
        request: FastAPI request object
        workflow_id: Workflow identifier
        limit: Maximum number of results to return
        
    Returns:
        List of test results
    """
    results = [
        WorkflowTestResultResponse(**r)
        for r in _test_results.values()
        if r["workflow_id"] == workflow_id
    ]
    
    # Sort by started_at descending
    results.sort(key=lambda r: r.started_at, reverse=True)
    
    return results[:limit]


@router.get("/{workflow_id}/test-runs", response_model=List[WorkflowTestRunResponse])
async def list_test_runs(
    request: Request,
    workflow_id: str,
    limit: int = 20,
) -> List[WorkflowTestRunResponse]:
    """
    List recent test runs for a workflow.
    
    Args:
        request: FastAPI request object
        workflow_id: Workflow identifier
        limit: Maximum number of runs to return
        
    Returns:
        List of test runs
    """
    runs = [
        WorkflowTestRunResponse(**r)
        for r in _test_runs.values()
        if r["workflow_id"] == workflow_id
    ]
    
    # Sort by started_at descending
    runs.sort(key=lambda r: r.started_at, reverse=True)
    
    return runs[:limit]
