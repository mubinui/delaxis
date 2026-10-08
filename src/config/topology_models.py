"""CrewAI workflow topology models.

These models describe graph-style crews and flows in product configuration.
The runtime maps them into CrewAI agents, tasks, process modes, and traceable
execution plans while keeping the REST API stable.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator


class TopologyType(StrEnum):
    """Type of workflow topology."""

    SINGLE = "single"
    SEQUENTIAL = "sequential"
    TREE = "tree"
    GRAPH = "graph"


class ContextStrategy(StrEnum):
    """Strategy for passing context between agents."""

    FULL = "full"  # Pass complete conversation history
    SUMMARY = "summary"  # Pass summarized context
    SELECTIVE = "selective"  # Pass selected fields only


class TerminationConditionType(StrEnum):
    """Type of termination condition."""

    MAX_ITERATIONS = "max_iterations"
    MESSAGE_PATTERN = "message_pattern"
    AGENT_DECISION = "agent_decision"
    TIMEOUT = "timeout"
    MAX_ROUTING_ATTEMPTS = "max_routing_attempts"


class AgentNode(BaseModel):
    """Represents a single agent in the workflow graph."""

    # The Studio writes canvas-only keys (and may add more); they must survive a
    # load/save cycle rather than vanish the first time a config is re-serialised.
    model_config = ConfigDict(extra="allow")

    id: str = Field(pattern=r"^[a-z0-9_-]+$", description="Unique node identifier")
    description: str = Field(default="", description="What this node does, for the canvas")
    position: dict[str, float] | None = Field(
        default=None, description="Canvas position {x, y}; absent for configs written by hand"
    )
    agent_id: str = Field(
        pattern=r"^[a-z0-9_]+$", description="ID of the agent to execute at this node"
    )
    is_router: bool = Field(
        default=False,
        description="Whether this node performs routing/selection for downstream agents",
    )
    config_override: dict[str, Any] | None = Field(
        default=None, description="Optional configuration overrides for this node"
    )
    input_transform: str | None = Field(
        default=None, description="jq-style transformation for input (e.g., '.topics[0]')"
    )
    output_transform: str | None = Field(
        default=None, description="jq-style transformation for output (e.g., '.plan')"
    )
    timeout: float | None = Field(
        default=None, gt=0, description="Node-specific timeout in seconds"
    )
    tools: list[str] = Field(
        default_factory=list,
        description="Extra tool ids attached to this node via the canvas Tools handle",
    )
    memory: bool | None = Field(
        default=None,
        description="Per-node memory attachment; None inherits the workflow-level setting",
    )
    knowledge: bool | None = Field(
        default=None,
        description="Per-node knowledge attachment; None inherits the workflow-level setting",
    )

    @field_validator("id", "agent_id")
    @classmethod
    def validate_ids(cls, v: str) -> str:
        """Validate ID format."""
        if not v or not v.strip():
            raise ValueError("ID cannot be empty")
        return v


class AgentEdge(BaseModel):
    """Represents connection between two agents."""

    # Canvas edges carry `source`/`target` next to `from_node`/`to_node`.
    model_config = ConfigDict(extra="allow")

    from_node: str = Field(description="Source node ID")
    to_node: str = Field(description="Destination node ID")
    condition: str | dict[str, Any] | None = Field(
        default=None,
        description="Optional condition for conditional routing (Python expression or condition dict)",
    )
    context_strategy: ContextStrategy = Field(
        default=ContextStrategy.FULL, description="Strategy for passing context"
    )
    fields: list[str] | None = Field(
        default=None, description="Fields to include when using selective context strategy"
    )

    @field_validator("from_node", "to_node")
    @classmethod
    def validate_node_ids(cls, v: str) -> str:
        """Validate node ID format."""
        if not v or not v.strip():
            raise ValueError("Node ID cannot be empty")
        return v

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, v: list[str] | None, info: ValidationInfo) -> list[str] | None:
        """Validate fields are required for selective strategy."""
        context_strategy = info.data.get("context_strategy")
        if context_strategy == ContextStrategy.SELECTIVE and not v:
            raise ValueError("fields must be specified when using selective context strategy")
        return v


class TerminationCondition(BaseModel):
    """Termination condition for graph topologies."""

    type: TerminationConditionType = Field(description="Type of termination condition")
    value: Any = Field(description="Value for the condition (e.g., max iterations, regex pattern)")

    @field_validator("value")
    @classmethod
    def validate_value(cls, v: Any, info: ValidationInfo) -> Any:
        """Validate value based on condition type."""
        condition_type = info.data.get("type")

        if condition_type == TerminationConditionType.MAX_ITERATIONS:
            if not isinstance(v, int) or v < 1:
                raise ValueError("max_iterations value must be a positive integer")
        elif condition_type == TerminationConditionType.MESSAGE_PATTERN:
            if not isinstance(v, str):
                raise ValueError("message_pattern value must be a string")
        elif condition_type == TerminationConditionType.TIMEOUT:
            if not isinstance(v, (int, float)) or v <= 0:
                raise ValueError("timeout value must be a positive number")
        elif condition_type == TerminationConditionType.MAX_ROUTING_ATTEMPTS:
            if not isinstance(v, int) or v < 1:
                raise ValueError("max_routing_attempts value must be a positive integer")

        return v


class TopologyConfig(BaseModel):
    """Workflow topology configuration."""

    type: TopologyType = Field(description="Type of topology")
    nodes: list[AgentNode] = Field(min_length=1, description="List of agent nodes in the topology")
    edges: list[AgentEdge] = Field(
        default_factory=list, description="List of edges connecting nodes"
    )
    entry_node: str = Field(description="ID of the entry node where execution starts")
    termination_conditions: list[TerminationCondition] = Field(
        default_factory=list, description="Termination conditions for the topology"
    )

    @field_validator("entry_node")
    @classmethod
    def validate_entry_node(cls, v: str, info: ValidationInfo) -> str:
        """Validate entry node exists in nodes list."""
        nodes = info.data.get("nodes", [])
        node_ids = [node.id for node in nodes]
        if v not in node_ids:
            raise ValueError(f"entry_node '{v}' not found in nodes list")
        return v

    @field_validator("edges")
    @classmethod
    def validate_edges(cls, v: list[AgentEdge], info: ValidationInfo) -> list[AgentEdge]:
        """Validate edges reference existing nodes."""
        nodes = info.data.get("nodes", [])
        node_ids = {node.id for node in nodes}

        for edge in v:
            if edge.from_node not in node_ids:
                raise ValueError(f"Edge from_node '{edge.from_node}' not found in nodes")
            if edge.to_node not in node_ids:
                raise ValueError(f"Edge to_node '{edge.to_node}' not found in nodes")

        return v

    def validate_topology(self) -> list[str]:
        """
        Validate topology structure and return list of validation errors.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        # Build adjacency list
        adjacency: dict[str, list[str]] = {node.id: [] for node in self.nodes}
        for edge in self.edges:
            adjacency[edge.from_node].append(edge.to_node)

        # Check for unreachable nodes (except for single node topology)
        if self.type != TopologyType.SINGLE:
            reachable = self._get_reachable_nodes(self.entry_node, adjacency)
            unreachable = set(adjacency.keys()) - reachable
            if unreachable:
                errors.append(f"Unreachable nodes detected: {unreachable}")

        # Validate topology-specific constraints
        if self.type == TopologyType.SINGLE:
            if len(self.nodes) != 1:
                errors.append(f"Single topology must have exactly 1 node, got {len(self.nodes)}")
            if len(self.edges) > 0:
                errors.append(f"Single topology must have 0 edges, got {len(self.edges)}")

        elif self.type == TopologyType.SEQUENTIAL:
            if len(self.edges) != len(self.nodes) - 1:
                errors.append(
                    f"Sequential topology must have n-1 edges for n nodes, "
                    f"got {len(self.edges)} edges for {len(self.nodes)} nodes"
                )
            # Check for cycles
            if self._has_cycle(adjacency):
                errors.append("Sequential topology cannot have cycles")

        elif self.type == TopologyType.TREE:
            # Check for cycles
            if self._has_cycle(adjacency):
                errors.append("Tree topology cannot have cycles")
            # Check that each node (except entry) has exactly one parent
            in_degree = {node.id: 0 for node in self.nodes}
            for edge in self.edges:
                in_degree[edge.to_node] += 1
            for node_id, degree in in_degree.items():
                if node_id != self.entry_node and degree != 1:
                    errors.append(
                        f"Tree topology: node '{node_id}' has {degree} parents, expected 1"
                    )

        elif self.type == TopologyType.GRAPH:
            # Graph can have cycles, but must have termination conditions
            if self._has_cycle(adjacency) and not self.termination_conditions:
                errors.append("Graph topology with cycles must have termination conditions")

        return errors

    def _get_reachable_nodes(self, start: str, adjacency: dict[str, list[str]]) -> set[str]:
        """Get all nodes reachable from start node using BFS."""
        visited = {start}
        queue = [start]

        while queue:
            current = queue.pop(0)
            for neighbor in adjacency.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        return visited

    def _has_cycle(self, adjacency: dict[str, list[str]]) -> bool:
        """Check if graph has a cycle using DFS."""
        visited = set()
        rec_stack = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)

            for neighbor in adjacency.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    return True

            rec_stack.remove(node)
            return False

        for node in adjacency:
            if node not in visited:
                if dfs(node):
                    return True

        return False
