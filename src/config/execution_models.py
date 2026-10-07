"""Execution configuration for async worker pools and resource limits."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ExecutionMode(StrEnum):
    """Execution mode for workflows."""

    SYNC = "sync"
    ASYNC = "async"


class BackoffStrategy(StrEnum):
    """Backoff strategy for retries."""

    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    CONSTANT = "constant"


class RetryConfig(BaseModel):
    """Configuration for retry behavior."""

    max_retries: int = Field(default=3, ge=0, description="Maximum number of retry attempts")
    backoff_factor: float = Field(
        default=2.0, ge=1.0, description="Backoff multiplier between retries"
    )
    backoff_strategy: BackoffStrategy = Field(
        default=BackoffStrategy.EXPONENTIAL, description="Backoff strategy"
    )
    retry_on: list[str] = Field(
        default_factory=lambda: ["timeout", "rate_limit", "temporary_failure"],
        description="Error types that should trigger retry",
    )
    dont_retry_on: list[str] = Field(
        default_factory=lambda: ["validation_error", "authentication_error"],
        description="Error types that should not trigger retry",
    )


class ResourceLimits(BaseModel):
    """Resource limits for workflow execution."""

    max_concurrent_executions: int = Field(
        default=10, ge=1, description="Maximum concurrent workflow executions"
    )
    max_execution_time: float = Field(
        default=300.0, gt=0, description="Maximum execution time in seconds"
    )
    max_agent_calls: int = Field(
        default=100, ge=1, description="Maximum number of agent calls per workflow"
    )
    max_context_size: int = Field(
        default=100000, ge=1000, description="Maximum context size in characters"
    )


class ExecutionConfig(BaseModel):
    """Configuration for the execution engine."""

    max_workers: int = Field(default=10, ge=1, description="Maximum number of worker tasks")
    queue_size: int = Field(default=100, ge=1, description="Size of the task queue")
    default_timeout: float = Field(
        default=300.0, gt=0, description="Default timeout for agent execution in seconds"
    )
    enable_parallel: bool = Field(
        default=True, description="Enable parallel execution of independent branches"
    )
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.ASYNC, description="Execution mode (sync or async)"
    )
    retry_strategy: RetryConfig = Field(
        default_factory=RetryConfig, description="Retry configuration"
    )
    resource_limits: ResourceLimits = Field(
        default_factory=ResourceLimits, description="Resource limits"
    )
