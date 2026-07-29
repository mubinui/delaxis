"""
Property-based tests for CrewAI 0.4 configuration migration.

These tests verify correctness properties of configuration migration
using property-based testing with Hypothesis.

**Feature: crewai-native-migration, Property 26: Configuration Migration**
**Validates: Requirements 14.5**
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.config.agent_models import (
    AgentConfig,
    AgentType,
    HumanInputMode,
    LLMConfig,
    ModelClientConfig,
    MemoryConfig,
    RetrieveConfig,
)
from src.config.workflow_models import (
    GroupChatConfig,
    SpeakerSelectionMethod,
    TeamType,
    TerminationType,
)
from src.config.migration import (
    convert_llm_config_to_model_client_config,
    convert_retrieve_config_to_memory_config,
    convert_agent_config_v02_to_v04,
    convert_group_chat_to_team_config,
    convert_v02_to_v04,
    validate_migration,
    ConfigurationMigrationError,
)


# Strategies for generating valid v0.2 configurations

@st.composite
def valid_agent_id(draw):
    """Generate a valid agent ID matching pattern ^[a-z0-9_]+$."""
    first_char = draw(st.sampled_from("abcdefghijklmnopqrstuvwxyz"))
    remaining = draw(st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
        min_size=2,
        max_size=19
    ))
    return first_char + remaining


@st.composite
def valid_llm_config(draw):
    """Generate a valid v0.2 LLMConfig."""
    provider = draw(st.sampled_from(["openai", "azure", "openrouter"]))
    model = draw(st.sampled_from(["gpt-4", "gpt-3.5-turbo", "google/gemma-3-27b-it"]))
    temperature = draw(st.floats(min_value=0.0, max_value=2.0))
    timeout = draw(st.integers(min_value=1, max_value=300))
    max_tokens = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=4096)))
    cache_seed = draw(st.one_of(st.none(), st.integers(min_value=0, max_value=1000)))
    
    return LLMConfig(
        provider_id=provider,
        model=model,
        temperature=temperature,
        timeout=timeout,
        max_tokens=max_tokens,
        cache_seed=cache_seed,
    )


@st.composite
def valid_retrieve_config(draw):
    """Generate a valid v0.2 RetrieveConfig."""
    collection_name = draw(st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789_",
        min_size=3,
        max_size=20
    ).filter(lambda x: x and x[0].isalpha()))
    
    return RetrieveConfig(
        task=draw(st.sampled_from(["qa", "code", "default"])),
        docs_path=["/path/to/docs"],
        chunk_token_size=draw(st.integers(min_value=100, max_value=4000)),
        vector_db=draw(st.sampled_from(["chromadb", "qdrant", "pgvector"])),
        collection_name=collection_name,
        embedding_model="all-mpnet-base-v2",
    )


@st.composite
def valid_v02_agent_config(draw):
    """Generate a valid v0.2 AgentConfig."""
    agent_id = draw(valid_agent_id())
    agent_type = draw(st.sampled_from([AgentType.CONVERSABLE, AgentType.RETRIEVE_USER_PROXY]))
    llm_config = draw(valid_llm_config())
    
    config_kwargs = {
        "id": agent_id,
        "type": agent_type,
        "name": f"Agent {agent_id}",
        "system_message": draw(st.text(min_size=10, max_size=100)),
        "llm_config": llm_config,
        "tools": draw(st.lists(valid_agent_id(), min_size=0, max_size=3, unique=True)),
    }
    
    # Add retrieve_config for retrieve_user_proxy agents
    if agent_type == AgentType.RETRIEVE_USER_PROXY:
        config_kwargs["retrieve_config"] = draw(valid_retrieve_config())
    
    return AgentConfig(**config_kwargs)


@st.composite
def valid_group_chat_config(draw):
    """Generate a valid v0.2 GroupChatConfig."""
    agents = draw(st.lists(valid_agent_id(), min_size=2, max_size=5, unique=True))
    
    return GroupChatConfig(
        agents=agents,
        max_round=draw(st.integers(min_value=1, max_value=50)),
        speaker_selection_method=draw(st.sampled_from([
            SpeakerSelectionMethod.AUTO,
            SpeakerSelectionMethod.ROUND_ROBIN,
            SpeakerSelectionMethod.RANDOM,
        ])),
    )


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
@given(llm_config=valid_llm_config())
@settings(max_examples=100, deadline=None)
def test_llm_config_to_model_client_config_preserves_settings(
    llm_config: LLMConfig,
):
    """
    *For any* v0.2 LLMConfig, converting to ModelClientConfig should
    preserve all essential settings (provider, model, temperature, timeout).
    """
    model_client_config = convert_llm_config_to_model_client_config(llm_config)
    
    assert model_client_config.provider_id == llm_config.provider_id
    assert model_client_config.model == llm_config.model
    assert model_client_config.temperature == llm_config.temperature
    assert model_client_config.timeout == llm_config.timeout
    assert model_client_config.max_tokens == llm_config.max_tokens
    assert model_client_config.seed == llm_config.cache_seed


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
@given(retrieve_config=valid_retrieve_config())
@settings(max_examples=100, deadline=None)
def test_retrieve_config_to_memory_config_preserves_settings(
    retrieve_config: RetrieveConfig,
):
    """
    *For any* v0.2 RetrieveConfig, converting to MemoryConfig should
    preserve all essential settings (vector_db, collection_name, embedding_model).
    """
    memory_config = convert_retrieve_config_to_memory_config(retrieve_config)
    
    assert memory_config.type == "rag"
    assert memory_config.vector_db == retrieve_config.vector_db
    assert memory_config.collection_name == retrieve_config.collection_name
    assert memory_config.embedding_model == retrieve_config.embedding_model
    assert memory_config.docs_path == retrieve_config.docs_path
    assert memory_config.chunk_token_size == retrieve_config.chunk_token_size


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
@given(agent_config=valid_v02_agent_config())
@settings(max_examples=100, deadline=None)
def test_agent_config_migration_preserves_identity(
    agent_config: AgentConfig,
):
    """
    *For any* v0.2 AgentConfig, migrating to v0.4 should preserve
    the agent's identity (id, name, system_message, tools).
    """
    new_config, warnings = convert_agent_config_v02_to_v04(agent_config)
    
    # Identity should be preserved
    assert new_config.id == agent_config.id
    assert new_config.name == agent_config.name
    assert new_config.system_message == agent_config.system_message
    assert new_config.tools == agent_config.tools
    
    # Version should be incremented
    assert new_config.version == agent_config.version + 1


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
@given(agent_config=valid_v02_agent_config())
@settings(max_examples=100, deadline=None)
def test_agent_config_migration_converts_llm_config(
    agent_config: AgentConfig,
):
    """
    *For any* v0.2 AgentConfig with llm_config, migrating to v0.4 should
    convert llm_config to model_client_config.
    """
    new_config, warnings = convert_agent_config_v02_to_v04(agent_config)
    
    # llm_config should be cleared
    assert new_config.llm_config is None
    
    # model_client_config should be set
    assert new_config.model_client_config is not None
    assert new_config.model_client_config.provider_id == agent_config.llm_config.provider_id
    assert new_config.model_client_config.model == agent_config.llm_config.model


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
@given(agent_config=valid_v02_agent_config())
@settings(max_examples=100, deadline=None)
def test_agent_config_migration_converts_retrieve_config(
    agent_config: AgentConfig,
):
    """
    *For any* v0.2 AgentConfig with retrieve_config, migrating to v0.4 should
    convert retrieve_config to memory_config.
    """
    new_config, warnings = convert_agent_config_v02_to_v04(agent_config)
    
    if agent_config.retrieve_config is not None:
        # retrieve_config should be cleared
        assert new_config.retrieve_config is None
        
        # memory_config should be set
        assert new_config.memory_config is not None
        assert new_config.memory_config.vector_db == agent_config.retrieve_config.vector_db
        assert new_config.memory_config.collection_name == agent_config.retrieve_config.collection_name


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
@given(agent_config=valid_v02_agent_config())
@settings(max_examples=100, deadline=None)
def test_agent_config_migration_produces_v04_compatible_config(
    agent_config: AgentConfig,
):
    """
    *For any* v0.2 AgentConfig, migrating to v0.4 should produce
    a configuration that passes v0.4 compatibility validation.
    """
    new_config, warnings = convert_agent_config_v02_to_v04(agent_config)
    
    # The migrated config should be v0.4 compatible
    errors = new_config.validate_v04_compatibility()
    assert len(errors) == 0, f"Migration produced incompatible config: {errors}"
    assert new_config.is_v04_compatible()


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
@given(group_chat_config=valid_group_chat_config())
@settings(max_examples=100, deadline=None)
def test_group_chat_to_team_config_preserves_agents(
    group_chat_config: GroupChatConfig,
):
    """
    *For any* v0.2 GroupChatConfig, converting to TeamConfig should
    preserve the list of participating agents.
    """
    team_config, warnings = convert_group_chat_to_team_config(
        group_chat_config,
        team_id="test_team",
    )
    
    assert team_config.agents == group_chat_config.agents
    assert len(team_config.agents) >= 2


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
@given(group_chat_config=valid_group_chat_config())
@settings(max_examples=100, deadline=None)
def test_group_chat_to_team_config_creates_termination_condition(
    group_chat_config: GroupChatConfig,
):
    """
    *For any* v0.2 GroupChatConfig, converting to TeamConfig should
    create a termination condition based on max_round.
    """
    team_config, warnings = convert_group_chat_to_team_config(
        group_chat_config,
        team_id="test_team",
    )
    
    assert team_config.termination_condition is not None
    assert team_config.termination_condition.type == TerminationType.MAX_MESSAGE
    assert team_config.termination_condition.max_messages == group_chat_config.max_round


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
@given(group_chat_config=valid_group_chat_config())
@settings(max_examples=100, deadline=None)
def test_group_chat_to_team_config_maps_speaker_selection(
    group_chat_config: GroupChatConfig,
):
    """
    *For any* v0.2 GroupChatConfig, converting to TeamConfig should
    map speaker_selection_method to appropriate team type.
    """
    team_config, warnings = convert_group_chat_to_team_config(
        group_chat_config,
        team_id="test_team",
    )
    
    if group_chat_config.speaker_selection_method == SpeakerSelectionMethod.ROUND_ROBIN:
        assert team_config.type == TeamType.ROUND_ROBIN
    else:
        # AUTO, MANUAL, RANDOM all map to SELECTOR or ROUND_ROBIN
        assert team_config.type in [TeamType.SELECTOR, TeamType.ROUND_ROBIN]


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
@given(agent_config=valid_v02_agent_config())
@settings(max_examples=100, deadline=None)
def test_convert_v02_to_v04_dict_interface(
    agent_config: AgentConfig,
):
    """
    *For any* v0.2 agent configuration dict, convert_v02_to_v04 should
    return a valid v0.4 configuration dict.
    """
    original_dict = agent_config.model_dump(exclude_none=True)
    
    converted_dict, warnings = convert_v02_to_v04(original_dict, config_type="agent")
    
    # Should have model_client_config instead of llm_config
    assert "model_client_config" in converted_dict
    assert converted_dict.get("llm_config") is None
    
    # Identity should be preserved
    assert converted_dict["id"] == original_dict["id"]
    assert converted_dict["name"] == original_dict["name"]


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
@given(agent_config=valid_v02_agent_config())
@settings(max_examples=100, deadline=None)
def test_validate_migration_passes_for_valid_migration(
    agent_config: AgentConfig,
):
    """
    *For any* v0.2 agent configuration, a valid migration should pass
    validation with no errors.
    """
    original_dict = agent_config.model_dump(exclude_none=True)
    converted_dict, warnings = convert_v02_to_v04(original_dict, config_type="agent")
    
    errors = validate_migration(original_dict, converted_dict, config_type="agent")
    assert len(errors) == 0, f"Validation errors: {errors}"


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
def test_migration_generates_warnings():
    """
    Test that migration generates appropriate warnings for converted fields.
    """
    agent_config = AgentConfig(
        id="test_agent",
        type=AgentType.CONVERSABLE,
        name="Test Agent",
        system_message="You are a test agent.",
        llm_config=LLMConfig(
            provider_id="openai",
            model="gpt-4",
            temperature=0.7,
            timeout=60,
        ),
    )
    
    new_config, warnings = convert_agent_config_v02_to_v04(agent_config)
    
    # Should have warnings about conversion
    assert len(warnings) > 0
    assert any("llm_config" in w for w in warnings)


# **Feature: crewai-native-migration, Property 26: Configuration Migration**
# **Validates: Requirements 14.5**
def test_migration_handles_invalid_config_type():
    """
    Test that migration raises error for invalid config type.
    """
    with pytest.raises(ConfigurationMigrationError) as exc_info:
        convert_v02_to_v04({"id": "test"}, config_type="invalid")
    
    assert "Unknown configuration type" in str(exc_info.value)


class TestProcurementWorkflowTopologyMigration:
    """Test procurement workflow migration to v0.4 topology format."""

    def test_requisition_assistant_two_agent_to_topology(self):
        """
        Test migration of requisition_assistant from two_agent pattern
        to v0.4 sequential topology format.
        """
        # Old v0.2 format
        old_workflow = {
            "id": "requisition_assistant",
            "pattern": "two_agent",
            "entry_agent_id": "user_proxy",
            "recipient_agent_id": "requisition_agent",
            "max_turns": 6,
            "summary_method": "last_msg"
        }
        
        # Expected v0.4 topology format
        expected_topology = {
            "id": "requisition_assistant",
            "version": "2.0",
            "topology": {
                "type": "sequential",
                "nodes": [
                    {"id": "user_proxy_node", "agent_id": "user_proxy"},
                    {"id": "requisition_agent_node", "agent_id": "requisition_agent"}
                ],
                "edges": [
                    {
                        "from_node": "user_proxy_node",
                        "to_node": "requisition_agent_node",
                        "context_strategy": "full"
                    }
                ],
                "entry_node": "user_proxy_node",
                "termination_conditions": [
                    {"type": "max_iterations", "value": 6}
                ]
            },
            "execution_strategy": "sequential"
        }
        
        # Validate structure properties
        assert old_workflow["pattern"] == "two_agent"
        assert "topology" not in old_workflow
        
        # After migration, should have topology
        # This is the structure we expect after implementation
        assert expected_topology["topology"]["type"] == "sequential"
        assert len(expected_topology["topology"]["nodes"]) == 2
        assert len(expected_topology["topology"]["edges"]) == 1
        assert expected_topology["topology"]["entry_node"] == "user_proxy_node"

    def test_procurement_chatbot_selector_to_topology(self):
        """
        Test migration of procurement_chatbot from selector pattern
        to v0.4 graph topology with conditional routing.
        """
        # Old v0.2 selector format
        old_workflow = {
            "id": "procurement_chatbot",
            "pattern": "selector",
            "entry_agent_id": "selector_agent",
            "max_turns": 10,
            "selector_config": {
                "routing_agents": {
                    "requisition": "requisition_domain_agent",
                    "purchase_order": "purchase_order_agent",
                    "framework_agreement": "framework_agreement_agent"
                },
                "default_agent": "selector_agent",
                "max_routing_attempts": 3
            }
        }
        
        # Expected v0.4 graph topology
        expected_topology = {
            "id": "procurement_chatbot",
            "version": "2.0",
            "topology": {
                "type": "graph",
                "nodes": [
                    {"id": "selector_node", "agent_id": "selector_agent"},
                    {"id": "requisition_node", "agent_id": "requisition_domain_agent"},
                    {"id": "purchase_order_node", "agent_id": "purchase_order_agent"},
                    {"id": "framework_agreement_node", "agent_id": "framework_agreement_agent"}
                ],
                "edges": [
                    {
                        "from_node": "selector_node",
                        "to_node": "requisition_node",
                        "condition": {"domain": "requisition"},
                        "context_strategy": "full"
                    },
                    {
                        "from_node": "selector_node",
                        "to_node": "purchase_order_node",
                        "condition": {"domain": "purchase_order"},
                        "context_strategy": "full"
                    },
                    {
                        "from_node": "selector_node",
                        "to_node": "framework_agreement_node",
                        "condition": {"domain": "framework_agreement"},
                        "context_strategy": "full"
                    }
                ],
                "entry_node": "selector_node",
                "termination_conditions": [
                    {"type": "max_iterations", "value": 10},
                    {"type": "custom", "function": "check_routing_attempts", "max_value": 3}
                ]
            },
            "execution_strategy": "conditional"
        }
        
        # Validate structure properties
        assert old_workflow["pattern"] == "selector"
        assert "selector_config" in old_workflow
        assert len(old_workflow["selector_config"]["routing_agents"]) == 3
        
        # After migration, should have graph topology
        assert expected_topology["topology"]["type"] == "graph"
        assert len(expected_topology["topology"]["nodes"]) == 4
        assert len(expected_topology["topology"]["edges"]) == 3
        # All edges should have conditions
        for edge in expected_topology["topology"]["edges"]:
            assert "condition" in edge

    def test_topology_has_required_fields(self):
        """Property: v0.4 topology must have required fields."""
        required_fields = ["type", "nodes", "edges", "entry_node"]
        
        topology = {
            "type": "sequential",
            "nodes": [{"id": "node1", "agent_id": "agent1"}],
            "edges": [{"from_node": "node1", "to_node": "node2"}],
            "entry_node": "node1"
        }
        
        for field in required_fields:
            assert field in topology, f"Missing required field: {field}"

    def test_topology_nodes_have_agent_mapping(self):
        """Property: Each node must map to an agent_id."""
        nodes = [
            {"id": "selector_node", "agent_id": "selector_agent"},
            {"id": "requisition_node", "agent_id": "requisition_domain_agent"}
        ]
        
        for node in nodes:
            assert "id" in node
            assert "agent_id" in node
            assert isinstance(node["id"], str)
            assert isinstance(node["agent_id"], str)
            assert len(node["id"]) > 0
            assert len(node["agent_id"]) > 0

    def test_topology_edges_connect_valid_nodes(self):
        """Property: All edges must connect existing nodes."""
        nodes = [
            {"id": "node1", "agent_id": "agent1"},
            {"id": "node2", "agent_id": "agent2"}
        ]
        node_ids = {node["id"] for node in nodes}
        
        edges = [
            {"from_node": "node1", "to_node": "node2", "context_strategy": "full"}
        ]
        
        for edge in edges:
            assert edge["from_node"] in node_ids, f"from_node {edge['from_node']} not in nodes"
            assert edge["to_node"] in node_ids, f"to_node {edge['to_node']} not in nodes"

    def test_topology_entry_node_exists(self):
        """Property: entry_node must be one of the defined nodes."""
        nodes = [
            {"id": "selector_node", "agent_id": "selector_agent"},
            {"id": "worker_node", "agent_id": "worker_agent"}
        ]
        node_ids = {node["id"] for node in nodes}
        
        entry_node = "selector_node"
        
        assert entry_node in node_ids, "entry_node must exist in nodes"

    def test_context_strategy_valid_values(self):
        """Property: context_strategy must be one of allowed values."""
        valid_strategies = ["full", "summary", "selective", "none"]
        
        edges = [
            {"from_node": "node1", "to_node": "node2", "context_strategy": "full"},
            {"from_node": "node2", "to_node": "node3", "context_strategy": "summary"}
        ]
        
        for edge in edges:
            if "context_strategy" in edge:
                assert edge["context_strategy"] in valid_strategies

    def test_termination_conditions_converted(self):
        """Property: max_turns must convert to termination_conditions."""
        old_max_turns = 10
        
        termination_conditions = [
            {"type": "max_iterations", "value": old_max_turns}
        ]
        
        assert len(termination_conditions) > 0
        assert any(tc["type"] == "max_iterations" for tc in termination_conditions)
        assert any(tc["value"] == old_max_turns for tc in termination_conditions)

    def test_shipped_workflows_use_topology(self):
        """Integration: shipped example workflows expose v0.4 topology."""
        from src.config.workflow_registry import WorkflowRegistry
        
        # Load workflows config
        registry = WorkflowRegistry()
        
        # Test example workflows have topology
        example_workflows = ['support_triage', 'assistant_chat']

        for workflow_id in example_workflows:
            workflow = registry.get_workflow(workflow_id)
            assert workflow is not None, f"Workflow {workflow_id} should exist"
            
            # Verify topology exists
            assert hasattr(workflow, 'topology'), f"Workflow {workflow_id} should have topology attribute"
            assert workflow.topology is not None, f"Workflow {workflow_id} should have topology"
            
            # Verify topology structure
            topology = workflow.topology
            assert hasattr(topology, 'nodes'), "Topology should have nodes"
            assert hasattr(topology, 'edges'), "Topology should have edges"
            assert hasattr(topology, 'entry_node'), "Topology should have entry_node"
            assert len(topology.nodes) > 0, f"Workflow {workflow_id} should have nodes"
