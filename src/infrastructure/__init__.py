"""Infrastructure layer for external integrations."""

# Import cache modules (always available)
from src.infrastructure.cache import RedisCache
from src.infrastructure.cache_manager import CacheManager, get_cache_manager
from src.infrastructure.embedding_cache import EmbeddingCache
from src.infrastructure.llm_cache import (
    CrewAICacheConfig,
    LLMCacheMonitor,
    get_llm_cache_monitor,
)
from src.infrastructure.session_cache import SessionCache

# Import message broker modules (requires aio_pika)
try:
    from src.infrastructure.async_processor import AsyncAgentTaskProcessor
    from src.infrastructure.message_broker import (
        AgentTask,
        AgentTaskConsumer,
        AgentTaskPublisher,
        DeadLetterQueueHandler,
        MessageBroker,
        RabbitMQConnectionPool,
    )

    _MESSAGE_BROKER_AVAILABLE = True
except ImportError:
    _MESSAGE_BROKER_AVAILABLE = False
    AgentTask = None
    AgentTaskConsumer = None
    AgentTaskPublisher = None
    DeadLetterQueueHandler = None
    MessageBroker = None
    RabbitMQConnectionPool = None
    AsyncAgentTaskProcessor = None

__all__ = [
    # Cache modules
    "RedisCache",
    "SessionCache",
    "EmbeddingCache",
    "LLMCacheMonitor",
    "CrewAICacheConfig",
    "CacheManager",
    "get_llm_cache_monitor",
    "get_cache_manager",
    # Message broker modules (may be None if not available)
    "AgentTask",
    "AgentTaskConsumer",
    "AgentTaskPublisher",
    "DeadLetterQueueHandler",
    "MessageBroker",
    "RabbitMQConnectionPool",
    "AsyncAgentTaskProcessor",
]
