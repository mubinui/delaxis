"""Property-based tests for workflow validation."""

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from src.api.models import WorkflowConnection, WorkflowNode, WorkflowNodePosition
from src.api.workflow_validation import (
    detect_cycles,
    validate_agent_references,
    validate_connections,
    validate_workflow,
)

# Strategy for generating valid agent IDs
valid_agent_id = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=1, max_size=20
).filter(lambda x: x and not x.startswith("_") and not x.endswith("_"))


# Strategy for generating node IDs
valid_node_id = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_", min_size=1, max_size=20
).filter(lambda x: x and not x.startswith("_") and not x.endswith("_"))


# Strategy for generating workflow nodes
def workflow_node_strategy(agent_ids):
    """Generate workflow nodes with given agent IDs."""
    return st.builds(
        WorkflowNode,
        id=valid_node_id,
        agent_id=st.sampled_from(agent_ids) if agent_ids else valid_agent_id,
        position=st.builds(
            WorkflowNodePosition,
            x=st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False),
            y=st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False),
        ),
        config=st.dictionaries(
            st.text(min_size=1, max_size=10),
            st.one_of(st.text(), st.integers(), st.booleans()),
            max_size=3,
        ),
    )


# Strategy for generating workflow connections
def workflow_connection_strategy(node_ids):
    """Generate workflow connections between given node IDs."""
    if not node_ids or len(node_ids) < 2:
        return st.none()

    return st.builds(
        WorkflowConnection,
        from_node=st.sampled_from(node_ids),
        to_node=st.sampled_from(node_ids),
        type=st.sampled_from(["sequential", "parallel"]),
    )


# **Feature: config-management-ui, Property 7: Workflow validation**
@given(
    # Generate a set of available agents
    available_agents=st.lists(valid_agent_id, min_size=1, max_size=10, unique=True),
    # Generate workflow nodes that may or may not reference valid agents
    num_nodes=st.integers(min_value=1, max_value=10),
    # Some nodes will reference invalid agents
    invalid_agent_ratio=st.floats(min_value=0.0, max_value=1.0),
)
@settings(max_examples=100)
def test_workflow_agent_reference_validation(available_agents, num_nodes, invalid_agent_ratio):
    """
    Test that workflow validation correctly identifies missing agent references.

    For any workflow configuration, all referenced agent IDs in nodes should exist
    in the agents configuration. If they don't, validation should fail with specific
    error messages.

    Validates: Requirements 6.4, 8.3
    """
    # Create a set of available agents
    available_agent_set = set(available_agents)

    # Generate nodes with a mix of valid and invalid agent references
    nodes = []
    expected_invalid_agents = set()

    for i in range(num_nodes):
        node_id = f"node_{i}"

        # Decide if this node should reference an invalid agent
        if i / num_nodes < invalid_agent_ratio and len(available_agents) > 0:
            # Reference an invalid agent (one not in available_agents)
            invalid_agent = f"invalid_agent_{i}"
            expected_invalid_agents.add(invalid_agent)
            agent_id = invalid_agent
        else:
            # Reference a valid agent
            agent_id = available_agents[i % len(available_agents)]

        node = WorkflowNode(
            id=node_id,
            agent_id=agent_id,
            position=WorkflowNodePosition(x=float(i * 100), y=100.0),
            config={},
        )
        nodes.append(node)

    # Validate agent references
    errors = validate_agent_references(nodes, available_agent_set)

    # Property: If all agents are valid, there should be no errors
    if not expected_invalid_agents:
        assert len(errors) == 0, "Valid agent references should not produce errors"
    else:
        # Property: If there are invalid agents, errors should be reported
        assert len(errors) > 0, "Invalid agent references should produce errors"

        # Property: Each invalid agent should have an error
        error_agents = {
            error.message.split("'")[1] for error in errors if "not found" in error.message
        }
        assert expected_invalid_agents.issubset(error_agents), (
            f"All invalid agents should be reported. Expected: {expected_invalid_agents}, Got: {error_agents}"
        )

        # Property: Error messages should be specific
        for error in errors:
            assert error.error_type == "missing_reference", (
                "Error type should be 'missing_reference'"
            )
            assert "not found" in error.message.lower(), (
                "Error message should indicate agent not found"
            )
            assert error.field.startswith("nodes["), "Error field should reference the node"


