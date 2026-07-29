"""Pydantic models for workflow configuration validation."""

from datetime import datetime
from enum import Enum
from typing import Any, List, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

# Import for v0.4 topology support
try:
    from src.config.topology_models import TopologyConfig
except ImportError:
    TopologyConfig = None  # type: ignore


class ConversationPattern(str, Enum):
    """Type of conversation pattern."""

    SINGLE = "single"
    TWO_AGENT = "two_agent"
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    GROUP_CHAT = "group_chat"
    NESTED = "nested"
    SELECTOR = "selector"
    INTERACTIVE = "interactive"  # Supports @ mentions for dynamic agent selection


class SpeakerSelectionMethod(str, Enum):
    """Speaker selection method for group chats."""

    AUTO = "auto"
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    MANUAL = "manual"


class SummaryMethod(str, Enum):
    """Method for generating conversation summaries."""

    LAST_MSG = "last_msg"
    REFLECTION_WITH_LLM = "reflection_with_llm"


class TerminationType(str, Enum):
    """Type of termination condition for CrewAI 0.4 teams."""
    
    TEXT_MENTION = "text_mention"
    MAX_MESSAGE = "max_message"
    COMBINED = "combined"


class TerminationOperator(str, Enum):
    """Operator for combining termination conditions."""
    
    AND = "and"
    OR = "or"


class TeamType(str, Enum):
    """Type of team for CrewAI 0.4."""
    
    ROUND_ROBIN = "round_robin"
    SELECTOR = "selector"
    CUSTOM = "custom"


class TerminationConfig(BaseModel):
    """Configuration for team termination conditions.
    
    Supports three types of termination conditions:
    - text_mention: Terminates when a specific text is mentioned
    - max_message: Terminates after a maximum number of messages
    - combined: Combines multiple conditions with and/or operator
    
    """
    
    type: TerminationType = Field(
        description="Type of termination condition"
    )
    text_mention: Optional[str] = Field(
        default=None,
        description="Text to match for text_mention termination (e.g., 'TERMINATE')"
    )
    max_messages: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum number of messages for max_message termination"
    )
    conditions: Optional[List["TerminationConfig"]] = Field(
        default=None,
        description="List of termination conditions for combined type"
    )
    operator: Optional[TerminationOperator] = Field(
        default=None,
        description="Operator for combining conditions (and/or)"
    )
    
    @model_validator(mode='after')
    def validate_termination_config(self) -> "TerminationConfig":
        """Validate termination configuration based on type."""
        if self.type == TerminationType.TEXT_MENTION:
            if not self.text_mention:
                raise ValueError(
                    "text_mention termination requires 'text_mention' field"
                )
        elif self.type == TerminationType.MAX_MESSAGE:
            if self.max_messages is None:
                raise ValueError(
                    "max_message termination requires 'max_messages' field"
                )
        elif self.type == TerminationType.COMBINED:
            if not self.conditions or len(self.conditions) < 2:
                raise ValueError(
                    "combined termination requires at least 2 conditions"
                )
            if self.operator is None:
                raise ValueError(
                    "combined termination requires 'operator' field (and/or)"
                )
        return self


class TeamConfig(BaseModel):
    """Configuration for CrewAI teams.
    
    Teams provide structured multi-agent collaboration with built-in orchestration.
    """
    
    id: str = Field(
        pattern=r"^[a-z0-9_-]+$",
        description="Unique team identifier"
    )
    type: TeamType = Field(
        description="Type of team (round_robin, selector, custom)"
    )
    agents: List[str] = Field(
        min_length=2,
        description="List of agent IDs participating in the team"
    )
    termination_condition: TerminationConfig = Field(
        description="Termination condition for the team"
    )
    max_turns: Optional[int] = Field(
        default=None,
        ge=1,
        description="Maximum number of conversation turns"
    )
    # Selector-specific settings
    selector_model_client_config: Optional[dict[str, Any]] = Field(
        default=None,
        description="Model client configuration for SelectorGroupChat speaker selection"
    )
    selector_func: Optional[str] = Field(
        default=None,
        description="Reference to custom selector function (module.path:function_name)"
    )
    
    @field_validator('agents')
    @classmethod
    def validate_agents(cls, v: List[str]) -> List[str]:
        """Validate agent list."""
        if len(v) < 2:
            raise ValueError("Team requires at least 2 agents")
        
        # Check for duplicates
        if len(v) != len(set(v)):
            raise ValueError("Agent IDs must be unique in team")
        
        # Validate each agent ID
        for agent_id in v:
            if not agent_id or not agent_id.strip():
                raise ValueError("Agent ID cannot be empty")
            if not agent_id.replace('_', '').replace('-', '').isalnum():
                raise ValueError(
                    f"Agent ID '{agent_id}' must contain only alphanumeric characters, "
                    "underscores, and hyphens"
                )
        
        return v
    
    @model_validator(mode='after')
    def validate_team_config(self) -> "TeamConfig":
        """Validate team configuration based on type."""
        if self.type == TeamType.SELECTOR:
            if self.selector_model_client_config is None and self.selector_func is None:
                raise ValueError(
                    "Selector team requires either 'selector_model_client_config' "
                    "or 'selector_func'"
                )
        return self


