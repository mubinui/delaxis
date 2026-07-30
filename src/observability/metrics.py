"""Prometheus metrics for Delaxis."""

from typing import Optional

from prometheus_client import (
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
)

# HTTP Request Metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "endpoint"],
)

# Agent Conversation Metrics
agent_conversations_total = Counter(
    "agent_conversations_total",
    "Total agent conversations",
    ["pattern", "workflow_id"],
)

agent_conversation_duration_seconds = Histogram(
    "agent_conversation_duration_seconds",
    "Agent conversation duration in seconds",
    ["pattern"],
)

agent_turns_total = Counter(
    "agent_turns_total",
    "Total conversation turns",
    ["agent_id"],
)

agent_errors_total = Counter(
    "agent_errors_total",
    "Total agent errors",
    ["agent_id", "error_type"],
)

# LLM Metrics
llm_calls_total = Counter(
    "llm_calls_total",
    "Total LLM API calls",
    ["provider", "model"],
)

llm_tokens_total = Counter(
    "llm_tokens_total",
    "Total tokens used",
    ["provider", "model", "type"],
)

llm_cost_total = Counter(
    "llm_cost_total",
    "Total LLM cost in USD",
    ["provider", "model"],
)

# Infrastructure Metrics
cache_hits_total = Counter(
    "cache_hits_total",
    "Total cache hits",
    ["cache_type"],
)

cache_misses_total = Counter(
    "cache_misses_total",
    "Total cache misses",
    ["cache_type"],
)

queue_depth = Gauge(
    "queue_depth",
    "Message queue depth",
    ["queue_name"],
)

# Configuration Metrics
config_reload_total = Counter(
    "config_reload_total",
    "Total configuration reloads",
    ["config_type"],
)

provider_client_created_total = Counter(
    "provider_client_created_total",
    "Total provider clients created",
    ["provider_id", "client_type"],
)

# Resource Management Metrics
workflow_executions_active = Gauge(
    "workflow_executions_active",
    "Number of currently active workflow executions",
    ["workflow_id"],
)

workflow_executions_queued = Gauge(
    "workflow_executions_queued",
    "Number of queued workflow executions waiting for resources",
    ["workflow_id"],
)

workflow_resource_limit_rejections_total = Counter(
    "workflow_resource_limit_rejections_total",
    "Total workflow executions rejected due to resource limits",
    ["workflow_id"],
)

workflow_timeouts_total = Counter(
    "workflow_timeouts_total",
    "Total workflow executions that timed out",
    ["workflow_id"],
)

agent_timeouts_total = Counter(
    "agent_timeouts_total",
    "Total agent executions that timed out",
    ["agent_id"],
)

worker_pool_utilization = Gauge(
    "worker_pool_utilization",
    "Worker pool utilization (active workers / max workers)",
)

execution_time_seconds = Histogram(
    "execution_time_seconds",
    "Execution time in seconds",
    ["execution_type", "workflow_id"],
)


def get_metrics_registry():
    """Get the Prometheus metrics registry."""
    return REGISTRY


def track_http_request(
    method: str,
    endpoint: str,
    status: int,
    duration: float,
) -> None:
    """Track HTTP request metrics."""
    http_requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
    http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)


def track_agent_conversation(
    pattern: str,
    workflow_id: str,
    duration: float,
) -> None:
    """Track agent conversation metrics."""
    agent_conversations_total.labels(pattern=pattern, workflow_id=workflow_id).inc()
    agent_conversation_duration_seconds.labels(pattern=pattern).observe(duration)


def track_agent_turn(agent_id: str) -> None:
    """Track agent conversation turn."""
    agent_turns_total.labels(agent_id=agent_id).inc()


def track_agent_error(agent_id: str, error_type: str) -> None:
    """Track agent error."""
    agent_errors_total.labels(agent_id=agent_id, error_type=error_type).inc()


def track_llm_call(provider: str, model: str) -> None:
    """Track LLM API call."""
    llm_calls_total.labels(provider=provider, model=model).inc()


def track_llm_tokens(
    provider: str,
    model: str,
    token_type: str,
    count: int,
) -> None:
    """Track LLM token usage."""
    llm_tokens_total.labels(provider=provider, model=model, type=token_type).add(count)


def track_llm_cost(provider: str, model: str, cost: float) -> None:
    """Track LLM cost in USD."""
    llm_cost_total.labels(provider=provider, model=model).add(cost)


def track_cache_hit(cache_type: str) -> None:
    """Track cache hit."""
    cache_hits_total.labels(cache_type=cache_type).inc()


def track_cache_miss(cache_type: str) -> None:
    """Track cache miss."""
    cache_misses_total.labels(cache_type=cache_type).inc()


def track_queue_depth(queue_name: str, depth: int) -> None:
    """Track message queue depth."""
    queue_depth.labels(queue_name=queue_name).set(depth)


def track_workflow_execution_active(workflow_id: str, count: int) -> None:
    """Track active workflow executions."""
    workflow_executions_active.labels(workflow_id=workflow_id).set(count)


def track_workflow_execution_queued(workflow_id: str, count: int) -> None:
    """Track queued workflow executions."""
    workflow_executions_queued.labels(workflow_id=workflow_id).set(count)


def track_workflow_resource_limit_rejection(workflow_id: str) -> None:
    """Track workflow rejection due to resource limits."""
    workflow_resource_limit_rejections_total.labels(workflow_id=workflow_id).inc()


def track_workflow_timeout(workflow_id: str) -> None:
    """Track workflow timeout."""
    workflow_timeouts_total.labels(workflow_id=workflow_id).inc()


def track_agent_timeout(agent_id: str) -> None:
    """Track agent timeout."""
    agent_timeouts_total.labels(agent_id=agent_id).inc()


def track_worker_pool_utilization(utilization: float) -> None:
    """Track worker pool utilization (0.0 to 1.0)."""
    worker_pool_utilization.set(utilization)


def track_execution_time(execution_type: str, workflow_id: str, duration: float) -> None:
    """Track execution time."""
    execution_time_seconds.labels(execution_type=execution_type, workflow_id=workflow_id).observe(duration)
