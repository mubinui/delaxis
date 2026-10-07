"""RabbitMQ message broker integration for async agent processing."""

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import aio_pika
from aio_pika import Channel, Connection, ExchangeType, Message
from aio_pika.abc import AbstractIncomingMessage
from aio_pika.pool import Pool

logger = logging.getLogger(__name__)


@dataclass
class AgentTask:
    """Represents a task for an agent to process."""

    task_id: UUID
    session_id: UUID
    agent_id: str
    message: str
    context: dict[str, Any]
    created_at: datetime
    priority: int = 0
    retry_count: int = 0
    max_retries: int = 3

    def to_json(self) -> str:
        """Serialize task to JSON."""
        data = asdict(self)
        # Convert UUID and datetime to strings
        data["task_id"] = str(data["task_id"])
        data["session_id"] = str(data["session_id"])
        data["created_at"] = data["created_at"].isoformat()
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> "AgentTask":
        """Deserialize task from JSON."""
        data = json.loads(json_str)
        # Convert strings back to UUID and datetime
        data["task_id"] = UUID(data["task_id"])
        data["session_id"] = UUID(data["session_id"])
        data["created_at"] = datetime.fromisoformat(data["created_at"])
        return cls(**data)


class RabbitMQConnectionPool:
    """
    Connection pool for RabbitMQ with automatic reconnection.

    This class manages a pool of RabbitMQ connections and channels,
    providing resilience through automatic reconnection on failures.

    Requirements: 8.1, 8.2
    """

    def __init__(
        self,
        url: str,
        max_connections: int = 10,
        max_channels: int = 100,
    ):
        """
        Initialize the connection pool.

        Args:
            url: RabbitMQ connection URL (amqp://user:pass@host:port/)
            max_connections: Maximum number of connections in the pool
            max_channels: Maximum number of channels per connection
        """
        self.url = url
        self.max_connections = max_connections
        self.max_channels = max_channels
        self._connection_pool: Pool[Connection] | None = None
        self._channel_pool: Pool[Channel] | None = None
        self._is_closed = False

    async def _get_connection(self) -> Connection:
        """Create a new RabbitMQ connection with reconnection support."""
        connection = await aio_pika.connect_robust(
            self.url,
            reconnect_interval=5.0,
            fail_fast=False,
        )
        logger.info("Established RabbitMQ connection")
        return connection

    async def _get_channel(self) -> Channel:
        """Get a channel from a connection in the pool."""
        if self._connection_pool is None:
            raise RuntimeError("Connection pool not initialized")

        async with self._connection_pool.acquire() as connection:
            channel = await connection.channel()
            await channel.set_qos(prefetch_count=10)
            return channel

    async def initialize(self) -> None:
        """Initialize the connection and channel pools."""
        if self._connection_pool is not None:
            logger.warning("Connection pool already initialized")
            return

        logger.info(
            f"Initializing RabbitMQ connection pool (max_connections={self.max_connections})"
        )

        # Create connection pool
        self._connection_pool = Pool(
            self._get_connection,
            max_size=self.max_connections,
        )

        # Create channel pool
        self._channel_pool = Pool(
            self._get_channel,
            max_size=self.max_channels,
        )

        logger.info("RabbitMQ connection pool initialized successfully")

    async def get_channel(self) -> Channel:
        """
        Get a channel from the pool.

        Returns:
            A channel from the pool

        Raises:
            RuntimeError: If the pool is not initialized
        """
        if self._channel_pool is None:
            raise RuntimeError("Channel pool not initialized. Call initialize() first.")

        return await self._channel_pool.acquire()

    async def close(self) -> None:
        """Close all connections and channels in the pool."""
        if self._is_closed:
            return

        logger.info("Closing RabbitMQ connection pool")
        self._is_closed = True

        if self._channel_pool is not None:
            await self._channel_pool.close()
            self._channel_pool = None

        if self._connection_pool is not None:
            await self._connection_pool.close()
            self._connection_pool = None

        logger.info("RabbitMQ connection pool closed")

    async def __aenter__(self) -> "RabbitMQConnectionPool":
        """Context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        await self.close()


class MessageBroker:
    """
    Base message broker class for RabbitMQ operations.

    Provides common functionality for publishers and consumers including
    queue declaration, exchange setup, and dead letter queue configuration.

    Requirements: 8.1, 8.2
    """

    def __init__(
        self,
        connection_pool: RabbitMQConnectionPool,
        exchange_name: str = "agent_tasks",
        dlx_exchange_name: str = "agent_tasks_dlx",
    ):
        """
        Initialize the message broker.

        Args:
            connection_pool: RabbitMQ connection pool
            exchange_name: Name of the main exchange
            dlx_exchange_name: Name of the dead letter exchange
        """
        self.connection_pool = connection_pool
        self.exchange_name = exchange_name
        self.dlx_exchange_name = dlx_exchange_name

    async def _declare_exchange(
        self,
        channel: Channel,
        exchange_name: str,
        exchange_type: ExchangeType = ExchangeType.TOPIC,
    ) -> aio_pika.Exchange:
        """Declare an exchange."""
        exchange = await channel.declare_exchange(
            exchange_name,
            exchange_type,
            durable=True,
        )
        return exchange

    async def _declare_queue(
        self,
        channel: Channel,
        queue_name: str,
        dlx_exchange: str | None = None,
        message_ttl: int | None = None,
    ) -> aio_pika.Queue:
        """
        Declare a queue with optional dead letter exchange.

        Args:
            channel: RabbitMQ channel
            queue_name: Name of the queue
            dlx_exchange: Dead letter exchange name (optional)
            message_ttl: Message TTL in milliseconds (optional)

        Returns:
            Declared queue
        """
        arguments: dict[str, Any] = {}

        if dlx_exchange:
            arguments["x-dead-letter-exchange"] = dlx_exchange
            arguments["x-dead-letter-routing-key"] = f"dlq.{queue_name}"

        if message_ttl:
            arguments["x-message-ttl"] = message_ttl

        queue = await channel.declare_queue(
            queue_name,
            durable=True,
            arguments=arguments if arguments else None,
        )

        return queue

    async def setup_infrastructure(self, channel: Channel) -> None:
        """
        Setup exchanges and queues infrastructure.

        Args:
            channel: RabbitMQ channel
        """
        # Declare main exchange
        await self._declare_exchange(channel, self.exchange_name)

        # Declare dead letter exchange
        await self._declare_exchange(channel, self.dlx_exchange_name)

        logger.info("Message broker infrastructure setup complete")


class AgentTaskPublisher(MessageBroker):
    """
    Publisher for agent tasks to RabbitMQ queues.

    This class handles publishing agent tasks to appropriate queues with
    support for task priority and message persistence.

    Requirements: 8.1, 8.2
    """

    def __init__(
        self,
        connection_pool: RabbitMQConnectionPool,
        exchange_name: str = "agent_tasks",
        dlx_exchange_name: str = "agent_tasks_dlx",
    ):
        """
        Initialize the task publisher.

        Args:
            connection_pool: RabbitMQ connection pool
            exchange_name: Name of the main exchange
            dlx_exchange_name: Name of the dead letter exchange
        """
        super().__init__(connection_pool, exchange_name, dlx_exchange_name)
        self._channel: Channel | None = None
        self._exchange: aio_pika.Exchange | None = None

    async def initialize(self) -> None:
        """Initialize the publisher by setting up infrastructure."""
        logger.info("Initializing AgentTaskPublisher")

        # Get a channel from the pool
        self._channel = await self.connection_pool.get_channel()

        # Setup infrastructure
        await self.setup_infrastructure(self._channel)

        # Get the exchange reference
        self._exchange = await self._channel.get_exchange(self.exchange_name)

        logger.info("AgentTaskPublisher initialized successfully")

    async def publish_task(
        self,
        task: AgentTask,
        routing_key: str | None = None,
    ) -> None:
        """
        Publish an agent task to the queue.

        Args:
            task: The agent task to publish
            routing_key: Optional routing key (defaults to agent.tasks.{agent_id})

        Raises:
            RuntimeError: If publisher is not initialized

        Requirements: 8.1, 8.2
        """
        if self._exchange is None:
            raise RuntimeError("Publisher not initialized. Call initialize() first.")

        # Default routing key based on agent_id
        if routing_key is None:
            routing_key = f"agent.tasks.{task.agent_id}"

        # Serialize task to JSON
        message_body = task.to_json()

        # Create message with persistence and priority
        message = Message(
            body=message_body.encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,  # Persist messages to disk
            priority=task.priority,
            content_type="application/json",
            message_id=str(task.task_id),
            timestamp=task.created_at,
            headers={
                "session_id": str(task.session_id),
                "agent_id": task.agent_id,
                "retry_count": task.retry_count,
            },
        )

        # Publish the message
        await self._exchange.publish(
            message,
            routing_key=routing_key,
        )

        logger.info(
            f"Published task {task.task_id} for agent {task.agent_id} "
            f"(priority={task.priority}, routing_key={routing_key})"
        )

    async def publish_result(
        self,
        session_id: UUID,
        result: dict[str, Any],
    ) -> None:
        """
        Publish a result to the session's result queue.

        Args:
            session_id: Session ID for routing the result
            result: Result data to publish
        """
        if self._exchange is None:
            raise RuntimeError("Publisher not initialized. Call initialize() first.")

        routing_key = f"agent.results.{session_id}"

        # Create message
        message = Message(
            body=json.dumps(result).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
            timestamp=datetime.now(UTC),
            headers={
                "session_id": str(session_id),
            },
        )

        # Publish the message
        await self._exchange.publish(
            message,
            routing_key=routing_key,
        )

        logger.info(f"Published result for session {session_id}")

    async def close(self) -> None:
        """Close the publisher and release resources."""
        if self._channel and not self._channel.is_closed:
            await self._channel.close()
            self._channel = None

        logger.info("AgentTaskPublisher closed")


class AgentTaskConsumer(MessageBroker):
    """
    Consumer for agent tasks from RabbitMQ queues.

    This class handles consuming agent tasks from queues with support for
    concurrent processing and proper acknowledgment handling.

    Requirements: 8.2, 8.3
    """

    def __init__(
        self,
        connection_pool: RabbitMQConnectionPool,
        agent_id: str,
        task_handler: Callable[[AgentTask], Any],
        exchange_name: str = "agent_tasks",
        dlx_exchange_name: str = "agent_tasks_dlx",
        prefetch_count: int = 10,
    ):
        """
        Initialize the task consumer.

        Args:
            connection_pool: RabbitMQ connection pool
            agent_id: ID of the agent this consumer handles tasks for
            task_handler: Async function to handle incoming tasks
            exchange_name: Name of the main exchange
            dlx_exchange_name: Name of the dead letter exchange
            prefetch_count: Number of messages to prefetch for concurrent processing
        """
        super().__init__(connection_pool, exchange_name, dlx_exchange_name)
        self.agent_id = agent_id
        self.task_handler = task_handler
        self.prefetch_count = prefetch_count
        self._channel: Channel | None = None
        self._queue: aio_pika.Queue | None = None
        self._consumer_tag: str | None = None
        self._is_consuming = False

    async def initialize(self) -> None:
        """Initialize the consumer by setting up infrastructure and queues."""
        logger.info(f"Initializing AgentTaskConsumer for agent {self.agent_id}")

        # Get a channel from the pool
        self._channel = await self.connection_pool.get_channel()

        # Set QoS for concurrent processing
        await self._channel.set_qos(prefetch_count=self.prefetch_count)

        # Setup infrastructure
        await self.setup_infrastructure(self._channel)

        # Get exchange reference
        exchange = await self._channel.get_exchange(self.exchange_name)

        # Declare the agent's task queue with DLX
        queue_name = f"agent.tasks.{self.agent_id}"
        self._queue = await self._declare_queue(
            self._channel,
            queue_name,
            dlx_exchange=self.dlx_exchange_name,
        )

        # Bind queue to exchange with routing key
        routing_key = f"agent.tasks.{self.agent_id}"
        await self._queue.bind(exchange, routing_key=routing_key)

        logger.info(
            f"AgentTaskConsumer initialized for agent {self.agent_id} "
            f"(queue={queue_name}, prefetch={self.prefetch_count})"
        )

    async def _process_message(self, message: AbstractIncomingMessage) -> None:
        """
        Process an incoming message.

        Args:
            message: The incoming RabbitMQ message
        """
        async with message.process():
            try:
                # Deserialize the task
                task = AgentTask.from_json(message.body.decode())

                logger.info(
                    f"Processing task {task.task_id} for agent {task.agent_id} "
                    f"(retry_count={task.retry_count})"
                )

                # Call the task handler
                await self.task_handler(task)

                # Message is automatically acknowledged on successful processing
                logger.info(f"Successfully processed task {task.task_id}")

            except Exception as e:
                logger.error(
                    f"Error processing task: {e}",
                    exc_info=True,
                    extra={
                        "message_id": message.message_id,
                        "agent_id": self.agent_id,
                    },
                )
                # Message will be rejected and sent to DLQ
                raise

    async def consume_tasks(self) -> None:
        """
        Start consuming tasks from the queue.

        This method starts consuming messages and will run until stop_consuming()
        is called or an error occurs.

        Requirements: 8.2, 8.3
        """
        if self._queue is None:
            raise RuntimeError("Consumer not initialized. Call initialize() first.")

        if self._is_consuming:
            logger.warning(f"Consumer for agent {self.agent_id} is already consuming")
            return

        logger.info(f"Starting to consume tasks for agent {self.agent_id}")
        self._is_consuming = True

        # Start consuming messages
        self._consumer_tag = await self._queue.consume(
            self._process_message,
            no_ack=False,  # Require explicit acknowledgment
        )

        logger.info(f"Consumer for agent {self.agent_id} is now active")

    async def stop_consuming(self) -> None:
        """Stop consuming tasks from the queue."""
        if not self._is_consuming:
            return

        logger.info(f"Stopping consumer for agent {self.agent_id}")
        self._is_consuming = False

        if self._consumer_tag and self._queue:
            await self._queue.cancel(self._consumer_tag)
            self._consumer_tag = None

        logger.info(f"Consumer for agent {self.agent_id} stopped")

    async def close(self) -> None:
        """Close the consumer and release resources."""
        await self.stop_consuming()

        if self._channel and not self._channel.is_closed:
            await self._channel.close()
            self._channel = None

        logger.info(f"AgentTaskConsumer for agent {self.agent_id} closed")


class DeadLetterQueueHandler(MessageBroker):
    """
    Handler for dead letter queue with retry logic.

    This class manages failed tasks, implementing exponential backoff retry
    logic and logging for debugging purposes.

    Requirements: 8.3, 8.4
    """

    def __init__(
        self,
        connection_pool: RabbitMQConnectionPool,
        publisher: AgentTaskPublisher,
        exchange_name: str = "agent_tasks",
        dlx_exchange_name: str = "agent_tasks_dlx",
        max_retries: int = 3,
        initial_retry_delay: int = 5000,  # milliseconds
        max_retry_delay: int = 300000,  # 5 minutes
    ):
        """
        Initialize the dead letter queue handler.

        Args:
            connection_pool: RabbitMQ connection pool
            publisher: Task publisher for republishing failed tasks
            exchange_name: Name of the main exchange
            dlx_exchange_name: Name of the dead letter exchange
            max_retries: Maximum number of retry attempts
            initial_retry_delay: Initial retry delay in milliseconds
            max_retry_delay: Maximum retry delay in milliseconds
        """
        super().__init__(connection_pool, exchange_name, dlx_exchange_name)
        self.publisher = publisher
        self.max_retries = max_retries
        self.initial_retry_delay = initial_retry_delay
        self.max_retry_delay = max_retry_delay
        self._channel: Channel | None = None
        self._dlq: aio_pika.Queue | None = None
        self._is_consuming = False

    def _calculate_retry_delay(self, retry_count: int) -> int:
        """
        Calculate retry delay using exponential backoff.

        Args:
            retry_count: Current retry count

        Returns:
            Delay in milliseconds
        """
        delay = self.initial_retry_delay * (2**retry_count)
        return min(delay, self.max_retry_delay)

    async def initialize(self) -> None:
        """Initialize the DLQ handler by setting up infrastructure."""
        logger.info("Initializing DeadLetterQueueHandler")

        # Get a channel from the pool
        self._channel = await self.connection_pool.get_channel()

        # Setup infrastructure
        await self.setup_infrastructure(self._channel)

        # Get DLX exchange reference
        dlx_exchange = await self._channel.get_exchange(self.dlx_exchange_name)

        # Declare the dead letter queue
        self._dlq = await self._declare_queue(
            self._channel,
            "agent.tasks.dlq",
        )

        # Bind DLQ to DLX with wildcard routing key
        await self._dlq.bind(dlx_exchange, routing_key="dlq.#")

        logger.info("DeadLetterQueueHandler initialized successfully")

    async def _process_dead_letter(self, message: AbstractIncomingMessage) -> None:
        """
        Process a message from the dead letter queue.

        Args:
            message: The dead letter message

        Requirements: 8.3, 8.4
        """
        async with message.process():
            try:
                # Deserialize the task
                task = AgentTask.from_json(message.body.decode())

                logger.warning(
                    f"Processing dead letter for task {task.task_id} "
                    f"(retry_count={task.retry_count}, max_retries={task.max_retries})"
                )

                # Check if we should retry
                if task.retry_count < task.max_retries:
                    # Increment retry count
                    task.retry_count += 1

                    # Calculate retry delay
                    retry_delay = self._calculate_retry_delay(task.retry_count)

                    logger.info(
                        f"Retrying task {task.task_id} (attempt {task.retry_count}/{task.max_retries}) "
                        f"after {retry_delay}ms delay"
                    )

                    # Wait for retry delay
                    await asyncio.sleep(retry_delay / 1000.0)

                    # Republish the task
                    await self.publisher.publish_task(task)

                    logger.info(f"Task {task.task_id} republished for retry")
                else:
                    # Max retries exceeded, log and discard
                    logger.error(
                        f"Task {task.task_id} exceeded max retries ({task.max_retries}). "
                        f"Discarding task.",
                        extra={
                            "task_id": str(task.task_id),
                            "session_id": str(task.session_id),
                            "agent_id": task.agent_id,
                            "retry_count": task.retry_count,
                            "message": task.message[:100],  # Log first 100 chars
                        },
                    )

                    # TODO: Store failed task in database for manual review
                    # This could be implemented as part of audit logging

                # Message is acknowledged after processing

            except Exception as e:
                logger.error(
                    f"Error processing dead letter: {e}",
                    exc_info=True,
                    extra={
                        "message_id": message.message_id,
                    },
                )
                # Acknowledge to prevent infinite loop
                # The error is logged for debugging

    async def start_processing(self) -> None:
        """
        Start processing messages from the dead letter queue.

        Requirements: 8.3, 8.4
        """
        if self._dlq is None:
            raise RuntimeError("DLQ handler not initialized. Call initialize() first.")

        if self._is_consuming:
            logger.warning("DLQ handler is already processing")
            return

        logger.info("Starting to process dead letter queue")
        self._is_consuming = True

        # Start consuming messages
        await self._dlq.consume(
            self._process_dead_letter,
            no_ack=False,
        )

        logger.info("DLQ handler is now active")

    async def stop_processing(self) -> None:
        """Stop processing messages from the dead letter queue."""
        if not self._is_consuming:
            return

        logger.info("Stopping DLQ handler")
        self._is_consuming = False

        # Consumer will be cancelled when channel is closed

        logger.info("DLQ handler stopped")

    async def close(self) -> None:
        """Close the DLQ handler and release resources."""
        await self.stop_processing()

        if self._channel and not self._channel.is_closed:
            await self._channel.close()
            self._channel = None

        logger.info("DeadLetterQueueHandler closed")