class WorkflowType(str, Enum):
    """Type of workflow for classification and routing."""

    CHATBOT = "chatbot"
    SEQUENTIAL = "sequential"
    TREE = "tree"
    CUSTOM = "custom"


class PersistenceMode(str, Enum):
    """Persistence backend mode."""

    POSTGRES = "postgres"
    MONGO_ONLY = "mongo_only"


class AgentRuntime(str, Enum):
    """Runtime engine used to execute a workflow."""

    CREWAI = "crewai"


class CrewAIProcess(str, Enum):
    """CrewAI process mode."""

    SEQUENTIAL = "sequential"
    HIERARCHICAL = "hierarchical"


class CrewAIMemoryConfig(BaseModel):
    """CrewAI memory configuration scoped to a workflow."""

    enabled: bool = True
    storage_dir: str | None = None
    retention: str = "session"


class CrewAIKnowledgeConfig(BaseModel):
    """CrewAI knowledge/RAG configuration scoped to a workflow."""

    enabled: bool = False
    collections: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=50)


class CrewAIGuardrailsConfig(BaseModel):
    """CrewAI guardrail configuration scoped to a workflow."""

    enabled: bool = True
    human_review: bool = False
    output_schema: str = "text"


class CrewAITracingConfig(BaseModel):
    """CrewAI tracing/observability configuration scoped to a workflow."""

    enabled: bool = True
    amp_enabled: bool = False
    event_listeners: list[str] = Field(default_factory=list)


class CrewAITaskConfig(BaseModel):
    """Optional explicit CrewAI task configuration."""

    id: str
    node_id: str | None = None
    agent_id: str
    description: str
    expected_output: str = "A useful, accurate result for the next step or user."


class WorkflowStep(BaseModel):
    """Configuration for a single step in a sequential workflow."""

    sender_id: str = Field(
        description="ID of the agent that initiates this conversation"
    )
    recipient_id: str = Field(
        description="ID of the agent that receives the message"
    )
    message: Optional[str] = Field(
        default=None,
        description="Initial message for this step (optional if using carryover)"
    )
    max_turns: int = Field(
        default=10,
        ge=1,
        description="Maximum number of conversation turns for this step"
    )
    summary_method: SummaryMethod = Field(
        default=SummaryMethod.LAST_MSG,
        description="Method for generating summary of this conversation"
    )
    carryover: bool = Field(
        default=True,
        description="Whether to carry over context from previous step"
    )
    clear_history: bool = Field(
        default=False,
        description="Whether to clear chat history before this step"
    )

    @field_validator('sender_id', 'recipient_id')
    @classmethod
    def validate_agent_id(cls, v: str) -> str:
        """Validate agent ID format."""
        if not v or not v.strip():
            raise ValueError("Agent ID cannot be empty")
        if not v.replace('_', '').replace('-', '').isalnum():
            raise ValueError(
                f"Agent ID '{v}' must contain only alphanumeric characters, "
                "underscores, and hyphens"
            )
        return v


