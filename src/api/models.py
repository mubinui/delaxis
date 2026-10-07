"""Pydantic models for API requests and responses."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, field_validator


class ConversationPattern(StrEnum):
    """CrewAI conversation and orchestration patterns."""

    SELECTOR = "selector"
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    LOOP = "loop"
    SINGLE = "single"
    TWO_AGENT = "two_agent"  # Legacy compatibility


# Session Models
class SessionCreateRequest(BaseModel):
    """Request to create a new chatbot session."""

    user_id: str | None = Field(default=None, description="Optional user identifier")
    workflow_id: str | None = Field(
        default="support_triage", description="Workflow to use (defaults to support_triage)"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class SessionResponse(BaseModel):
    """Response containing chatbot session information."""

    session_id: UUID
    workflow_id: str = Field(description="Workflow used by this session")
    user_id: str | None
    active: bool
    created_at: datetime
    updated_at: datetime
    turn_count: int
    metadata: dict[str, Any]


class UserSessionsResponse(BaseModel):
    """Response containing all sessions for a user."""

    user_id: str
    sessions: list["SessionResponse"]
    total_count: int
    active_count: int


class Chat(BaseModel):
    """Chat DTO for frontend consumption."""

    id: str = Field(description="Unique chat/session identifier")
    title: str = Field(description="Chat title (derived from first message or workflow name)")
    messageCount: int | None = Field(default=0, description="Number of messages in the chat")  # noqa: N815 - Studio wire contract
    createdAt: str = Field(description="ISO timestamp when chat was created")  # noqa: N815 - Studio wire contract
    updatedAt: str = Field(description="ISO timestamp when chat was last updated")  # noqa: N815 - Studio wire contract


class ChatListResponse(BaseModel):
    """Response containing list of chats for a user."""

    chats: list[Chat]
    total: int


# Message Models
class MessageRequest(BaseModel):
    """Request to send a message in a session."""

    message: str = Field(description="The message content")
    pattern: ConversationPattern = Field(
        default=ConversationPattern.TWO_AGENT, description="Conversation pattern to use"
    )
    max_turns: int | None = Field(default=None, description="Maximum conversation turns")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class MessageResponse(BaseModel):
    """Response from processing a message."""

    session_id: UUID
    response: str
    turn_count: int
    cost: dict[str, Any] = Field(default_factory=dict, description="Cost information")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Response metadata")
    chat_history: list[dict[str, Any]] = Field(
        default_factory=list, description="Conversation history"
    )
    summary: str = Field(default="", description="Conversation summary")
    safety_passed: bool = Field(default=True, description="Content safety check result")


class QueryRequest(BaseModel):
    """Request DTO for the query endpoint.

    Accepts sessionId in the request body for simplified frontend integration.
    """

    session_id: str = Field(description="Session identifier", alias="sessionId")
    query: str = Field(description="The message/query content", min_length=1)
    pattern: ConversationPattern | None = Field(
        default=None, description="Conversation pattern to use (optional)"
    )
    max_turns: int | None = Field(
        default=None, description="Maximum conversation turns (optional)", alias="maxTurns"
    )
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

    model_config = {
        "populate_by_name": True,
        "extra": "ignore",  # Forward compatibility - ignore unknown fields
    }

    @field_validator("query")
    @classmethod
    def validate_query_not_whitespace(cls, v: str) -> str:
        """Reject whitespace-only queries."""
        if not v.strip():
            raise ValueError("Query cannot be empty or contain only whitespace")
        return v


class QueryResponse(BaseModel):
    """Response DTO for the query endpoint.

    Uses camelCase field naming for frontend compatibility.
    """

    session_id: str = Field(description="Session identifier", serialization_alias="sessionId")
    response: str = Field(description="AI agent response")
    turn_count: int = Field(description="Current turn count", serialization_alias="turnCount")
    chat_history: list[dict[str, Any]] = Field(
        default_factory=list, description="Conversation history", serialization_alias="chatHistory"
    )
    summary: str = Field(default="", description="Conversation summary")
    safety_passed: bool = Field(
        default=True, description="Content safety check result", serialization_alias="safetyPassed"
    )
    cost: dict[str, Any] = Field(default_factory=dict, description="Cost information")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Response metadata")

    model_config = {"populate_by_name": True}


class ChatHistoryResponse(BaseModel):
    """Response containing chat history."""

    session_id: UUID
    messages: list[dict[str, Any]]
    agent_notes: list[dict[str, Any]]
    turn_count: int


# Agent Configuration Models
class AgentConfigCreateRequest(BaseModel):
    """Request to create an agent configuration."""

    id: str = Field(pattern=r"^[a-z0-9_]+$", description="Unique agent identifier")
    type: str = Field(description="Agent type")
    name: str = Field(description="Agent display name (no spaces allowed)")
    system_message: str | None = Field(default="You are a helpful AI assistant.")
    llm_config: dict[str, Any] | bool | None = None
    human_input_mode: str = Field(default="NEVER")
    code_execution_config: dict[str, Any] | bool | None = False
    tools: list[str] = Field(default_factory=list)
    max_consecutive_auto_reply: int = Field(default=10, ge=0)
    retrieve_config: dict[str, Any] | None = None
    description: str | None = None
    is_selector: bool = Field(default=False, description="Agent routes/delegates to peer agents")
    output_key: str | None = Field(
        default=None, description="State key this agent writes its result to"
    )
    agent_settings: dict[str, Any] | None = Field(
        default=None,
        description="CrewAI Agent execution settings (max_iter, max_rpm, delegation, ...)",
    )
    model_config_override: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("model_config_override", "model_config"),
        description="Untyped model settings merged last; accepts the studio's 'model_config' key",
    )


class AgentConfigResponse(BaseModel):
    """Response containing agent configuration."""

    id: str
    type: str
    name: str
    system_message: str | None = None
    llm_config: dict[str, Any] | bool | None = None
    human_input_mode: str = "NEVER"
    code_execution_config: dict[str, Any] | bool | None = False
    tools: list[str] = Field(default_factory=list)
    max_consecutive_auto_reply: int = 10
    retrieve_config: dict[str, Any] | None = None
    description: str | None = None
    is_selector: bool = Field(default=False, description="Agent routes/delegates to peer agents")
    output_key: str | None = Field(
        default=None, description="State key this agent writes its result to"
    )
    agent_settings: dict[str, Any] | None = Field(
        default=None,
        description="CrewAI Agent execution settings (max_iter, max_rpm, delegation, ...)",
    )
    model_config_override: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("model_config_override", "model_config"),
        description="Untyped model settings merged last; accepts the studio's 'model_config' key",
    )


class AgentConfigUpdateRequest(BaseModel):
    """Request to update an agent configuration."""

    name: str | None = None
    system_message: str | None = None
    llm_config: dict[str, Any] | bool | None = None
    human_input_mode: str | None = None
    code_execution_config: dict[str, Any] | bool | None = None
    tools: list[str] | None = None
    max_consecutive_auto_reply: int | None = None
    retrieve_config: dict[str, Any] | None = None
    description: str | None = None
    is_selector: bool | None = None
    output_key: str | None = None
    agent_settings: dict[str, Any] | None = None
    model_config_override: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("model_config_override", "model_config"),
    )


# Tool Models
class ToolRegisterRequest(BaseModel):
    """Request to register a tool.

    Supported settings['type'] values: function (default, requires entrypoint),
    api (requires settings.api_url), mcp (requires transport + command/url),
    database (requires db_uri or db_uri_env_var), gmail (requires account_email).
    """

    id: str = Field(
        pattern=r"^[a-z0-9_]+$",
        description="Unique tool identifier (lowercase alphanumeric and underscores only)",
    )
    name: str = Field(description="Tool name")
    description: str = Field(description="Tool description")
    entrypoint: str | None = Field(
        default=None,
        description="Python entrypoint (module.path:function). Required for function tools only.",
    )
    enabled: bool = Field(default=True)
    settings: dict[str, Any] = Field(
        default_factory=dict, description="Tool settings; see ToolConfig for per-type requirements."
    )

    def model_post_init(self, __context: Any) -> None:
        """Validate by delegating to ToolConfig — the single source of truth for tool schemas."""
        from src.config.tool_models import ToolConfig

        validated = ToolConfig(
            id=self.id,
            name=self.name,
            description=self.description,
            entrypoint=self.entrypoint,
            enabled=self.enabled,
            settings=self.settings,
        )
        # ToolConfig may normalize fields (e.g. default entrypoint for api tools,
        # default gmail capabilities) — propagate those back.
        self.entrypoint = validated.entrypoint
        self.settings = validated.settings

        if self.entrypoint and ":" not in self.entrypoint:
            raise ValueError(
                f"Invalid entrypoint format: '{self.entrypoint}'. "
                "Expected format: 'module.path:function_name' (e.g., 'src.tools.calculator:calculate')"
            )


class ToolResponse(BaseModel):
    """Response containing tool information."""

    id: str
    name: str
    description: str
    entrypoint: str | None = None
    enabled: bool
    settings: dict[str, Any]
    category: str | None = None


class ToolUpdateRequest(BaseModel):
    """Request to update a tool."""

    name: str | None = None
    description: str | None = None
    entrypoint: str | None = None
    enabled: bool | None = None
    settings: dict[str, Any] | None = None
    category: str | None = None


# Swagger Import Models
class SwaggerImportRequest(BaseModel):
    """Request to import tools from a Swagger/OpenAPI specification."""

    swagger_url: str = Field(description="URL to the Swagger/OpenAPI specification (JSON or YAML)")
    endpoint_filter: list[str] | None = Field(
        default=None, description="List of operation_ids to import. If None, imports all endpoints."
    )
    auth_type: str = Field(
        default="none",
        description="Default authentication type for imported tools: 'none', 'bearer', 'api_key', 'basic'",
    )
    auth_env_var: str | None = Field(
        default=None, description="Environment variable name containing authentication credentials"
    )
    forward_user_context: bool = Field(
        default=False,
        description="Whether to forward user context headers (x-client-username, x-client-ref)",
    )
    timeout: int = Field(default=30, ge=1, le=300, description="Request timeout in seconds (1-300)")
    enabled: bool = Field(
        default=True, description="Whether imported tools should be enabled by default"
    )


class SwaggerPreviewEndpoint(BaseModel):
    """Preview of an endpoint from Swagger spec."""

    operation_id: str
    path: str
    method: str
    summary: str
    description: str
    tags: list[str]
    generated_tool_id: str
    is_duplicate: bool = False


class SwaggerPreviewResponse(BaseModel):
    """Response from previewing a Swagger specification."""

    title: str
    version: str
    description: str
    base_url: str
    openapi_version: str
    endpoints: list[SwaggerPreviewEndpoint]
    total_endpoints: int
    duplicate_count: int
    errors: list[str] = Field(default_factory=list)


class SwaggerImportResult(BaseModel):
    """Result of importing tools from Swagger."""

    success: bool
    imported_count: int
    skipped_duplicates: list[str]
    imported_tools: list[str]
    errors: list[str] = Field(default_factory=list)


# Workflow Models
class WorkflowStepConfig(BaseModel):
    """Configuration for a workflow step."""

    sender_id: str
    recipient_id: str
    message: str | None = None
    max_turns: int = 10
    summary_method: str = "last_msg"


class GroupChatConfigModel(BaseModel):
    """Configuration for group chat."""

    agents: list[str]
    max_round: int = 10
    speaker_selection_method: str = "auto"
    allowed_transitions: dict[str, list[str]] | None = None
    send_introductions: bool = False


class WorkflowNodePosition(BaseModel):
    """Position of a node in the visual workflow builder."""

    x: float = Field(description="X coordinate")
    y: float = Field(description="Y coordinate")


class WorkflowNode(BaseModel):
    """Node in a visual workflow."""

    id: str = Field(description="Unique node identifier")
    agent_id: str = Field(description="ID of the agent this node represents")
    position: WorkflowNodePosition = Field(description="Position in the canvas")
    config: dict[str, Any] = Field(default_factory=dict, description="Node-specific configuration")


class WorkflowConnection(BaseModel):
    """Connection between workflow nodes."""

    from_node: str = Field(description="Source node ID")
    to_node: str = Field(description="Target node ID")
    type: str = Field(description="Connection type: 'sequential' or 'parallel'")


class WorkflowCreateRequest(BaseModel):
    """Request to create a workflow."""

    id: str = Field(pattern=r"^[a-z0-9_-]+$", description="Unique workflow identifier")
    name: str = Field(description="Workflow name")
    description: str = Field(default="", description="Workflow description")
    pattern: ConversationPattern = Field(description="Conversation pattern")
    entry_agent_id: str = Field(description="ID of the entry agent")
    recipient_agent_id: str | None = Field(
        default=None, description="ID of recipient agent (for two_agent pattern)"
    )
    max_turns: int = Field(default=10, ge=1, description="Maximum conversation turns")
    summary_method: str = Field(default="last_msg", description="Summary method")
    enabled: bool = Field(default=True, description="Whether workflow is enabled")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    topology: dict[str, Any] | None = Field(
        default=None, description="CrewAI topology configuration"
    )
    execution_strategy: str | None = Field(
        default="sequential", description="Workflow execution strategy"
    )
    workflow_type: str = Field(default="sequential", description="Workflow type")
    persistence: str = Field(default="postgres", description="Persistence mode")
    runtime: str = Field(default="crewai", description="Workflow runtime")
    process: str = Field(default="sequential", description="CrewAI process mode")
    tasks: list[dict[str, Any]] = Field(default_factory=list, description="Explicit CrewAI tasks")
    memory: dict[str, Any] = Field(default_factory=dict, description="CrewAI memory settings")
    knowledge: dict[str, Any] = Field(default_factory=dict, description="CrewAI knowledge settings")
    guardrails: dict[str, Any] = Field(
        default_factory=dict, description="CrewAI guardrail settings"
    )
    tracing: dict[str, Any] = Field(default_factory=dict, description="CrewAI tracing settings")
    event_listeners: list[dict[str, Any]] = Field(
        default_factory=list, description="CrewAI event listener settings"
    )
    mcp_servers: list[dict[str, Any]] = Field(
        default_factory=list, description="MCP server settings"
    )
    output_schema: dict[str, Any] | str | None = Field(
        default="text", description="Structured output schema"
    )
    deployment_auth_mode: str = Field(
        default="public", description="Default deployed chatbot auth mode"
    )
    steps: list[WorkflowStepConfig] | None = None
    group_chat: GroupChatConfigModel | None = None
    nested_chats: list[dict] | None = None
    selector_config: dict[str, Any] | None = Field(
        default=None, description="Selector configuration (for selector pattern)"
    )
    nodes: list[WorkflowNode] | None = Field(default=None, description="Visual workflow nodes")
    connections: list[WorkflowConnection] | None = Field(
        default=None, description="Visual workflow connections"
    )


class WorkflowResponse(BaseModel):
    """Response containing workflow information."""

    id: str
    name: str
    description: str
    topology: dict[str, Any]
    execution_strategy: str | None = None
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None
    workflow_type: str | None = None
    persistence: str | None = None
    runtime: str | None = None
    process: str | None = None
    tasks: list[dict[str, Any]] | None = None
    memory: dict[str, Any] | None = None
    knowledge: dict[str, Any] | None = None
    guardrails: dict[str, Any] | None = None
    tracing: dict[str, Any] | None = None
    event_listeners: list[dict[str, Any]] | None = None
    mcp_servers: list[dict[str, Any]] | None = None
    output_schema: dict[str, Any] | str | None = None
    deployment_auth_mode: str | None = None
    version: int | None = None
    last_updated: str | None = None


class WorkflowUpdateRequest(BaseModel):
    """Request to update a workflow."""

    name: str | None = None
    description: str | None = None
    pattern: ConversationPattern | None = None
    entry_agent_id: str | None = None
    metadata: dict[str, Any] | None = None
    topology: dict[str, Any] | None = None
    execution_strategy: str | None = None
    process: str | None = None
    tasks: list[dict[str, Any]] | None = None
    memory: dict[str, Any] | None = None
    knowledge: dict[str, Any] | None = None
    guardrails: dict[str, Any] | None = None
    tracing: dict[str, Any] | None = None
    event_listeners: list[dict[str, Any]] | None = None
    mcp_servers: list[dict[str, Any]] | None = None
    output_schema: dict[str, Any] | str | None = None
    deployment_auth_mode: str | None = None
    steps: list[WorkflowStepConfig] | None = None
    group_chat: GroupChatConfigModel | None = None
    nodes: list[WorkflowNode] | None = None
    connections: list[WorkflowConnection] | None = None


class WorkflowValidationError(BaseModel):
    """Validation error details."""

    field: str = Field(description="Field that failed validation")
    message: str = Field(description="Error message")
    error_type: str = Field(description="Type of validation error")


class WorkflowValidationResponse(BaseModel):
    """Response from workflow validation."""

    valid: bool = Field(description="Whether the workflow is valid")
    errors: list[WorkflowValidationError] = Field(
        default_factory=list, description="List of validation errors"
    )
    warnings: list[str] = Field(default_factory=list, description="List of warnings")


# Error Response
class ErrorResponse(BaseModel):
    """Structured error response."""

    error_code: str
    error_message: str
    error_type: str
    request_id: UUID
    timestamp: float
    details: Any | None = None


# Prompt Template Models
class PromptTemplateCreateRequest(BaseModel):
    """Request to create a prompt template."""

    id: str = Field(pattern=r"^[a-z0-9_]+$", description="Unique prompt identifier")
    name: str = Field(description="Prompt display name")
    description: str = Field(description="Prompt description")
    template: str = Field(description="Prompt template text with {variable} placeholders")
    variables: list[str] = Field(default_factory=list, description="List of variable names")
    category: str | None = Field(default=None, description="Optional category")


class PromptTemplateUpdateRequest(BaseModel):
    """Request to update a prompt template."""

    name: str | None = None
    description: str | None = None
    template: str | None = None
    variables: list[str] | None = None
    category: str | None = None


class PromptTemplateResponse(BaseModel):
    """Response containing prompt template information."""

    id: str
    name: str
    description: str
    template: str
    variables: list[str]
    category: str | None = None
    version: int | None = None
    etag: str | None = None
    last_updated: str | None = None


class ConfigHistoryEntry(BaseModel):
    """Single configuration history entry."""

    version: int
    etag: str
    created_at: str
    updated_by: str | None
    change_summary: str | None
    config_data: dict[str, Any]


class ConfigHistoryResponse(BaseModel):
    """Response containing configuration history."""

    config_type: str
    config_id: str
    history: list[ConfigHistoryEntry]


# API Provider Models
class APIProviderCreateRequest(BaseModel):
    """Request to create an API provider."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$", description="Unique provider identifier")
    name: str = Field(description="Provider display name")
    type: str = Field(description="Provider type (llm, tool, api)")
    description: str = Field(description="Provider description")
    base_url: str | None = Field(default=None, description="Base URL for API")
    api_key: str | None = Field(default=None, description="API key for authentication")
    api_key_env: str | None = Field(
        default=None, description="Env var holding the API key (stored as auth.env_var)"
    )
    litellm_prefix: str | None = Field(
        default=None,
        description="Native provider route prefix; leave unset for OpenAI-compatible endpoints",
    )
    models: list[dict[str, Any]] | None = Field(
        default=None, description='Model entries, e.g. [{"name": "qwen-plus"}]'
    )
    enabled: bool = Field(default=True, description="Whether provider is enabled")
    config: dict[str, Any] = Field(default_factory=dict, description="Additional configuration")