# **Feature: config-management-ui, Property 7: Workflow validation**
@given(
    # Generate available agents
    available_agents=st.lists(valid_agent_id, min_size=2, max_size=10, unique=True),
    # Generate number of nodes
    num_nodes=st.integers(min_value=2, max_value=8),
    # Generate number of connections
    num_connections=st.integers(min_value=0, max_value=15),
)
@settings(max_examples=100)
def test_workflow_connection_validation(available_agents, num_nodes, num_connections):
    """
    Test that workflow connection validation correctly identifies invalid connections.

    For any workflow configuration, all connections should reference existing nodes.
    Invalid connections should be rejected with specific error messages.

    Validates: Requirements 6.4, 8.3
    """
    # Create nodes with valid agent references
    nodes = []
    node_ids = []

    for i in range(num_nodes):
        node_id = f"node_{i}"
        node_ids.append(node_id)
        node = WorkflowNode(
            id=node_id,
            agent_id=available_agents[i % len(available_agents)],
            position=WorkflowNodePosition(x=float(i * 100), y=100.0),
            config={},
        )
        nodes.append(node)

    # Generate connections (some may be invalid)
    connections = []
    expected_invalid_connections = 0

    for i in range(num_connections):
        # Randomly decide if this connection should be invalid
        if i % 3 == 0 and num_nodes > 0:
            # Create invalid connection (reference non-existent node)
            from_node = f"invalid_node_{i}"
            to_node = node_ids[i % len(node_ids)] if node_ids else "invalid"
            expected_invalid_connections += 1
        elif i % 5 == 0 and num_nodes > 0:
            # Create another type of invalid connection
            from_node = node_ids[i % len(node_ids)] if node_ids else "invalid"
            to_node = f"invalid_node_{i}"
            expected_invalid_connections += 1
        else:
            # Create valid connection
            if len(node_ids) >= 2:
                from_node = node_ids[i % len(node_ids)]
                to_node = node_ids[(i + 1) % len(node_ids)]
            else:
                continue

        connection = WorkflowConnection(
            from_node=from_node, to_node=to_node, type="sequential" if i % 2 == 0 else "parallel"
        )
        connections.append(connection)

    # Validate connections
    errors = validate_connections(nodes, connections)

    # Property: If all connections are valid, there should be no errors
    if expected_invalid_connections == 0:
        assert len(errors) == 0, "Valid connections should not produce errors"
    else:
        # Property: If there are invalid connections, errors should be reported
        assert len(errors) > 0, "Invalid connections should produce errors"

        # Property: Error messages should be specific
        for error in errors:
            assert error.error_type == "missing_node", "Error type should be 'missing_node'"
            assert "not found" in error.message.lower(), (
                "Error message should indicate node not found"
            )
            assert error.field.startswith("connections["), (
                "Error field should reference the connection"
            )


# **Feature: config-management-ui, Property 7: Workflow validation**
@given(
    # Generate available agents
    available_agents=st.lists(valid_agent_id, min_size=3, max_size=8, unique=True),
    # Generate number of nodes
    num_nodes=st.integers(min_value=3, max_value=8),
)
@settings(max_examples=100)
def test_workflow_complete_validation(available_agents, num_nodes):
    """
    Test complete workflow validation with valid configurations.

    For any workflow with all valid agent references and connections,
    the validation should pass without errors.

    Validates: Requirements 6.4, 8.3
    """
    # Create nodes with valid agent references
    nodes = []
    node_ids = []

    for i in range(num_nodes):
        node_id = f"node_{i}"
        node_ids.append(node_id)
        node = WorkflowNode(
            id=node_id,
            agent_id=available_agents[i % len(available_agents)],
            position=WorkflowNodePosition(x=float(i * 100), y=100.0),
            config={},
        )
        nodes.append(node)

    # Create valid connections (no cycles)
    connections = []
    for i in range(len(node_ids) - 1):
        connection = WorkflowConnection(
            from_node=node_ids[i], to_node=node_ids[i + 1], type="sequential"
        )
        connections.append(connection)

    # Validate workflow
    is_valid, errors, warnings = validate_workflow(nodes, connections, set(available_agents))

    # Property: Valid workflows should pass validation
    assert is_valid, f"Valid workflow should pass validation. Errors: {errors}"
    assert len(errors) == 0, "Valid workflow should have no errors"


