"""OpenTelemetry tracing configuration and utilities."""

from typing import Any, Callable, Optional

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

from src.config.settings import get_settings

logger = structlog.get_logger(__name__)

# Global tracer instance
_tracer: Optional[trace.Tracer] = None


def configure_tracing() -> None:
    """
    Configure OpenTelemetry tracing for the application.
    
    This sets up the tracer provider with appropriate exporters
    based on the environment configuration.
    
    Requirements: 14.3, 14.4
    """
    global _tracer
    
    settings = get_settings()
    
    # Create resource with service information
    resource = Resource.create(
        {
            "service.name": "delaxis",
            "service.version": "0.1.0",
            "deployment.environment": settings.app.environment,
        }
    )
    
    # Create tracer provider
    provider = TracerProvider(resource=resource)
    
    # Add console exporter for development
    if settings.app.environment == "development":
        console_exporter = ConsoleSpanExporter()
        provider.add_span_processor(BatchSpanProcessor(console_exporter))
        logger.info("tracing_configured", exporter="console")
    
    # Add OTLP exporter if endpoint is configured
    otlp_endpoint = settings.app.otlp_endpoint if hasattr(settings.app, "otlp_endpoint") else None
    if otlp_endpoint:
        otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
        logger.info("tracing_configured", exporter="otlp", endpoint=otlp_endpoint)
    
    # Set the tracer provider
    trace.set_tracer_provider(provider)
    
    # Get tracer instance
    _tracer = trace.get_tracer(__name__)
    
    logger.info("opentelemetry_tracing_initialized")


def instrument_fastapi(app: Any) -> None:
    """
    Instrument FastAPI application with OpenTelemetry.
    
    Args:
        app: FastAPI application instance
        
    Requirements: 14.3, 14.4
    """
    FastAPIInstrumentor.instrument_app(app)
    logger.info("fastapi_instrumented_with_opentelemetry")


def get_tracer() -> Optional[trace.Tracer]:
    """
    Get the OpenTelemetry tracer instance.
    
    Returns:
        Tracer instance or None if tracing not configured
    """
    return _tracer


def is_tracing_enabled() -> bool:
    """
    Check if tracing is enabled.
    
    Returns:
        True if tracing is configured, False otherwise
    """
    return _tracer is not None


def trace_agent_conversation(
    pattern: str,
    workflow_id: str,
    session_id: str,
) -> trace.Span:
    """
    Create a span for an agent conversation.
    
    Args:
        pattern: Conversation pattern (two_agent, sequential, group_chat, nested)
        workflow_id: Workflow identifier
        session_id: Session identifier
        
    Returns:
        Span context manager
        
    Requirements: 14.3, 14.4
    """
    tracer = get_tracer()
    span = tracer.start_span(
        "agent.conversation",
        attributes={
            "conversation.pattern": pattern,
            "conversation.workflow_id": workflow_id,
            "conversation.session_id": session_id,
        },
    )
    return span


def trace_workflow_execution(
    workflow_id: str,
    session_id: str,
    topology_type: Optional[str] = None,
) -> Optional[trace.Span]:
    """
    Create a span for workflow execution.
    
    Args:
        workflow_id: Workflow identifier
        session_id: Session identifier
        topology_type: Type of topology (single, sequential, tree, graph)
        
    Returns:
        Span context manager or None if tracing not configured
        
    Requirements: 9.2
    """
    tracer = get_tracer()
    if tracer is None:
        return None
    
    attributes = {
        "workflow.id": workflow_id,
        "workflow.session_id": session_id,
    }
    
    if topology_type:
        attributes["workflow.topology_type"] = topology_type
    
    span = tracer.start_span("workflow.execution", attributes=attributes)
    return span


def trace_agent_execution(
    agent_id: str,
    node_id: str,
    workflow_id: str,
) -> Optional[trace.Span]:
    """
    Create a span for agent execution within a workflow.
    
    Args:
        agent_id: Agent identifier
        node_id: Node identifier in workflow
        workflow_id: Workflow identifier
        
    Returns:
        Span context manager or None if tracing not configured
        
    Requirements: 9.2
    """
    tracer = get_tracer()
    if tracer is None:
        return None
    
    span = tracer.start_span(
        "agent.execution",
        attributes={
            "agent.id": agent_id,
            "agent.node_id": node_id,
            "agent.workflow_id": workflow_id,
        },
    )
    return span