class GroupChatConfig(BaseModel):
    """Configuration for a group chat workflow."""

    agents: list[str] = Field(
        min_length=2,
        description="List of agent IDs participating in the group chat"
    )
    max_round: int = Field(
        default=10,
        ge=1,
        description="Maximum number of conversation rounds"
    )
    speaker_selection_method: SpeakerSelectionMethod = Field(
        default=SpeakerSelectionMethod.AUTO,
        description="Method for selecting the next speaker"
    )
    allowed_transitions: Optional[dict[str, list[str]]] = Field(
        default=None,
        description="Dictionary mapping agent IDs to lists of agent IDs they can transition to"
    )
    speaker_transitions_type: Optional[str] = Field(
        default=None,
        description="Type of transitions: 'allowed' or 'disallowed'"
    )
    send_introductions: bool = Field(
        default=False,
        description="Whether agents should introduce themselves at the start"
    )
    admin_name: str = Field(
        default="GroupChatManager",
        description="Name for the GroupChatManager agent"
    )
    select_speaker_message_template: Optional[str] = Field(
        default=None,
        description="Custom template for speaker selection prompt"
    )
    select_speaker_auto_verbose: bool = Field(
        default=False,
        description="Whether to show verbose output during speaker selection"
    )

    @field_validator('agents')
    @classmethod
    def validate_agents(cls, v: list[str]) -> list[str]:
        """Validate agent list."""
        if len(v) < 2:
            raise ValueError("Group chat requires at least 2 agents")
        
        # Check for duplicates
        if len(v) != len(set(v)):
            raise ValueError("Agent IDs must be unique in group chat")
        
        # Validate each agent ID
        for agent_id in v:
            if not agent_id or not agent_id.strip():
                raise ValueError("Agent ID cannot be empty")
            if not agent_id.replace('_', '').replace('-', '').isalnum():
                raise ValueError(
                    f"Agent ID '{agent_id}' must contain only alphanumeric characters, "
                    "underscores, and hyphens"
                )
        
        return v

    @field_validator('speaker_transitions_type')
    @classmethod
    def validate_transitions_type(cls, v: Optional[str], info) -> Optional[str]:
        """Validate speaker transitions type."""
        if v is not None and v not in ['allowed', 'disallowed']:
            raise ValueError("speaker_transitions_type must be 'allowed' or 'disallowed'")
        
        # If allowed_transitions is set, speaker_transitions_type should be set
        allowed_transitions = info.data.get('allowed_transitions')
        if allowed_transitions is not None and v is None:
            return 'allowed'  # Default to 'allowed'
        
        return v


class NestedChatConfig(BaseModel):
    """Configuration for a nested chat trigger."""

    trigger_agent_id: str = Field(
        description="ID of the agent that will trigger nested chats"
    )
    nested_chats: list[dict[str, Any]] = Field(
        description="List of nested chat configurations"
    )
    trigger_condition: Optional[str] = Field(
        default=None,
        description="String to match in messages to trigger nested chat (None = always trigger)"
    )
    position: int = Field(
        default=2,
        ge=0,
        description="Position in reply sequence where nested chat executes"
    )


class SelectorConfig(BaseModel):
    """Configuration for a selector (router) workflow pattern.
    
    The selector pattern uses a routing agent to analyze user intent
    and route queries to specialized domain agents.
    """

    routing_agents: dict[str, str] = Field(
        description="Mapping of domain names to agent IDs (e.g., {'math': 'calculator_agent'})"
    )
    default_agent: str = Field(
        description="Agent ID to use when no specific domain is matched"
    )
    max_routing_attempts: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum number of routing attempts before failing"
    )

    @field_validator('routing_agents')
    @classmethod
    def validate_routing_agents(cls, v: dict[str, str]) -> dict[str, str]:
        """Validate routing agents mapping."""
        if not v:
            raise ValueError("routing_agents cannot be empty")
        
        for domain, agent_id in v.items():
            if not domain or not domain.strip():
                raise ValueError("Domain name cannot be empty")
            if not agent_id or not agent_id.strip():
                raise ValueError(f"Agent ID for domain '{domain}' cannot be empty")
            if not agent_id.replace('_', '').replace('-', '').isalnum():
                raise ValueError(
                    f"Agent ID '{agent_id}' must contain only alphanumeric characters, "
                    "underscores, and hyphens"
                )
        
        return v