# **Feature: config-management-ui, Property 7: Workflow validation**
@given(
    # Generate available agents
    available_agents=st.lists(valid_agent_id, min_size=2, max_size=5, unique=True),
    # Generate number of nodes (at least 2 for potential invalid references)
    num_nodes=st.integers(min_value=2, max_value=5),
    # Number of invalid agent references
    num_invalid=st.integers(min_value=1, max_value=3),
)
@settings(max_examples=100)
def test_workflow_validation_with_invalid_agents(available_agents, num_nodes, num_invalid):
    """
    Test workflow validation correctly rejects workflows with invalid agent references.

    For any workflow with invalid agent references, validation should fail
    and report all missing agents.

    Validates: Requirements 6.4, 8.3
    """
    assume(num_invalid <= num_nodes)

    # Create nodes with some invalid agent references
    nodes = []
    node_ids = []
    invalid_agents = set()

    for i in range(num_nodes):
        node_id = f"node_{i}"
        node_ids.append(node_id)

        # First num_invalid nodes reference invalid agents
        if i < num_invalid:
            agent_id = f"invalid_agent_{i}"
            invalid_agents.add(agent_id)
        else:
            agent_id = available_agents[i % len(available_agents)]

        node = WorkflowNode(
            id=node_id,
            agent_id=agent_id,
            position=WorkflowNodePosition(x=float(i * 100), y=100.0),
            config={},
        )
        nodes.append(node)

    # Create valid connections
    connections = []
    if len(node_ids) >= 2:
        connection = WorkflowConnection(
            from_node=node_ids[0], to_node=node_ids[1], type="sequential"
        )
        connections.append(connection)

    # Validate workflow
    is_valid, errors, warnings = validate_workflow(nodes, connections, set(available_agents))

    # Property: Workflow with invalid agents should fail validation
    assert not is_valid, "Workflow with invalid agent references should fail validation"
    assert len(errors) > 0, "Workflow with invalid agents should have errors"

    # Property: All invalid agents should be reported
    error_agents = {error.message.split("'")[1] for error in errors if "not found" in error.message}
    assert invalid_agents.issubset(error_agents), (
        f"All invalid agents should be reported. Expected: {invalid_agents}, Got: {error_agents}"
    )


def test_workflow_validation_empty_workflow():
    """Test validation of empty workflow."""
    # Empty workflow should be valid (no errors)
    is_valid, errors, warnings = validate_workflow([], [], set())
    assert is_valid
    assert len(errors) == 0


def test_workflow_validation_single_node():
    """Test validation of workflow with single node."""
    node = WorkflowNode(
        id="node_1", agent_id="agent_1", position=WorkflowNodePosition(x=100.0, y=100.0), config={}
    )

    # Valid single node
    is_valid, errors, warnings = validate_workflow([node], [], {"agent_1"})
    assert is_valid
    assert len(errors) == 0

    # Invalid single node (missing agent)
    is_valid, errors, warnings = validate_workflow(
        [node],
        [],
        {"agent_2"},  # Different agent
    )
    assert not is_valid
    assert len(errors) == 1
    assert "agent_1" in errors[0].message
    assert "not found" in errors[0].message.lower()


def test_workflow_validation_connection_to_nonexistent_node():
    """Test validation catches connections to non-existent nodes."""
    nodes = [
        WorkflowNode(
            id="node_1",
            agent_id="agent_1",
            position=WorkflowNodePosition(x=100.0, y=100.0),
            config={},
        )
    ]

    connections = [
        WorkflowConnection(
            from_node="node_1",
            to_node="node_2",  # Doesn't exist
            type="sequential",
        )
    ]

    is_valid, errors, warnings = validate_workflow(nodes, connections, {"agent_1"})

    assert not is_valid
    assert len(errors) == 1
    assert "node_2" in errors[0].message
    assert "not found" in errors[0].message.lower()
    assert errors[0].error_type == "missing_node"