def trace_execution_stage(
    stage_number: int,
    node_count: int,
    workflow_id: str,
) -> trace.Span:
    """
    Create a span for an execution stage in a workflow.
    
    Args:
        stage_number: Stage number in execution plan
        node_count: Number of nodes in this stage
        workflow_id: Workflow identifier
        
    Returns:
        Span context manager
        
    Requirements: 9.2
    """
    tracer = get_tracer()
    span = tracer.start_span(
        "workflow.stage",
        attributes={
            "stage.number": stage_number,
            "stage.node_count": node_count,
            "stage.workflow_id": workflow_id,
        },
    )
    return span


def trace_llm_call(
    provider: str,
    model: str,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
) -> trace.Span:
    """
    Create a span for an LLM API call.
    
    Args:
        provider: LLM provider name
        model: Model identifier
        prompt_tokens: Number of prompt tokens
        completion_tokens: Number of completion tokens
        
    Returns:
        Span context manager
        
    Requirements: 14.3, 14.4
    """
    tracer = get_tracer()
    attributes = {
        "llm.provider": provider,
        "llm.model": model,
    }
    
    if prompt_tokens is not None:
        attributes["llm.prompt_tokens"] = prompt_tokens
    if completion_tokens is not None:
        attributes["llm.completion_tokens"] = completion_tokens
    
    span = tracer.start_span("llm.call", attributes=attributes)
    return span


def trace_tool_execution(
    tool_name: str,
    agent_id: str,
) -> trace.Span:
    """
    Create a span for a tool execution.
    
    Args:
        tool_name: Name of the tool being executed
        agent_id: Agent executing the tool
        
    Returns:
        Span context manager
        
    Requirements: 14.3, 14.4
    """
    tracer = get_tracer()
    span = tracer.start_span(
        "tool.execution",
        attributes={
            "tool.name": tool_name,
            "tool.agent_id": agent_id,
        },
    )
    return span


def trace_database_query(
    operation: str,
    table: Optional[str] = None,
) -> trace.Span:
    """
    Create a span for a database query.
    
    Args:
        operation: Database operation (select, insert, update, delete)
        table: Table name
        
    Returns:
        Span context manager
        
    Requirements: 14.3, 14.4
    """
    tracer = get_tracer()
    attributes = {
        "db.operation": operation,
    }
    
    if table:
        attributes["db.table"] = table
    
    span = tracer.start_span("db.query", attributes=attributes)
    return span


def trace_cache_operation(
    operation: str,
    cache_type: str,
    key: Optional[str] = None,
) -> trace.Span:
    """
    Create a span for a cache operation.
    
    Args:
        operation: Cache operation (get, set, delete)
        cache_type: Type of cache (session, embedding, llm)
        key: Cache key
        
    Returns:
        Span context manager
        
    Requirements: 14.3, 14.4
    """
    tracer = get_tracer()
    attributes = {
        "cache.operation": operation,
        "cache.type": cache_type,
    }
    
    if key:
        attributes["cache.key"] = key
    
    span = tracer.start_span("cache.operation", attributes=attributes)
    return span


def add_span_event(span: Optional[trace.Span], name: str, attributes: Optional[dict] = None) -> None:
    """
    Add an event to a span.
    
    Args:
        span: Span to add event to (can be None if tracing not configured)
        name: Event name
        attributes: Event attributes
        
    Requirements: 14.3, 14.4
    """
    if span is None:
        return
    
    if attributes:
        span.add_event(name, attributes=attributes)
    else:
        span.add_event(name)


def set_span_error(span: Optional[trace.Span], error: Exception) -> None:
    """
    Mark a span as having an error.
    
    Args:
        span: Span to mark as error (can be None if tracing not configured)
        error: Exception that occurred
        
    Requirements: 14.3, 14.4
    """
    if span is None:
        return
    
    span.set_status(trace.Status(trace.StatusCode.ERROR, str(error)))
    span.record_exception(error)