class InteractiveConfig(BaseModel):
    """Configuration for an interactive workflow with @ mention support.
    
    Allows users to dynamically select agents during conversation using @ mentions.
    Example: "Hey @calculator_agent, what is 2+2?"
    """

    enabled: bool = Field(
        default=True,
        description="Whether interactive @ mention routing is enabled"
    )
    
    available_agents: list[str] = Field(
        min_length=1,
        description="List of agent IDs that users can mention with @"
    )
    default_agent: str = Field(
        description="Agent ID to use when no @ mention is detected"
    )
    mention_prefix: str = Field(
        default="@",
        description="Prefix character for agent mentions"
    )
    allow_multiple_mentions: bool = Field(
        default=False,
        description="Whether to allow mentioning multiple agents in one message"
    )
    max_turns: int = Field(
        default=20,
        ge=1,
        description="Maximum number of conversation turns"
    )
    
    @field_validator('available_agents')
    @classmethod
    def validate_available_agents(cls, v: list[str]) -> list[str]:
        """Validate that all agent IDs are non-empty and properly formatted."""
        if not v:
            raise ValueError("available_agents cannot be empty")
        
        for agent_id in v:
            if not agent_id or not agent_id.strip():
                raise ValueError("Agent ID cannot be empty")
            if not agent_id.replace('_', '').replace('-', '').isalnum():
                raise ValueError(
                    f"Agent ID '{agent_id}' must contain only alphanumeric characters, "
                    "underscores, and hyphens"
                )
        
        # Check for duplicates
        if len(v) != len(set(v)):
            raise ValueError("available_agents contains duplicate agent IDs")
        
        return v
    
    @model_validator(mode='after')
    def validate_default_agent_in_available(self) -> 'InteractiveConfig':
        """Validate that default_agent exists (but doesn't need to be in available_agents).
        
        The default_agent can be a routing/selector agent that handles classification
        but isn't meant for direct @ mention interaction. In this case, it won't be
        in available_agents, but that's intentional - when no @ mention is provided,
        the workflow uses topology-based routing through the default agent.
        """
        # No validation needed - default_agent can be outside available_agents
        # for routing-only agents like selector_agent
        return self


class WorkflowConfig(BaseModel):
    """Configuration for a complete workflow."""

    id: str = Field(
        pattern=r"^[a-z0-9_-]+$",
        description="Unique workflow identifier"
    )
    name: str = Field(
        description="Human-readable workflow name"
    )
    description: str = Field(
        description="Description of what this workflow does"
    )
    
    pattern: ConversationPattern = Field(
        default=ConversationPattern.SEQUENTIAL,
        description="Conversation pattern: single, sequential, parallel, selector, ..."
    )

    # v0.4 topology configuration (required - all workflows use topology)
    topology: "TopologyConfig" = Field(
        description="Topology configuration defining workflow structure with nodes, edges, and routing"
    )
    
    # Execution strategy
    execution_strategy: str = Field(
        default="sequential",
        description="Execution strategy: sequential, conditional, or parallel"
    )
    
    # Common settings
    enabled: bool = Field(
        default=True,
        description="Whether this workflow is enabled"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional workflow metadata"
    )
    
    # Interactive workflow configuration
    interactive_config: Optional[InteractiveConfig] = Field(
        default=None,
        description="Configuration for interactive workflows with @ mention support"
    )
    
    # Persistence configuration (Requirement 16.4, 17.2, 17.3)
    persistence: PersistenceMode = Field(
        default=PersistenceMode.POSTGRES,
        description="Persistence backend: 'postgres' or 'mongo_only'"
    )
    workflow_type: WorkflowType = Field(
        default=WorkflowType.SEQUENTIAL,
        description="Workflow type: 'chatbot', 'sequential', 'tree', or 'custom'"
    )
    runtime: AgentRuntime = Field(
        default=AgentRuntime.CREWAI,
        description="Runtime engine for this workflow: 'crewai'"
    )
    process: CrewAIProcess = Field(
        default=CrewAIProcess.SEQUENTIAL,
        description="CrewAI process mode"
    )
    tasks: list[CrewAITaskConfig] = Field(
        default_factory=list,
        description="Explicit CrewAI task definitions. When empty, tasks are derived from topology nodes."
    )
    memory: CrewAIMemoryConfig = Field(default_factory=CrewAIMemoryConfig)
    knowledge: CrewAIKnowledgeConfig = Field(default_factory=CrewAIKnowledgeConfig)
    guardrails: CrewAIGuardrailsConfig = Field(default_factory=CrewAIGuardrailsConfig)
    planning: bool = Field(
        default=False,
        description="Enable CrewAI planning: an LLM drafts a step-by-step plan before execution",
    )
    cache: bool = Field(
        default=True,
        description="Enable CrewAI tool-result caching across the crew",
    )
    max_rpm: int | None = Field(
        default=None,
        ge=1,
        description="Crew-wide requests-per-minute cap for LLM calls",
    )
    verbose: bool = Field(
        default=False,
        description="Verbose crew execution logging",
    )
    manager_llm: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Model config for the hierarchical manager that delegates between agents. "
            "Defaults to the entry agent's model; a weak manager emits delegations as plain text."
        ),
    )
    planning_llm: dict[str, Any] | None = Field(
        default=None,
        description="Model config for the planning step. Defaults to the entry agent's model.",
    )
    tracing: CrewAITracingConfig = Field(default_factory=CrewAITracingConfig)
    event_listeners: list[dict[str, Any]] = Field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    output_schema: dict[str, Any] | str | None = Field(default="text")
    deployment_auth_mode: str = Field(default="public")
    
    # Versioning and metadata fields (Requirement 17.1, 17.2)
    version: int = Field(
        default=1,
        ge=1,
        description="Configuration version number"
    )
    last_updated: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp of last configuration update"
    )

    @field_validator('workflow_type')
    @classmethod
    def validate_workflow_type(cls, v: WorkflowType) -> WorkflowType:
        """Validate workflow_type enum value."""
        if v not in WorkflowType:
            raise ValueError(
                f"workflow_type must be one of {[t.value for t in WorkflowType]}, got '{v}'"
            )
        return v

    def validate_pattern_config(self) -> None:
        """Validate that the topology is consistent with the declared pattern.

        Raises:
            ValueError: If the topology does not match the pattern's requirements
        """
        node_count = len(self.topology.nodes)
        if node_count == 0:
            raise ValueError(f"Workflow '{self.id}' must define at least one topology node")

        if self.pattern == ConversationPattern.SINGLE and node_count != 1:
            raise ValueError(
                f"Workflow '{self.id}' uses pattern 'single' but defines {node_count} nodes"
            )

        if self.pattern == ConversationPattern.SELECTOR and node_count < 2:
            raise ValueError(
                f"Workflow '{self.id}' uses pattern 'selector' but needs an entry agent "
                "plus at least one specialist node"
            )

        entry = getattr(self.topology, "entry_node", None)
        if entry:
            node_ids = {node.id for node in self.topology.nodes}
            if entry not in node_ids:
                raise ValueError(
                    f"Workflow '{self.id}' entry_node '{entry}' is not a topology node"
                )

    def get_all_agent_ids(self) -> set[str]:
        """
        Get all agent IDs referenced in this workflow.

        Returns:
            Set of agent IDs used in the workflow
        """
        agent_ids = {node.agent_id for node in self.topology.nodes}

        # Include interactive @ mention agents so they are instantiated even
        # when they are not wired directly in the topology graph.
        if self.interactive_config and getattr(self.interactive_config, "enabled", True):
            agent_ids.update(self.interactive_config.available_agents)
            agent_ids.add(self.interactive_config.default_agent)

        return agent_ids

    @model_validator(mode='after')
    def validate_interactive_agents_exist(self) -> "WorkflowConfig":
        """Ensure interactive default agent participates in topology.

        The interactive default agent is used when no @ mention is present and
        the workflow falls back to topology-based routing. It must therefore be
        present in the topology nodes so the execution engine can route
        correctly.
        """

        if self.interactive_config:
            topology_agents = {node.agent_id for node in self.topology.nodes}
            default_agent = self.interactive_config.default_agent

            if default_agent not in topology_agents:
                raise ValueError(
                    "Interactive default_agent must be present in topology nodes for routing"
                )

        return self