def test_workflow_validation_multiple_errors():
    """Test validation reports multiple errors."""
    nodes = [
        WorkflowNode(
            id="node_1",
            agent_id="invalid_agent_1",  # Invalid
            position=WorkflowNodePosition(x=100.0, y=100.0),
            config={},
        ),
        WorkflowNode(
            id="node_2",
            agent_id="invalid_agent_2",  # Invalid
            position=WorkflowNodePosition(x=200.0, y=100.0),
            config={},
        ),
    ]

    connections = [
        WorkflowConnection(
            from_node="node_1",
            to_node="node_3",  # Doesn't exist
            type="sequential",
        )
    ]

    is_valid, errors, warnings = validate_workflow(
        nodes,
        connections,
        {"agent_1"},  # Neither invalid_agent_1 nor invalid_agent_2
    )

    assert not is_valid
    # Should have 3 errors: 2 invalid agents + 1 invalid connection
    assert len(errors) == 3

    # Check we have both types of errors
    error_types = {error.error_type for error in errors}
    assert "missing_reference" in error_types
    assert "missing_node" in error_types


# **Feature: config-management-ui, Property 13: Workflow cycle detection**
@given(
    # Generate number of nodes
    num_nodes=st.integers(min_value=2, max_value=8),
    # Generate available agents
    available_agents=st.lists(valid_agent_id, min_size=2, max_size=8, unique=True),
)
@settings(max_examples=100)
def test_workflow_cycle_detection_acyclic(num_nodes, available_agents):
    """
    Test that acyclic workflows pass validation.

    For any workflow with sequential connections that form a directed acyclic graph (DAG),
    there should be no cycles detected and validation should pass.

    Validates: Requirements 6.4
    """
    # Create nodes
    nodes = []
    node_ids = []

    for i in range(num_nodes):
        node_id = f"node_{i}"
        node_ids.append(node_id)
        node = WorkflowNode(
            id=node_id,
            agent_id=available_agents[i % len(available_agents)],
            position=WorkflowNodePosition(x=float(i * 100), y=100.0),
            config={},
        )
        nodes.append(node)

    # Create acyclic sequential connections (linear chain)
    connections = []
    for i in range(len(node_ids) - 1):
        connection = WorkflowConnection(
            from_node=node_ids[i], to_node=node_ids[i + 1], type="sequential"
        )
        connections.append(connection)

    # Detect cycles
    cycles = detect_cycles(connections)

    # Property: Acyclic graphs should have no cycles
    assert len(cycles) == 0, f"Acyclic workflow should have no cycles, but found: {cycles}"

    # Property: Workflow validation should pass
    is_valid, errors, warnings = validate_workflow(nodes, connections, set(available_agents))

    assert is_valid, f"Acyclic workflow should pass validation. Errors: {errors}"
    assert len(errors) == 0, "Acyclic workflow should have no errors"


