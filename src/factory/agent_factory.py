"""CrewAI agent factory for Delaxis."""

from __future__ import annotations

from typing import Any

from src.config.agent_models import AgentConfig
from src.crewai_runtime.runtime import CrewAIWorkflowRuntime


class AgentFactory:
    """Compatibility import that now creates CrewAI agents only."""

    def __init__(self, runtime: CrewAIWorkflowRuntime | None = None, **_: Any) -> None:
        self.runtime = runtime or CrewAIWorkflowRuntime()

    def create_agent_from_config(
        self,
        agent_config: AgentConfig,
        sub_agents: list[Any] | None = None,
    ) -> Any:
        """Create a CrewAI agent from an existing agent config."""
        try:
            from crewai import Agent
        except Exception as exc:
            raise RuntimeError("CrewAI is not installed. Run `uv sync` to install dependencies.") from exc
        return self.runtime._create_agent(Agent, agent_config)