class WorkflowsConfig(BaseModel):
    """Root configuration for workflows."""

    version: str = Field(
        description="Configuration version"
    )
    workflows: list[WorkflowConfig] = Field(
        description="List of workflow configurations"
    )

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowConfig]:
        """
        Get workflow configuration by ID.
        
        Args:
            workflow_id: Workflow identifier
            
        Returns:
            WorkflowConfig or None if not found
        """
        return next((w for w in self.workflows if w.id == workflow_id), None)

    def get_enabled_workflows(self) -> list[WorkflowConfig]:
        """
        Get all enabled workflow configurations.
        
        Returns:
            List of enabled WorkflowConfig objects
        """
        return [w for w in self.workflows if w.enabled]

    def validate_all(self) -> None:
        """
        Validate all workflow configurations.
        
        Raises:
            ValueError: If any workflow configuration is invalid
        """
        # Check for duplicate IDs
        workflow_ids = [w.id for w in self.workflows]
        if len(workflow_ids) != len(set(workflow_ids)):
            duplicates = [wid for wid in workflow_ids if workflow_ids.count(wid) > 1]
            raise ValueError(f"Duplicate workflow IDs found: {set(duplicates)}")
        
        # Validate topology structure for each workflow
        for workflow in self.workflows:
            if not workflow.topology or len(workflow.topology.nodes) == 0:
                raise ValueError(f"Workflow {workflow.id} must have at least one node in topology")