# **Feature: config-management-ui, Property 13: Workflow cycle detection**
@given(
    # Generate number of nodes (at least 2 to form a cycle)
    num_nodes=st.integers(min_value=2, max_value=6),
    # Generate available agents
    available_agents=st.lists(valid_agent_id, min_size=2, max_size=6, unique=True),
)
@settings(max_examples=100)
def test_workflow_cycle_detection_simple_cycle(num_nodes, available_agents):
    """
    Test that simple cycles are detected.

    For any workflow with sequential connections that form a cycle,
    the cycle should be detected and validation should fail.

    Validates: Requirements 6.4
    """
    # Create nodes
    nodes = []
    node_ids = []

    for i in range(num_nodes):
        node_id = f"node_{i}"
        node_ids.append(node_id)
        node = WorkflowNode(
            id=node_id,
            agent_id=available_agents[i % len(available_agents)],
            position=WorkflowNodePosition(x=float(i * 100), y=100.0),
            config={},
        )
        nodes.append(node)

    # Create a cycle: node_0 -> node_1 -> ... -> node_n -> node_0
    connections = []
    for i in range(len(node_ids)):
        connection = WorkflowConnection(
            from_node=node_ids[i],
            to_node=node_ids[(i + 1) % len(node_ids)],  # Wrap around to create cycle
            type="sequential",
        )
        connections.append(connection)

    # Detect cycles
    cycles = detect_cycles(connections)

    # Property: Cyclic graphs should have at least one cycle detected
    assert len(cycles) > 0, "Cyclic workflow should have at least one cycle detected"

    # Property: The detected cycle should contain nodes from our workflow
    for cycle in cycles:
        assert len(cycle) >= 2, "Cycle should contain at least 2 nodes"
        # All nodes in cycle should be from our node_ids
        for node in cycle[:-1]:  # Exclude last node (duplicate of first)
            assert node in node_ids, f"Cycle node {node} should be in workflow nodes"

    # Property: Workflow validation should fail due to cycle
    is_valid, errors, warnings = validate_workflow(nodes, connections, set(available_agents))

    assert not is_valid, "Cyclic workflow should fail validation"
    assert len(errors) > 0, "Cyclic workflow should have errors"

    # Property: Should have cycle_detected error
    cycle_errors = [e for e in errors if e.error_type == "cycle_detected"]
    assert len(cycle_errors) > 0, "Should have at least one cycle_detected error"


# **Feature: config-management-ui, Property 13: Workflow cycle detection**
@given(
    # Generate number of nodes
    num_nodes=st.integers(min_value=3, max_value=8),
    # Generate available agents
    available_agents=st.lists(valid_agent_id, min_size=3, max_size=8, unique=True),
)
@settings(max_examples=100)
def test_workflow_parallel_connections_no_cycle(num_nodes, available_agents):
    """
    Test that parallel connections do not contribute to cycle detection.

    For any workflow, parallel connections should be ignored in cycle detection,
    and only sequential connections should be considered.

    Validates: Requirements 6.4
    """
    # Create nodes
    nodes = []
    node_ids = []

    for i in range(num_nodes):
        node_id = f"node_{i}"
        node_ids.append(node_id)
        node = WorkflowNode(
            id=node_id,
            agent_id=available_agents[i % len(available_agents)],
            position=WorkflowNodePosition(x=float(i * 100), y=100.0),
            config={},
        )
        nodes.append(node)

    # Create parallel connections that would form a cycle if they were sequential
    connections = []
    for i in range(len(node_ids)):
        connection = WorkflowConnection(
            from_node=node_ids[i],
            to_node=node_ids[(i + 1) % len(node_ids)],
            type="parallel",  # Parallel, not sequential
        )
        connections.append(connection)

    # Detect cycles
    cycles = detect_cycles(connections)

    # Property: Parallel connections should not form cycles
    assert len(cycles) == 0, f"Parallel connections should not create cycles, but found: {cycles}"

    # Property: Workflow validation should pass (no cycles from parallel connections)
    is_valid, errors, warnings = validate_workflow(nodes, connections, set(available_agents))

    assert is_valid, (
        f"Workflow with only parallel connections should pass validation. Errors: {errors}"
    )

    # Property: Should have no cycle_detected errors
    cycle_errors = [e for e in errors if e.error_type == "cycle_detected"]
    assert len(cycle_errors) == 0, "Should have no cycle_detected errors for parallel connections"


