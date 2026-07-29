"""Structured workflow diagnostics for the studio's Help panel.

Reuses the graph checks in ``src.api.workflow_validation`` (cycle detection,
agent references, connection integrity) and adds the configuration checks that
``configs/README.md`` already tells users to perform by hand: does the agent's
provider exist, is its key set, is the model known, is the tool importable and
enabled.

Findings carry a stable ``code`` and, where possible, a ``node_id`` so the
canvas can highlight the offending component.
"""

from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.api.workflow_validation import (
    detect_cycles,
    validate_agent_references,
    validate_connections,
)

Severity = Literal["error", "warning", "info"]


class Diagnostic(BaseModel):
    """One finding about a workflow or one of its components."""

    code: str = Field(description="Stable identifier, e.g. 'provider_key_missing'")
    severity: Severity = "error"
    message: str
    field: str | None = Field(default=None, description="Config path, e.g. nodes[n1].agent_id")
    node_id: str | None = None
    component: str | None = Field(default=None, description="agent | tool | workflow | provider")
    suggestions: list[str] = Field(default_factory=list, description="'Did you mean' candidates")
    doc_id: str | None = Field(default=None, description="Key into the studio help catalogue")


def _provider_index(providers: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(p.get("id")): p for p in providers if p.get("id")}


def _check_agent_model(
    agent_id: str,
    agent: dict[str, Any],
    providers: dict[str, dict[str, Any]],
    node_id: str | None = None,
) -> list[Diagnostic]:
    """The checks that actually explain 'my agent does nothing'."""
    findings: list[Diagnostic] = []
    llm = agent.get("llm_config")
    if not isinstance(llm, dict):
        llm = agent.get("model_config") or {}
    provider_id = str(llm.get("provider_id") or "")
    model = str(llm.get("model") or "")

    if not provider_id:
        return findings  # No provider set: the runtime falls back to its default

    provider = providers.get(provider_id)
    if provider is None:
        findings.append(
            Diagnostic(
                code="provider_missing",
                severity="error",
                message=f"Agent '{agent_id}' uses provider '{provider_id}', which is not configured.",
                field=f"agents[{agent_id}].llm_config.provider_id",
                node_id=node_id,
                component="provider",
                suggestions=sorted(providers)[:5],
                doc_id="agent",
            )
        )
        return findings

    if not provider.get("enabled", True):
        findings.append(
            Diagnostic(
                code="provider_disabled",
                severity="error",
                message=f"Agent '{agent_id}' uses provider '{provider_id}', which is disabled.",
                field=f"agents[{agent_id}].llm_config.provider_id",
                node_id=node_id,
                component="provider",
                doc_id="agent",
            )
        )

    auth = provider.get("auth") or {}
    if auth.get("required", bool(auth)):
        from src.config.provider_registry import resolve_api_key

        if not resolve_api_key(provider_id):
            env_var = auth.get("env_var") or "the provider's API key"
            findings.append(
                Diagnostic(
                    code="provider_key_missing",
                    severity="error",
                    message=(
                        f"Provider '{provider_id}' has no API key. "
                        f"Set {env_var} or paste a key in the provider settings."
                    ),
                    field=f"agents[{agent_id}].llm_config.provider_id",
                    node_id=node_id,
                    component="provider",
                    doc_id="agent",
                )
            )

    known = [str(m.get("name")) for m in provider.get("models", []) if m.get("name")]
    if model and known and model not in known:
        findings.append(
            Diagnostic(
                code="model_unknown_for_provider",
                severity="warning",
                message=(
                    f"Model '{model}' is not in the configured list for '{provider_id}'. "
                    "It may still work — refresh the model list to confirm."
                ),
                field=f"agents[{agent_id}].llm_config.model",
                node_id=node_id,
                component="agent",
                suggestions=known[:5],
                doc_id="agent",
            )
        )
    return findings


def _check_tools(
    agent_id: str,
    agent: dict[str, Any],
    tools: dict[str, dict[str, Any]],
    node_id: str | None = None,
    probe_imports: bool = False,
) -> list[Diagnostic]:
    findings: list[Diagnostic] = []
    for tool_id in agent.get("tools") or []:
        tool = tools.get(str(tool_id))
        if tool is None:
            findings.append(
                Diagnostic(
                    code="tool_missing",
                    severity="error",
                    message=f"Agent '{agent_id}' references tool '{tool_id}', which does not exist.",
                    field=f"agents[{agent_id}].tools",
                    node_id=node_id,
                    component="tool",
                    suggestions=sorted(tools)[:5],
                    doc_id="tool",
                )
            )
            continue
        if not tool.get("enabled", True):
            findings.append(
                Diagnostic(
                    code="tool_disabled_but_referenced",
                    severity="error",
                    message=f"Tool '{tool_id}' is disabled but agent '{agent_id}' still uses it.",
                    field=f"tools[{tool_id}].enabled",
                    node_id=node_id,
                    component="tool",
                    doc_id="tool",
                )
            )
        findings.extend(_check_tool_entrypoint(tool, probe_imports=probe_imports))
    return findings


