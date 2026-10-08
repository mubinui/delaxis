"""Structured logging configuration."""

import logging
import sys
from typing import Any
from uuid import UUID

import structlog
import structlog.typing

from src.config import get_settings


def configure_logging() -> None:
    """
    Configure structured logging for the application.

    This configures structlog with appropriate processors for
    structured logging with correlation IDs and context.

    Requirements: 6.1, 6.2, 12.1, 12.2
    """
    settings = get_settings()

    # Configure structlog processors
    processors: list[structlog.typing.Processor] = [
        # Merge context variables (correlation IDs, etc.)
        structlog.contextvars.merge_contextvars,
        # Add log level
        structlog.processors.add_log_level,
        # Add stack info for errors
        structlog.processors.StackInfoRenderer(),
        # Set exception info
        structlog.dev.set_exc_info,
        # Add timestamp
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # Add appropriate renderer based on environment
    if settings.app.log_level == "DEBUG" or settings.app.environment == "development":
        # Use console renderer for development
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        # Use JSON renderer for production
        processors.append(structlog.processors.JSONRenderer())

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.app.log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """
    Get a logger instance with the given name.

    Args:
        name: Logger name (typically __name__)

    Returns:
        Configured structlog logger
    """
    logger: structlog.BoundLogger = structlog.get_logger(name)
    return logger


def bind_correlation_ids(
    request_id: str | None = None,
    session_id: UUID | None = None,
    user_id: str | UUID | None = None,
    workflow_id: str | None = None,
    agent_id: str | None = None,
    node_id: str | None = None,
) -> None:
    """
    Bind correlation IDs to the logging context.

    This adds correlation IDs to all subsequent log messages
    in the current context.

    Args:
        request_id: HTTP request ID
        session_id: Conversation session ID
        user_id: User identifier
        workflow_id: Workflow identifier
        agent_id: Agent identifier
        node_id: Node identifier in workflow graph

    Requirements: 6.1, 6.2, 9.1, 12.1, 12.2
    """
    context = {}

    if request_id:
        context["request_id"] = request_id
    if session_id:
        context["session_id"] = str(session_id)
    if user_id:
        context["user_id"] = str(user_id)
    if workflow_id:
        context["workflow_id"] = workflow_id
    if agent_id:
        context["agent_id"] = agent_id
    if node_id:
        context["node_id"] = node_id

    if context:
        structlog.contextvars.bind_contextvars(**context)


def clear_correlation_ids() -> None:
    """
    Clear correlation IDs from the logging context.

    This should be called at the end of a request or operation
    to prevent context leakage.

    Requirements: 6.1, 6.2
    """
    structlog.contextvars.clear_contextvars()


def log_agent_decision(
    logger: structlog.BoundLogger,
    agent_id: str,
    decision: str,
    reasoning: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """
    Log an agent decision with structured context.

    Args:
        logger: Logger instance
        agent_id: Agent identifier
        decision: Decision made by the agent
        reasoning: Reasoning behind the decision
        context: Additional context

    Requirements: 6.1, 6.2, 12.1, 12.2
    """
    logger.info(
        "agent_decision",
        agent_id=agent_id,
        decision=decision,
        reasoning=reasoning,
        context=context or {},
    )


def log_tool_call(
    logger: structlog.BoundLogger,
    agent_id: str,
    tool_name: str,
    tool_args: dict[str, Any],
    result: str | None = None,
    error: str | None = None,
) -> None:
    """
    Log a tool call with structured context.

    Args:
        logger: Logger instance
        agent_id: Agent identifier
        tool_name: Name of the tool
        tool_args: Tool arguments
        result: Tool execution result
        error: Error message if tool failed

    Requirements: 6.1, 6.2, 12.1, 12.2
    """
    log_data = {
        "agent_id": agent_id,
        "tool_name": tool_name,
        "tool_args": tool_args,
    }

    if result:
        log_data["result"] = result
    if error:
        log_data["error"] = error

    if error:
        logger.error("tool_call_failed", **log_data)
    else:
        logger.info("tool_call_success", **log_data)


def log_agent_execution_start(
    logger: structlog.BoundLogger,
    agent_id: str,
    node_id: str,
    workflow_id: str,
    input_message: str | None = None,
) -> None:
    """
    Log the start of agent execution.

    Args:
        logger: Logger instance
        agent_id: Agent identifier
        node_id: Node identifier in workflow
        workflow_id: Workflow identifier
        input_message: Input message to agent

    Requirements: 9.1, 9.2
    """
    logger.info(
        "agent_execution_start",
        agent_id=agent_id,
        node_id=node_id,
        workflow_id=workflow_id,
        input_message=input_message,
    )


def log_agent_execution_end(
    logger: structlog.BoundLogger,
    agent_id: str,
    node_id: str,
    workflow_id: str,
    status: str,
    execution_time: float,
    output: str | None = None,
    error: str | None = None,
) -> None:
    """
    Log the end of agent execution.

    Args:
        logger: Logger instance
        agent_id: Agent identifier
        node_id: Node identifier in workflow
        workflow_id: Workflow identifier
        status: Execution status (success, failure, timeout)
        execution_time: Execution time in seconds
        output: Agent output
        error: Error message if failed

    Requirements: 9.1, 9.2, 9.4
    """
    log_data = {
        "agent_id": agent_id,
        "node_id": node_id,
        "workflow_id": workflow_id,
        "status": status,
        "execution_time_seconds": execution_time,
    }

    if output:
        log_data["output"] = output
    if error:
        log_data["error"] = error

    if status == "success":
        logger.info("agent_execution_end", **log_data)
    else:
        logger.error("agent_execution_end", **log_data)


def log_workflow_execution_start(
    logger: structlog.BoundLogger,
    workflow_id: str,
    session_id: str,
    message: str,
) -> None:
    """
    Log the start of workflow execution.

    Args:
        logger: Logger instance
        workflow_id: Workflow identifier
        session_id: Session identifier
        message: Initial message

    Requirements: 9.1, 9.2
    """
    logger.info(
        "workflow_execution_start",
        workflow_id=workflow_id,
        session_id=session_id,
        message=message,
    )


def log_workflow_execution_end(
    logger: structlog.BoundLogger,
    workflow_id: str,
    session_id: str,
    status: str,
    execution_time: float,
    agent_count: int,
    final_response: str | None = None,
) -> None:
    """
    Log the end of workflow execution.

    Args:
        logger: Logger instance
        workflow_id: Workflow identifier
        session_id: Session identifier
        status: Execution status
        execution_time: Total execution time in seconds
        agent_count: Number of agents executed
        final_response: Final response from workflow

    Requirements: 9.1, 9.2, 9.4
    """
    log_data = {
        "workflow_id": workflow_id,
        "session_id": session_id,
        "status": status,
        "execution_time_seconds": execution_time,
        "agent_count": agent_count,
    }

    if final_response:
        log_data["final_response"] = final_response

    if status == "success":
        logger.info("workflow_execution_end", **log_data)
    else:
        logger.error("workflow_execution_end", **log_data)


def log_llm_call(
    logger: structlog.BoundLogger,
    agent_id: str,
    provider: str,
    model: str,
    prompt: str | None = None,
    response: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    execution_time: float | None = None,
    cache_hit: bool = False,
) -> None:
    """
    Log an LLM API call with optional prompt/response in debug mode.

    Args:
        logger: Logger instance
        agent_id: Agent identifier
        provider: LLM provider name
        model: Model identifier
        prompt: LLM prompt (logged only in debug mode)
        response: LLM response (logged only in debug mode)
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
        execution_time: Execution time in seconds
        cache_hit: Whether response was from cache

    Requirements: 9.3, 9.4
    """
    from src.config import get_settings

    settings = get_settings()

    log_data = {
        "agent_id": agent_id,
        "provider": provider,
        "model": model,
        "cache_hit": cache_hit,
    }

    if prompt_tokens is not None:
        log_data["prompt_tokens"] = prompt_tokens
    if completion_tokens is not None:
        log_data["completion_tokens"] = completion_tokens
    if execution_time is not None:
        log_data["execution_time_seconds"] = execution_time

    # Only log prompts and responses in debug mode
    if settings.telemetry.debug_mode or settings.telemetry.log_llm_prompts:
        if prompt:
            log_data["prompt"] = prompt

    if settings.telemetry.debug_mode or settings.telemetry.log_llm_responses:
        if response:
            log_data["response"] = response

    logger.info("llm_call", **log_data)


def log_error_context(
    logger: structlog.BoundLogger,
    error: Exception,
    agent_id: str | None = None,
    node_id: str | None = None,
    workflow_id: str | None = None,
    session_id: str | None = None,
    agent_state: dict[str, Any] | None = None,
    conversation_history: list[Any] | None = None,
    retry_count: int = 0,
) -> None:
    """
    Log error with full context for debugging.

    Args:
        logger: Logger instance
        error: Exception that occurred
        agent_id: Agent identifier
        node_id: Node identifier
        workflow_id: Workflow identifier
        session_id: Session identifier
        agent_state: Current agent state
        conversation_history: Conversation history
        retry_count: Number of retries attempted

    Requirements: 9.3, 9.5
    """
    from src.config import get_settings

    settings = get_settings()

    log_data = {
        "error_type": type(error).__name__,
        "error_message": str(error),
        "retry_count": retry_count,
    }

    if agent_id:
        log_data["agent_id"] = agent_id
    if node_id:
        log_data["node_id"] = node_id
    if workflow_id:
        log_data["workflow_id"] = workflow_id
    if session_id:
        log_data["session_id"] = session_id

    # Include agent state and conversation history in debug mode
    if settings.telemetry.debug_mode or settings.telemetry.log_agent_state:
        if agent_state:
            log_data["agent_state"] = agent_state
        if conversation_history:
            # Limit conversation history to last 5 messages to avoid log bloat
            log_data["conversation_history"] = conversation_history[-5:]

    logger.error("error_with_context", **log_data, exc_info=True)