# **Feature: config-management-ui, Property 13: Workflow cycle detection**
@given(
    # Generate number of nodes (at least 4 for complex graph)
    num_nodes=st.integers(min_value=4, max_value=7),
    # Generate available agents
    available_agents=st.lists(valid_agent_id, min_size=4, max_size=7, unique=True),
    # Generate cycle position (where to inject the cycle)
    cycle_start=st.integers(min_value=0, max_value=3),
)
@settings(max_examples=100)
def test_workflow_cycle_detection_mixed_connections(num_nodes, available_agents, cycle_start):
    """
    Test cycle detection with mixed sequential and parallel connections.

    For any workflow with both sequential and parallel connections,
    cycles should only be detected in the sequential connections.

    Validates: Requirements 6.4
    """
    assume(cycle_start < num_nodes - 1)

    # Create nodes
    nodes = []
    node_ids = []

    for i in range(num_nodes):
        node_id = f"node_{i}"
        node_ids.append(node_id)
        node = WorkflowNode(
            id=node_id,
            agent_id=available_agents[i % len(available_agents)],
            position=WorkflowNodePosition(x=float(i * 100), y=100.0),
            config={},
        )
        nodes.append(node)

    # Create a mix of connections with a cycle in sequential connections
    connections = []

    # Add some acyclic sequential connections
    for i in range(cycle_start):
        connection = WorkflowConnection(
            from_node=node_ids[i], to_node=node_ids[i + 1], type="sequential"
        )
        connections.append(connection)

    # Add a cycle in sequential connections
    if cycle_start + 2 < num_nodes:
        # Create a small cycle: cycle_start -> cycle_start+1 -> cycle_start+2 -> cycle_start
        connections.append(
            WorkflowConnection(
                from_node=node_ids[cycle_start],
                to_node=node_ids[cycle_start + 1],
                type="sequential",
            )
        )
        connections.append(
            WorkflowConnection(
                from_node=node_ids[cycle_start + 1],
                to_node=node_ids[cycle_start + 2],
                type="sequential",
            )
        )
        connections.append(
            WorkflowConnection(
                from_node=node_ids[cycle_start + 2],
                to_node=node_ids[cycle_start],
                type="sequential",
            )
        )

    # Add some parallel connections (should not affect cycle detection)
    for i in range(num_nodes - 1):
        connection = WorkflowConnection(
            from_node=node_ids[i], to_node=node_ids[(i + 2) % num_nodes], type="parallel"
        )
        connections.append(connection)

    # Detect cycles
    cycles = detect_cycles(connections)

    # Property: Should detect the cycle in sequential connections
    if cycle_start + 2 < num_nodes:
        assert len(cycles) > 0, "Should detect cycle in sequential connections"

        # Property: Workflow validation should fail
        is_valid, errors, warnings = validate_workflow(nodes, connections, set(available_agents))

        assert not is_valid, "Workflow with cycle should fail validation"

        # Property: Should have cycle_detected error
        cycle_errors = [e for e in errors if e.error_type == "cycle_detected"]
        assert len(cycle_errors) > 0, "Should have cycle_detected error"


def test_workflow_cycle_detection_self_loop():
    """Test detection of self-loop (node connecting to itself)."""
    nodes = [
        WorkflowNode(
            id="node_1",
            agent_id="agent_1",
            position=WorkflowNodePosition(x=100.0, y=100.0),
            config={},
        )
    ]

    connections = [
        WorkflowConnection(
            from_node="node_1",
            to_node="node_1",  # Self-loop
            type="sequential",
        )
    ]

    # Detect cycles
    cycles = detect_cycles(connections)

    # Should detect the self-loop as a cycle
    assert len(cycles) > 0, "Self-loop should be detected as a cycle"

    # Validate workflow
    is_valid, errors, warnings = validate_workflow(nodes, connections, {"agent_1"})

    assert not is_valid, "Workflow with self-loop should fail validation"
    cycle_errors = [e for e in errors if e.error_type == "cycle_detected"]
    assert len(cycle_errors) > 0, "Should have cycle_detected error for self-loop"


def test_workflow_cycle_detection_no_connections():
    """Test that workflow with no connections has no cycles."""
    nodes = [
        WorkflowNode(
            id="node_1",
            agent_id="agent_1",
            position=WorkflowNodePosition(x=100.0, y=100.0),
            config={},
        ),
        WorkflowNode(
            id="node_2",
            agent_id="agent_2",
            position=WorkflowNodePosition(x=200.0, y=100.0),
            config={},
        ),
    ]

    connections = []

    # Detect cycles
    cycles = detect_cycles(connections)

    # Should have no cycles
    assert len(cycles) == 0, "Workflow with no connections should have no cycles"

    # Validate workflow
    is_valid, errors, warnings = validate_workflow(nodes, connections, {"agent_1", "agent_2"})

    assert is_valid, "Workflow with no connections should pass validation"
    assert len(errors) == 0, "Should have no errors"