class APIProviderUpdateRequest(BaseModel):
    """Request to update an API provider."""

    name: str | None = None
    type: str | None = None
    description: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    litellm_prefix: str | None = None
    models: list[dict[str, Any]] | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None


class APIProviderResponse(BaseModel):
    """Response containing API provider information."""

    id: str
    name: str
    type: str
    description: str
    base_url: str | None = None
    api_key_masked: str | None = None
    api_key_env: str | None = None
    key_source: str | None = Field(
        default=None, description="Where the key comes from: inline | secret_store | env | none"
    )
    litellm_prefix: str | None = None
    enabled: bool
    config: dict[str, Any] = {}
    models: list[dict[str, Any]] | None = None
    version: int | None = None
    etag: str | None = None
    last_updated: str | None = None


class ConnectionTestResponse(BaseModel):
    """Response from testing API provider connection."""

    success: bool
    message: str
    live: bool = False
    latency_ms: int | None = None
    checked_endpoint: str | None = None
    model_id: str | None = None
    supports_streaming: bool | None = None
    supports_tools: bool | None = None
    details: dict[str, Any] | None = None


# Health Response
class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str
    version: str
    timestamp: float = Field(default_factory=lambda: datetime.now(UTC).timestamp())


class ToolExecutionRequest(BaseModel):
    """Request to execute a tool."""

    args: dict[str, Any] = Field(
        default_factory=dict, description="Arguments for the tool execution"
    )


