"""Async task processor for agent conversations via RabbitMQ.

CrewAI IMPLEMENTATION:
- Uses CrewAI's Runner and Session for execution
- Agent execution uses _run_async_impl() instead of generate_reply()
"""

import logging
from typing import Any

from src.api.session_manager import SessionManager
from src.infrastructure.message_broker import (
    AgentTask,
    AgentTaskConsumer,
    AgentTaskPublisher,
    RabbitMQConnectionPool,
)


# Legacy CrewAI stub - CrewAI uses SessionManager's Runner directly
class ConversationPatternEngine:
    """Stub for legacy CrewAI pattern engine - not used in CrewAI."""

    pass


logger = logging.getLogger(__name__)


class AsyncAgentTaskProcessor:
    """
    Processor for handling agent tasks asynchronously.

    This class consumes agent tasks from RabbitMQ queues, executes them
    using the session manager and conversation engine, and publishes
    results back to result queues.

    Requirements: 8.1, 8.2, 8.5
    """

    def __init__(
        self,
        connection_pool: RabbitMQConnectionPool,
        session_manager: SessionManager,
        pattern_engine: ConversationPatternEngine,
        publisher: AgentTaskPublisher,
    ):
        """
        Initialize the async task processor.

        Args:
            connection_pool: RabbitMQ connection pool
            session_manager: Session manager for agent operations
            pattern_engine: Conversation pattern engine
            publisher: Task publisher for results
        """
        self.connection_pool = connection_pool
        self.session_manager = session_manager
        self.pattern_engine = pattern_engine
        self.publisher = publisher
        self._consumers: dict[str, AgentTaskConsumer] = {}
        self._is_running = False

    async def _handle_task(self, task: AgentTask) -> None:
        """
        Handle an agent task.

        Args:
            task: The agent task to process

        Requirements: 8.1, 8.2, 8.5
        """
        try:
            logger.info(
                f"Handling task {task.task_id} for agent {task.agent_id} "
                f"in session {task.session_id}"
            )

            # Get session
            session = await self.session_manager.get_session(task.session_id)
            if session is None:
                raise ValueError(f"Session not found: {task.session_id}")

            # Get agents for the session
            agents = await self.session_manager._get_or_create_agents(
                task.session_id,
                session,
            )

            # Determine conversation pattern
            pattern = task.context.get("pattern", "two_agent")

            # Execute based on pattern
            result: dict[str, Any] = {}

            if pattern == "two_agent":
                # Get sender and recipient agents
                sender_id = task.agent_id
                recipient_id = task.context.get("recipient_agent_id")

                if sender_id not in agents or recipient_id not in agents:
                    raise ValueError(
                        f"Agents not found: sender={sender_id}, recipient={recipient_id}"
                    )

                sender = agents[sender_id]
                recipient = agents[recipient_id]

                # Execute two-agent chat
                chat_result = self.pattern_engine.execute_two_agent_chat(
                    sender=sender,
                    recipient=recipient,
                    message=task.message,
                    **task.context.get("kwargs", {}),
                )

                # Extract result
                result = self._extract_chat_result(chat_result, recipient.name)

            elif pattern == "group_chat":
                # Get all agents for group chat
                agent_ids = task.context.get("agent_ids", [])
                group_agents = [agents[aid] for aid in agent_ids if aid in agents]

                if not group_agents:
                    raise ValueError(f"No agents found for group chat: {agent_ids}")

                # Execute group chat
                chat_result = self.pattern_engine.execute_group_chat(
                    agents=group_agents,
                    initial_message=task.message,
                    **task.context.get("kwargs", {}),
                )

                # Extract result
                result = self._extract_chat_result(chat_result)

            else:
                raise ValueError(f"Unsupported pattern: {pattern}")

            # Add task metadata to result
            result["task_id"] = str(task.task_id)
            result["session_id"] = str(task.session_id)
            result["agent_id"] = task.agent_id

            # Publish result
            await self.publisher.publish_result(task.session_id, result)

            # Notify pattern engine if it's waiting for this result
            if hasattr(self.pattern_engine, "handle_task_result"):
                await self.pattern_engine.handle_task_result(
                    task.task_id,
                    result,
                )

            logger.info(f"Successfully handled task {task.task_id}")

        except Exception as e:
            logger.error(
                f"Error handling task {task.task_id}: {e}",
                exc_info=True,
            )

            # Publish error result
            error_result = {
                "task_id": str(task.task_id),
                "session_id": str(task.session_id),
                "agent_id": task.agent_id,
                "error": str(e),
            }

            try:
                await self.publisher.publish_result(task.session_id, error_result)

                # Notify pattern engine of error
                if hasattr(self.pattern_engine, "handle_task_result"):
                    await self.pattern_engine.handle_task_result(
                        task.task_id,
                        error_result,
                        error=str(e),
                    )
            except Exception as publish_error:
                logger.error(
                    f"Failed to publish error result: {publish_error}",
                    exc_info=True,
                )

            # Re-raise to trigger retry via DLQ
            raise

    def _extract_chat_result(
        self,
        chat_result: Any,
        recipient_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Extract result data from CrewAI execution result.

        Args:
            chat_result: CrewAI execution result object
            recipient_name: Optional name of recipient agent

        Returns:
            Dictionary containing extracted result data
        """
        result: dict[str, Any] = {}

        # Extract summary
        if hasattr(chat_result, "summary") and chat_result.summary:
            result["summary"] = chat_result.summary
            result["response"] = chat_result.summary

        # Extract chat history
        if hasattr(chat_result, "chat_history") and chat_result.chat_history:
            result["chat_history"] = chat_result.chat_history

            # If no summary, get last message from recipient
            if "response" not in result and recipient_name:
                for msg in reversed(chat_result.chat_history):
                    if msg.get("name") == recipient_name:
                        result["response"] = msg.get("content", "")
                        break

        # Extract cost
        if hasattr(chat_result, "cost") and chat_result.cost:
            result["cost"] = chat_result.cost

        return result

    async def register_agent_consumer(self, agent_id: str) -> None:
        """
        Register a consumer for an agent's task queue.

        Args:
            agent_id: ID of the agent to consume tasks for

        Requirements: 8.2, 8.3
        """
        if agent_id in self._consumers:
            logger.warning(f"Consumer already registered for agent {agent_id}")
            return

        logger.info(f"Registering consumer for agent {agent_id}")

        # Create consumer
        consumer = AgentTaskConsumer(
            connection_pool=self.connection_pool,
            agent_id=agent_id,
            task_handler=self._handle_task,
        )

        # Initialize consumer
        await consumer.initialize()

        # Store consumer
        self._consumers[agent_id] = consumer

        # Start consuming if processor is running
        if self._is_running:
            await consumer.consume_tasks()

        logger.info(f"Consumer registered for agent {agent_id}")

    async def unregister_agent_consumer(self, agent_id: str) -> None:
        """
        Unregister a consumer for an agent.

        Args:
            agent_id: ID of the agent to stop consuming for
        """
        consumer = self._consumers.pop(agent_id, None)
        if consumer:
            await consumer.close()
            logger.info(f"Consumer unregistered for agent {agent_id}")

    async def start(self) -> None:
        """
        Start processing tasks from all registered consumers.

        Requirements: 8.2, 8.3
        """
        if self._is_running:
            logger.warning("Async task processor is already running")
            return

        logger.info("Starting async task processor")
        self._is_running = True

        # Start all consumers
        for agent_id, consumer in self._consumers.items():
            await consumer.consume_tasks()
            logger.info(f"Started consumer for agent {agent_id}")

        logger.info(f"Async task processor started with {len(self._consumers)} consumers")

    async def stop(self) -> None:
        """Stop processing tasks from all consumers."""
        if not self._is_running:
            return

        logger.info("Stopping async task processor")
        self._is_running = False

        # Stop all consumers
        for agent_id, consumer in self._consumers.items():
            await consumer.stop_consuming()
            logger.info(f"Stopped consumer for agent {agent_id}")

        logger.info("Async task processor stopped")

    async def close(self) -> None:
        """Close the processor and all consumers."""
        await self.stop()

        # Close all consumers
        for consumer in self._consumers.values():
            await consumer.close()

        self._consumers.clear()

        logger.info("Async task processor closed")