def _check_tool_entrypoint(tool: dict[str, Any], probe_imports: bool = False) -> list[Diagnostic]:
    """Verify a function tool's entrypoint resolves.

    Only the module is probed by default — importing user modules executes
    arbitrary code, which validation must not do implicitly.
    """
    entrypoint = tool.get("entrypoint")
    tool_id = str(tool.get("id") or "")
    if not entrypoint or ":" not in str(entrypoint):
        return []
    module_path, _, attr = str(entrypoint).partition(":")
    try:
        spec = importlib.util.find_spec(module_path)
    except (ImportError, ValueError, ModuleNotFoundError):
        spec = None
    if spec is None:
        return [
            Diagnostic(
                code="tool_entrypoint_unimportable",
                severity="error",
                message=f"Tool '{tool_id}' points at module '{module_path}', which cannot be found.",
                field=f"tools[{tool_id}].entrypoint",
                component="tool",
                doc_id="tool",
            )
        ]
    if probe_imports:
        try:
            module = importlib.import_module(module_path)
            if not hasattr(module, attr):
                return [
                    Diagnostic(
                        code="tool_entrypoint_unimportable",
                        severity="error",
                        message=f"Tool '{tool_id}': module '{module_path}' has no '{attr}'.",
                        field=f"tools[{tool_id}].entrypoint",
                        component="tool",
                        doc_id="tool",
                    )
                ]
        except Exception as exc:  # noqa: BLE001 - user code, any failure is a finding
            return [
                Diagnostic(
                    code="tool_entrypoint_unimportable",
                    severity="error",
                    message=f"Tool '{tool_id}' failed to import: {exc}",
                    field=f"tools[{tool_id}].entrypoint",
                    component="tool",
                    doc_id="tool",
                )
            ]
    return []


def structural_checks_applicable(topology: dict[str, Any]) -> bool:
    """Whether edge-based reachability rules mean anything for this topology.

    Most shipped workflows declare no edges at all: selectors route through an
    LLM at run time, and other crews run their nodes in declaration order.
    Applying reachability there reports every non-entry node as unreachable.
    Read from the raw dict — the parsed model drops routing_method/domain_agents.
    """
    if not topology.get("edges") and not topology.get("connections"):
        return False
    if str(topology.get("routing_method") or "").lower() == "llm":
        return False
    return not topology.get("domain_agents")


def diagnose_graph(
    nodes: list[dict[str, Any]],
    connections: list[dict[str, Any]],
    *,
    agents: list[dict[str, Any]] | None = None,
    tools: list[dict[str, Any]] | None = None,
    providers: list[dict[str, Any]] | None = None,
    entry_node: str | None = None,
    topology: dict[str, Any] | None = None,
    probe_imports: bool = False,
) -> list[Diagnostic]:
    """Diagnose a graph, saved or not."""
    agent_index = {str(a.get("id")): a for a in (agents or []) if a.get("id")}
    tool_index = {str(t.get("id")): t for t in (tools or []) if t.get("id")}
    provider_index = _provider_index(providers or [])
    findings: list[Diagnostic] = []

    if not nodes:
        return [
            Diagnostic(
                code="workflow_empty",
                severity="error",
                message="This workflow has no nodes.",
                component="workflow",
                doc_id="workflow",
            )
        ]

    # The shared validators read plain attributes, so lightweight shims let us
    # pass loose canvas nodes whose agent_id may be absent — exactly the case
    # the typed WorkflowNode model would refuse to construct.
    node_shims = [
        SimpleNamespace(id=str(n.get("id") or ""), agent_id=str(n.get("agent_id") or ""))
        for n in nodes
    ]
    conn_shims = [
        SimpleNamespace(
            from_node=str(c.get("from_node") or c.get("source") or ""),
            to_node=str(c.get("to_node") or c.get("target") or ""),
            type=str(c.get("type") or "sequential"),
        )
        for c in connections
    ]

    # Structural checks from the existing validator
    for shim in node_shims:
        if not shim.agent_id:
            findings.append(
                Diagnostic(
                    code="agent_not_assigned",
                    severity="error",
                    message=f"Node '{shim.id}' has no agent assigned.",
                    field=f"nodes[{shim.id}].agent_id",
                    node_id=shim.id,
                    component="agent",
                    doc_id="agent",
                )
            )
    bound = [n for n in node_shims if n.agent_id]
    for err in validate_agent_references(bound, set(agent_index)):
        node_id = str(err.field or "").removeprefix("nodes[").partition("]")[0] or None
        findings.append(
            Diagnostic(
                code="agent_missing",
                severity="error",
                message=err.message,
                field=err.field,
                node_id=node_id,
                component="agent",
                suggestions=sorted(agent_index)[:5],
                doc_id="agent",
            )
        )
    for err in validate_connections(node_shims, conn_shims):
        findings.append(
            Diagnostic(
                code=str(err.error_type or "invalid_connection"),
                severity="error",
                message=err.message,
                field=err.field,
                component="workflow",
                doc_id="workflow",
            )
        )
    for cycle in detect_cycles(conn_shims):
        findings.append(
            Diagnostic(
                code="cycle_detected",
                severity="warning",
                message=f"Sequential connections form a cycle: {' -> '.join(cycle)}",
                component="workflow",
                doc_id="workflow",
            )
        )

    if entry_node and entry_node not in {str(n.get("id")) for n in nodes}:
        findings.append(
            Diagnostic(
                code="entry_node_missing",
                severity="error",
                message=f"Entry node '{entry_node}' is not one of this workflow's nodes.",
                field="topology.entry_node",
                component="workflow",
                doc_id="workflow",
            )
        )

    if topology is not None and not structural_checks_applicable(topology):
        findings.append(
            Diagnostic(
                code="no_explicit_edges",
                severity="info",
                message=(
                    "This topology has no explicit edges. Nodes run in declaration "
                    "order, or routing is decided by the selector at run time."
                ),
                component="workflow",
                doc_id="workflow",
            )
        )

    # Configuration checks, per node
    for node in nodes:
        node_id = str(node.get("id") or "")
        agent_id = str(node.get("agent_id") or "")
        agent = agent_index.get(agent_id)
        if agent is None:
            continue
        findings.extend(_check_agent_model(agent_id, agent, provider_index, node_id))
        findings.extend(
            _check_tools(agent_id, agent, tool_index, node_id, probe_imports=probe_imports)
        )

    return findings
