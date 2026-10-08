"""Workflow validation logic for visual builder."""

from collections.abc import Sequence
from typing import Protocol

from src.api.models import (
    WorkflowConnection,
    WorkflowNode,
    WorkflowValidationError,
)


class NodeLike(Protocol):
    """What the validators read from a node: canvas shims and WorkflowNode alike."""

    id: str
    agent_id: str


class ConnectionLike(Protocol):
    """What the validators read from a connection."""

    from_node: str
    to_node: str
    type: str


def detect_cycles(connections: Sequence[ConnectionLike]) -> list[list[str]]:
    """
    Detect cycles in workflow connections using DFS.

    Args:
        connections: List of workflow connections

    Returns:
        List of cycles, where each cycle is a list of node IDs
    """
    # Build adjacency list for sequential connections only
    graph: dict[str, list[str]] = {}
    for conn in connections:
        if conn.type == "sequential":
            if conn.from_node not in graph:
                graph[conn.from_node] = []
            graph[conn.from_node].append(conn.to_node)

    cycles: list[list[str]] = []
    visited: set[str] = set()
    rec_stack: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> bool:
        """DFS helper to detect cycles."""
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        if node in graph:
            for neighbor in graph[node]:
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])
                    return True

        path.pop()
        rec_stack.remove(node)
        return False

    # Check all nodes
    for node in graph:
        if node not in visited:
            dfs(node)

    return cycles


def validate_agent_references(
    nodes: Sequence[NodeLike], available_agents: set[str]
) -> list[WorkflowValidationError]:
    """
    Validate that all agent references in nodes exist.

    Args:
        nodes: List of workflow nodes
        available_agents: Set of available agent IDs

    Returns:
        List of validation errors
    """
    errors: list[WorkflowValidationError] = []

    for node in nodes:
        if node.agent_id not in available_agents:
            errors.append(
                WorkflowValidationError(
                    field=f"nodes[{node.id}].agent_id",
                    message=f"Agent '{node.agent_id}' not found",
                    error_type="missing_reference",
                )
            )

    return errors


def validate_connections(
    nodes: Sequence[NodeLike], connections: Sequence[ConnectionLike]
) -> list[WorkflowValidationError]:
    """
    Validate workflow connections.

    Args:
        nodes: List of workflow nodes
        connections: List of workflow connections

    Returns:
        List of validation errors
    """
    errors: list[WorkflowValidationError] = []
    node_ids = {node.id for node in nodes}

    for i, conn in enumerate(connections):
        # Check if from_node exists
        if conn.from_node not in node_ids:
            errors.append(
                WorkflowValidationError(
                    field=f"connections[{i}].from_node",
                    message=f"Node '{conn.from_node}' not found",
                    error_type="missing_node",
                )
            )

        # Check if to_node exists
        if conn.to_node not in node_ids:
            errors.append(
                WorkflowValidationError(
                    field=f"connections[{i}].to_node",
                    message=f"Node '{conn.to_node}' not found",
                    error_type="missing_node",
                )
            )

        # Check connection type
        if conn.type not in ["sequential", "parallel"]:
            errors.append(
                WorkflowValidationError(
                    field=f"connections[{i}].type",
                    message=f"Invalid connection type '{conn.type}'. Must be 'sequential' or 'parallel'",
                    error_type="invalid_value",
                )
            )

    return errors


def validate_workflow(
    nodes: list[WorkflowNode], connections: list[WorkflowConnection], available_agents: set[str]
) -> tuple[bool, list[WorkflowValidationError], list[str]]:
    """
    Validate a complete workflow configuration.

    Args:
        nodes: List of workflow nodes
        connections: List of workflow connections
        available_agents: Set of available agent IDs

    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    errors: list[WorkflowValidationError] = []
    warnings: list[str] = []

    # Validate agent references
    errors.extend(validate_agent_references(nodes, available_agents))

    # Validate connections
    errors.extend(validate_connections(nodes, connections))

    # Detect cycles in sequential connections
    cycles = detect_cycles(connections)
    if cycles:
        for cycle in cycles:
            errors.append(
                WorkflowValidationError(
                    field="connections",
                    message=f"Cycle detected: {' -> '.join(cycle)}",
                    error_type="cycle_detected",
                )
            )

    # Check for disconnected nodes
    connected_nodes = set()
    for conn in connections:
        connected_nodes.add(conn.from_node)
        connected_nodes.add(conn.to_node)

    disconnected = {node.id for node in nodes} - connected_nodes
    if disconnected:
        warnings.append(f"Disconnected nodes: {', '.join(disconnected)}")

    is_valid = len(errors) == 0
    return is_valid, errors, warnings