class ToolExecutionResponse(BaseModel):
    """Response from tool execution."""

    status: str = Field(description="Status of execution (success/error)")
    result: Any = Field(description="Result of the tool execution")
    error: str | None = Field(default=None, description="Error message if failed")


# Topology Models
class TopologyNodeRequest(BaseModel):
    """Request model for topology node."""

    id: str = Field(description="Unique node identifier")
    agent_id: str = Field(description="Agent ID for this node")
    input_transform: str | None = Field(default=None, description="jq-style input transformation")
    output_transform: str | None = Field(default=None, description="jq-style output transformation")
    timeout: float | None = Field(default=None, description="Node-specific timeout")
    config_override: dict[str, Any] | None = Field(
        default=None, description="Node-specific config overrides"
    )


class TopologyEdgeRequest(BaseModel):
    """Request model for topology edge."""

    from_node: str = Field(description="Source node ID")
    to_node: str = Field(description="Target node ID")
    context_strategy: str = Field(
        default="full", description="Context passing strategy: full, summary, selective"
    )
    fields: list[str] | None = Field(
        default=None, description="Fields to include for selective strategy"
    )
    condition: str | None = Field(default=None, description="Conditional routing expression")


class TopologyCreateRequest(BaseModel):
    """Request to create a workflow topology."""

    workflow_id: str = Field(description="Workflow ID to attach topology to")
    type: str = Field(description="Topology type: single, sequential, tree, graph")
    nodes: list[TopologyNodeRequest] = Field(description="List of topology nodes")
    edges: list[TopologyEdgeRequest] = Field(description="List of topology edges")
    entry_node: str = Field(description="Entry node ID")
    max_iterations: int | None = Field(default=None, description="Max iterations for cyclic graphs")


class TopologyResponse(BaseModel):
    """Response containing topology information."""

    workflow_id: str
    type: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    entry_node: str
    max_iterations: int | None = None
    validation: dict[str, Any]


class TopologyValidationResponse(BaseModel):
    """Response from topology validation."""

    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WorkflowExecutionStatusResponse(BaseModel):
    """Response containing workflow execution status."""

    workflow_id: str
    active_executions: int
    max_concurrent: int
    queued_requests: int
    resource_limit_reached: bool


class ProviderCapabilitiesResponse(BaseModel):
    """What a provider's route actually honours, for studio field gating."""

    provider_id: str
    crewai_provider: str = Field(description="The declared route")
    effective_provider: str = Field(
        description="Route after native-SDK fallback; this is what the UI must gate on"
    )
    native: bool
    output_token_param: str | None = None
    supported_llm_params: list[str] = Field(default_factory=list)
    agent_params: list[str] = Field(default_factory=list)
    key_present: bool = False
    key_source: str = "none"
    api_key_env: str | None = None
