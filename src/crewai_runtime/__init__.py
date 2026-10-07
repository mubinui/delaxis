"""CrewAI runtime adapter for Delaxis."""

# CrewAI decides between Redis and file locks from REDIS_URL when it is first
# imported, so an unreachable Redis has to be ruled out before that happens.
from src.infrastructure.redis_guard import ensure_redis_or_disable

ensure_redis_or_disable()

from src.crewai_runtime.runtime import CrewAIRuntimeResult, CrewAIWorkflowRuntime  # noqa: E402

__all__ = ["CrewAIRuntimeResult", "CrewAIWorkflowRuntime"]
