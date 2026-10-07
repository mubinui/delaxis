"""
Workflow Test Models for database persistence.

Provides SQLAlchemy models and Pydantic schemas for workflow test cases and results.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

# SQLAlchemy models live in the unified schema so Alembic sees one metadata;
# re-exported here for backwards compatibility with existing imports.
from src.infrastructure.database.schema import (  # noqa: F401
    Base,
    WorkflowTestCase,
    WorkflowTestResult,
    WorkflowTestRun,
)


class TestStatus(StrEnum):
    """Status of a test execution."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


# Pydantic Schemas for API


class WorkflowTestCaseCreate(BaseModel):
    """Request to create a workflow test case."""

    workflow_id: str | None = Field(
        default=None,
        description="Ignored when present: the workflow is the one named in the URL",
    )
    name: str = Field(description="Name of the test case")
    description: str | None = Field(default=None, description="Test case description")
    input_message: str = Field(description="Message to send to the workflow")
    expected_agent: str | None = Field(default=None, description="Expected agent to respond")
    expected_tools: list[str] | None = Field(
        default=None, description="Expected tools to be called"
    )
    expected_output_contains: list[str] | None = Field(
        default=None, description="Strings that should appear in output"
    )
    expected_output_pattern: str | None = Field(
        default=None, description="Regex pattern to match output"
    )
    timeout_seconds: int = Field(default=60, ge=1, le=300, description="Timeout in seconds")
    enabled: bool = Field(default=True, description="Whether test case is enabled")
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowTestCaseUpdate(BaseModel):
    """Request to update a workflow test case."""

    name: str | None = None
    description: str | None = None
    input_message: str | None = None
    expected_agent: str | None = None
    expected_tools: list[str] | None = None
    expected_output_contains: list[str] | None = None
    expected_output_pattern: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None


class WorkflowTestCaseResponse(BaseModel):
    """Response containing a workflow test case."""

    id: UUID
    workflow_id: str
    name: str
    description: str | None
    input_message: str
    expected_agent: str | None
    expected_tools: list[str] | None
    expected_output_contains: list[str] | None
    expected_output_pattern: str | None
    timeout_seconds: int
    enabled: bool
    created_at: datetime
    updated_at: datetime
    created_by: str | None
    metadata: dict[str, Any]

    model_config = {"from_attributes": True}


class WorkflowTestResultResponse(BaseModel):
    """Response containing a test result."""

    id: UUID
    test_case_id: UUID
    workflow_id: str
    status: TestStatus
    actual_response: str | None
    actual_agent: str | None
    actual_tools: list[str] | None
    execution_time_ms: int | None
    error_message: str | None
    execution_trace: list[dict[str, Any]] | dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None
    run_by: str | None
    run_id: UUID | None
    metadata: dict[str, Any]

    model_config = {"from_attributes": True}


class WorkflowTestRunResponse(BaseModel):
    """Response containing a test run summary."""

    id: UUID
    workflow_id: str | None
    name: str | None
    total_tests: int
    passed_tests: int
    failed_tests: int
    error_tests: int
    skipped_tests: int
    status: TestStatus
    started_at: datetime
    completed_at: datetime | None
    run_by: str | None
    metadata: dict[str, Any]
    pass_rate: float = Field(default=0.0)

    model_config = {"from_attributes": True}

    def model_post_init(self, __context) -> None:
        if self.total_tests > 0:
            self.pass_rate = (self.passed_tests / self.total_tests) * 100


class WorkflowExecuteRequest(BaseModel):
    """Request for standalone workflow execution."""

    message: str = Field(description="Input message for the workflow")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    timeout_seconds: int = Field(default=60, ge=1, le=300, description="Execution timeout")
    dry_run: bool = Field(default=False, description="If true, validate but don't execute")


class WorkflowExecuteResponse(BaseModel):
    """Response from standalone workflow execution."""

    workflow_id: str
    response: str
    execution_time_ms: int
    agents_called: list[str] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
    execution_trace: list[dict[str, Any]] = Field(default_factory=list)
    success: bool = True
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestRunRequest(BaseModel):
    """Request to run tests for a workflow."""

    workflow_id: str | None = Field(default=None, description="Workflow to test (null = all)")
    test_case_ids: list[UUID] | None = Field(
        default=None, description="Specific test cases (null = all enabled)"
    )
    name: str | None = Field(default=None, description="Name for this test run")
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowValidationResponse(BaseModel):
    """Response from workflow configuration validation."""

    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
