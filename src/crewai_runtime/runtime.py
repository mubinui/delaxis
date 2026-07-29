"""CrewAI runtime adapter for Open Agent Kit workflow configs.

The adapter intentionally keeps the public REST surface stable while moving
workflow execution to CrewAI. It translates the existing JSON agent/tool/workflow
configuration into CrewAI objects at runtime, leveraging advanced CrewAI features
such as Flows, Knowledge Sources, and Memory databases natively.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import structlog

from src.config.agent_models import AgentConfig, LLMConfig
from src.config.provider_capabilities import AGENT_PARAMS, filter_llm_params
from src.config.loader import load_agents_config
from src.config.tool_registry import ToolDefinition, get_tool_registry
from src.config.workflow_models import WorkflowConfig
from src.crewai_runtime.execution_events import EventSink, ExecutionEventEmitter, TaskMeta

logger = structlog.get_logger(__name__)

# Used when an agent (or the hierarchical manager) has no model configured.
# Must handle tool calling reliably: the manager delegates via tool calls, and a
# model that cannot do that emits the call as plain text instead of running it.
DEFAULT_FALLBACK_MODEL = "openrouter/google/gemini-3.5-flash-lite"


@dataclass
class CrewAIRuntimeResult:
    """Normalized result returned to the existing API layer."""

    response: str
    trace_steps: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class CrewAINotAvailableError(RuntimeError):
    """Raised when CrewAI is selected but not installed in the environment."""


class CrewAIWorkflowRuntime:
    """Execute existing workflow configurations through advanced CrewAI capabilities."""

    def __init__(
        self,
        memory_enabled: bool = True,
        storage_dir: str = "./.crewai",
        default_process: str = "sequential",
    ) -> None:
        self.memory_enabled = memory_enabled
        self.storage_dir = storage_dir
        self.default_process = default_process

    @staticmethod
    def is_available() -> bool:
        """Return whether CrewAI can be imported in the current environment."""
        try:
            import crewai  # noqa: F401
        except Exception:
            return False
        return True

    async def run_message(
        self,
        workflow: WorkflowConfig,
        message: str,
        session_id: str,
        user_id: str,
        metadata: dict[str, Any] | None = None,
        event_sink: EventSink | None = None,
    ) -> CrewAIRuntimeResult:
        """Run one user message through a CrewAI crew or Flow in a worker thread."""

        started = time.perf_counter()
        result = await asyncio.to_thread(
            self._run_message_sync,
            workflow,
            message,
            session_id,
            user_id,
            metadata or {},
            event_sink,
        )
        result.metadata.setdefault("latency_ms", round((time.perf_counter() - started) * 1000))
        return result

    def _run_message_sync(
        self,
        workflow: WorkflowConfig,
        message: str,
        session_id: str,
        user_id: str,
        metadata: dict[str, Any],
        event_sink: EventSink | None = None,
    ) -> CrewAIRuntimeResult:
        # The ExitStack owns the lifecycle of per-run tool resources (notably MCP
        # server connections/subprocesses): they are closed when this method
        # returns or raises, no matter where the failure happens.
        with contextlib.ExitStack() as stack:
            return self._run_message_inner(workflow, message, session_id, user_id, metadata, stack, event_sink)

    def _run_message_inner(
        self,
        workflow: WorkflowConfig,
        message: str,
        session_id: str,
        user_id: str,
        metadata: dict[str, Any],
        stack: contextlib.ExitStack,
        event_sink: EventSink | None = None,
    ) -> CrewAIRuntimeResult:
        try:
            from crewai import Agent, Crew, Process, Task
        except Exception as exc:
            raise CrewAINotAvailableError(
                "CrewAI runtime selected but crewai is not installed. Run `uv sync` first."
            ) from exc

        os.environ.setdefault("CREWAI_STORAGE_DIR", self.storage_dir)

        agent_configs = {agent.id: agent for agent in load_agents_config().agents}
        # Set by the session manager from the deployment record (server-side only)
        raw_override = metadata.get("model_override")
        model_override = raw_override if isinstance(raw_override, dict) and raw_override else None
        ordered_nodes = self._ordered_nodes(workflow)
        workflow_agent_ids = [node.agent_id for node in ordered_nodes]
        if not workflow_agent_ids:
            raise ValueError(f"Workflow {workflow.id} has no agents to execute")

        # The emitter records per-node I/O for every run (surfaced in result
        # metadata); with an event_sink it additionally streams events live.
        emitter = ExecutionEventEmitter(event_sink, message)

        # Canvas attachments (Tools/Memory/Knowledge handles) fold into the
        # agent behind each node. The same agent used by several nodes gets
        # the union of their attachments.
        extra_tools, wants_memory, wants_knowledge, router_agent_ids = self._node_attachments(ordered_nodes)
        attached_knowledge_sources = (
            self._resolve_knowledge_sources(workflow, force=True) if wants_knowledge else []
        )
        # Retrieval over the configured collections. A Knowledge node used to
        # produce only a StringKnowledgeSource echoing the workflow description,
        # so its collections/top_k settings did nothing; this is the part that
        # actually searches the corpus.
        knowledge_tools = self._knowledge_retrieval_tools(workflow)
        knowledge_everywhere = (
            not wants_knowledge and bool(getattr(getattr(workflow, "knowledge", None), "enabled", False))
        )

        crew_agents: list[Any] = []
        crew_agent_by_id: dict[str, Any] = {}
        # One factory build per tool id per run: agents sharing an MCP tool share
        # one live server connection instead of spawning one each.
        run_tool_cache: dict[str, list[Any]] = {}
        for agent_id in workflow_agent_ids:
            config = agent_configs.get(agent_id)
            if config is None:
                logger.warning("crewai_agent_config_missing", workflow_id=workflow.id, agent_id=agent_id)
                continue
            crew_agent = self._create_agent(
                Agent,
                config,
                stack,
                run_tool_cache,
                emitter=emitter,
                extra_tool_ids=extra_tools.get(agent_id, []),
                memory_attached=agent_id in wants_memory,
                knowledge_sources=attached_knowledge_sources if agent_id in wants_knowledge else None,
                knowledge_tools=knowledge_tools if (knowledge_everywhere or agent_id in wants_knowledge) else None,
                delegates=agent_id in router_agent_ids,
                model_override=model_override,
            )
            crew_agents.append(crew_agent)
            crew_agent_by_id[agent_id] = crew_agent

        if not crew_agents:
            raise ValueError(f"Workflow {workflow.id} has no valid CrewAI agents")

        tasks, task_metas = self._create_tasks(
            task_cls=Task,
            workflow=workflow,
            ordered_nodes=ordered_nodes,
            crew_agent_by_id=crew_agent_by_id,
            message=message,
            session_id=session_id,
            user_id=user_id,
            metadata=metadata,
            agent_configs=agent_configs,
        )

        process = self._resolve_process(Process, workflow)
        process_name = process.value if hasattr(process, "value") else str(process)
        emitter.register_tasks(task_metas, sequential=not process_name.lower().endswith("hierarchical"))

        # Resolve Knowledge sources natively if available
        knowledge_sources = self._resolve_knowledge_sources(workflow)

        trace_steps = self._planning_trace(
            workflow=workflow,
            task_metas=task_metas,
            tasks=tasks,
            process=process,
            crew_agents=crew_agents,
        )
        if event_sink is not None:
            for step in trace_steps:
                emitter.emit_trace(step)

        memory_active = workflow.memory.enabled if hasattr(workflow, "memory") else self.memory_enabled
        
        crew_kwargs: dict[str, Any] = {
            "agents": crew_agents,
            "tasks": tasks,
            "process": process,
            "memory": memory_active,
            "verbose": bool(getattr(workflow, "verbose", False)),
            "cache": bool(getattr(workflow, "cache", True)),
            "task_callback": emitter.task_callback,
        }

        if knowledge_sources:
            crew_kwargs["knowledge"] = knowledge_sources

        if getattr(workflow, "planning", False):
            crew_kwargs["planning"] = True
            crew_kwargs["planning_llm"] = self._resolve_llm_model(
                self._crew_llm_config(workflow, "planning_llm", agent_configs, workflow_agent_ids)
            )

        if getattr(workflow, "max_rpm", None):
            crew_kwargs["max_rpm"] = int(workflow.max_rpm)

        if (process.value if hasattr(process, "value") else str(process)).lower().endswith("hierarchical"):
            crew_kwargs["manager_llm"] = self._resolve_llm_model(
                self._crew_llm_config(workflow, "manager_llm", agent_configs, workflow_agent_ids)
            )
            
        crew = Crew(**crew_kwargs)

        # Kickoff CrewAI process
        inputs_dict = {
            "message": message,
            "session_id": session_id,
            "user_id": user_id,
            "workflow_id": workflow.id,
            **metadata,
        }
        
        started_execution = time.time()
        try:
            emitter.on_kickoff_start()
            kickoff_result = crew.kickoff(inputs=inputs_dict)
            response = getattr(kickoff_result, "raw", None) or str(kickoff_result)
            token_usage = getattr(kickoff_result, "token_usage", {})
            if hasattr(token_usage, "model_dump"):
                token_usage = token_usage.model_dump()
            elif hasattr(token_usage, "__dict__"):
                token_usage = token_usage.__dict__
        except Exception as e:
            logger.error("crewai_execution_error", error=str(e), exc_info=True)
            response = f"Error during CrewAI execution: {str(e)}"
            token_usage = {}
            
        execution_duration = time.time() - started_execution
        
        # Calculate approximate cost if token usage available
        total_tokens = token_usage.get("total_tokens", 0) if isinstance(token_usage, dict) else 0
        prompt_tokens = token_usage.get("prompt_tokens", 0) if isinstance(token_usage, dict) else 0
        completion_tokens = token_usage.get("completion_tokens", 0) if isinstance(token_usage, dict) else 0
        approx_cost = (prompt_tokens * 0.0000015) + (completion_tokens * 0.000006)

        trace_steps.append(
            {
                "type": "crew_done",
                "agent": "CrewAI",
                "description": f"Completed workflow {workflow.id} using advanced features",
                "timestamp": time.time(),
                "details": {
                    "latency_source": "runtime",
                    "execution_duration_sec": round(execution_duration, 2),
                    "response_chars": len(response or ""),
                    "tokens": {
                        "total": total_tokens,
                        "prompt": prompt_tokens,
                        "completion": completion_tokens,
                    },
                    "estimated_cost_usd": round(approx_cost, 6),
                },
            }
        )
        
        return CrewAIRuntimeResult(
            response=response.strip(),
            trace_steps=trace_steps,
            metadata={
                "runtime": "crewai",
                "workflow_id": workflow.id,
                "agent_count": len(crew_agents),
                "task_count": len(tasks),
                "agents_called": [getattr(agent, "role", "agent") for agent in crew_agents],
                "tools_called": self._workflow_tool_ids(workflow, agent_configs),
                "memory_enabled": memory_active,
                "knowledge_enabled": bool(knowledge_sources),
                "knowledge_sources_count": len(knowledge_sources) if knowledge_sources else 0,
                "process": process_name,
                "usage": token_usage if isinstance(token_usage, dict) else {},
                "cost_usd": round(approx_cost, 6),
                "node_io": emitter.node_io(),
                "tool_io": emitter.tool_io(),
            },
        )

    @staticmethod
    def _node_attachments(
        ordered_nodes: list[Any],
    ) -> tuple[dict[str, list[str]], set[str], set[str], set[str]]:
        """Fold canvas handle attachments (tools/memory/knowledge) per agent id.

        Also returns the agents whose node is marked ``is_router`` — a Flow
        Router on the canvas fans out through them, so they delegate to their
        branches instead of just running first.
        """
        extra_tools: dict[str, list[str]] = {}
        wants_memory: set[str] = set()
        wants_knowledge: set[str] = set()
        routers: set[str] = set()
        for node in ordered_nodes:
            agent_id = node.agent_id
            for tool_id in getattr(node, "tools", None) or []:
                bucket = extra_tools.setdefault(agent_id, [])
                if tool_id not in bucket:
                    bucket.append(tool_id)
            if getattr(node, "memory", None):
                wants_memory.add(agent_id)
            if getattr(node, "knowledge", None):
                wants_knowledge.add(agent_id)
            if getattr(node, "is_router", False):
                routers.add(agent_id)
        return extra_tools, wants_memory, wants_knowledge, routers

    def _knowledge_retrieval_tools(self, workflow: WorkflowConfig) -> list[Any]:
        """A ``search_knowledge`` tool bound to the workflow's collections.

        This is what makes a Knowledge Source node do real retrieval: it pins
        the collections and ``top_k`` configured on the node, so the agent only
        supplies a query. Returns nothing when the RAG service is off or no
        collection is configured, rather than handing the agent a tool that can
        only fail.
        """
        knowledge = getattr(workflow, "knowledge", None)
        collections = [str(c) for c in (getattr(knowledge, "collections", None) or []) if str(c).strip()]
        if not collections:
            return []

        try:
            from crewai.tools import tool as crewai_tool

            from src.config.settings import get_settings
            from src.tools.rag_pipeline import query_rag
        except Exception as exc:
            logger.warning("knowledge_retrieval_unavailable", error=str(exc))
            return []

        if not get_settings().external_services.rag_pipeline_enabled:
            logger.warning("knowledge_retrieval_skipped", reason="RAG_PIPELINE_ENABLED is false")
            return []

        top_k = int(getattr(knowledge, "top_k", 5) or 5)

        def search_knowledge(query: str) -> str:
            """Search the workflow's knowledge collections for passages relevant to a query. Returns the matching passages with their source and relevance score."""
            passages: list[str] = []
            for collection in collections:
                try:
                    result = asyncio.run(query_rag(query=query, collection=collection, top_k=top_k))
                except Exception as exc:  # a failing collection must not kill the run
                    logger.warning("knowledge_query_failed", collection=collection, error=str(exc))
                    continue
                if not result.get("success"):
                    logger.warning("knowledge_query_rejected", collection=collection, error=result.get("error"))
                    continue
                for item in result.get("results", []):
                    text = str(item.get("text", "")).strip()
                    if not text:
                        continue
                    passages.append(f"[{collection} · score {item.get('score', 0):.3f}] {text}")
            if not passages:
                return "No relevant passages found in the configured knowledge collections."
            return "\n\n".join(passages[: top_k * len(collections)])

        logger.info("knowledge_retrieval_enabled", collections=collections, top_k=top_k)
        return [crewai_tool("search_knowledge")(search_knowledge)]

    def _resolve_knowledge_sources(self, workflow: WorkflowConfig, force: bool = False) -> list[Any]:
        """Dynamically build CrewAI Knowledge source instances if configured.

        `force=True` builds sources even when the workflow-level toggle is off,
        for agents with a Knowledge node attached directly on the canvas.
        """
        enabled = hasattr(workflow, "knowledge") and getattr(workflow.knowledge, "enabled", False)
        if not enabled and not force:
            return []
            
        sources = []
        try:
            from crewai.knowledge.source.string_knowledge_source import StringKnowledgeSource
            
            # Inject dynamic context as string knowledge if metadata contains context
            desc = getattr(workflow, "description", "")
            if desc:
                sources.append(
                    StringKnowledgeSource(
                        content=f"Workflow Domain Info: {desc}",
                        metadata={"source": "workflow_description"},
                    )
                )
        except Exception as e:
            logger.debug("crewai_knowledge_source_import_skipped", error=str(e))
            
        return sources

    def _crew_llm_config(
        self,
        workflow: Any,
        field: str,
        agent_configs: dict[str, Any],
        workflow_agent_ids: list[str],
    ) -> dict[str, Any]:
        """Model config for a crew-level LLM (manager or planner).

        An explicit workflow setting wins. Otherwise inherit the entry agent's
        model rather than the global fallback: the hierarchical manager
        delegates via tool calls, so a weaker model than the crew itself
        produces delegations emitted as plain text.
        """
        explicit = getattr(workflow, field, None)
        if isinstance(explicit, dict) and explicit:
            return dict(explicit)
        for agent_id in workflow_agent_ids:
            config = agent_configs.get(agent_id)
            if config is None:
                continue
            model_config = self._effective_model_config(config)
            if model_config.get("model"):
                return model_config
        return {}

    def _effective_model_config(self, config: AgentConfig) -> dict[str, Any]:
        """Merge every place the studio/API can express an agent's model settings.

        Studio-created agents persist `llm_config` (v0.2), older configs use
        `model_config`/`model_config_override`, and v0.4 uses model_client_config.
        The runtime previously read only model_config_override, silently dropping
        the provider/model/temperature users picked in the studio.
        Priority: model_config_override > llm_config/model_client_config.
        """
        merged: dict[str, Any] = {}
        # get_effective_model_config() re-projects onto ModelClientConfig field
        # by field, which drops every sampling parameter that model doesn't
        # declare. Dump the source config instead so new fields survive.
        llm_config = config.llm_config if isinstance(config.llm_config, LLMConfig) else None
        if llm_config is not None:
            merged.update(llm_config.model_dump(exclude_none=True))
        elif config.model_client_config is not None:
            merged.update(config.model_client_config.model_dump(exclude_none=True))
        else:
            try:
                effective = config.get_effective_model_config()
            except Exception:
                effective = None
            if effective is not None:
                merged.update({k: v for k, v in effective.model_dump().items() if v is not None})
        if config.agent_settings is not None:
            merged.update(config.agent_settings.model_dump(exclude_none=True))
        override = config.model_config_override or {}
        merged.update({k: v for k, v in override.items() if v is not None})
        return merged

    def _create_agent(
        self,
        agent_cls: type[Any],
        config: AgentConfig,
        stack: contextlib.ExitStack | None = None,
        run_tool_cache: dict[str, list[Any]] | None = None,
        emitter: ExecutionEventEmitter | None = None,
        extra_tool_ids: list[str] | None = None,
        memory_attached: bool = False,
        knowledge_sources: list[Any] | None = None,
        knowledge_tools: list[Any] | None = None,
        delegates: bool = False,
        model_override: dict[str, Any] | None = None,
    ) -> Any:
        model_config = self._effective_model_config(config)
        if model_override:
            # A deployment pins provider/model for every agent it runs
            model_config = {**model_config, **model_override}
        tool_ids = list(config.tools)
        for tool_id in extra_tool_ids or []:
            if tool_id not in tool_ids:
                tool_ids.append(tool_id)
        tools = self._get_crewai_tools(tool_ids, stack, run_tool_cache, emitter=emitter)
        tools = tools + list(knowledge_tools or [])

        agent_kwargs: dict[str, Any] = {
            "role": config.name,
            "goal": config.description or f"Help users with {config.name} requests.",
            "backstory": config.system_message or config.description or "You are a highly capable enterprise AI assistant.",
            "llm": self._resolve_llm_model(model_config),
            "tools": tools,
        }
        agent_kwargs.update(self._agent_params(config, model_config))
        if delegates:
            # A canvas Flow Router branching off this node means it must be able
            # to hand work to those branches.
            agent_kwargs["allow_delegation"] = True
        if memory_attached:
            agent_kwargs["memory"] = True
        if knowledge_sources:
            agent_kwargs["knowledge_sources"] = knowledge_sources

        return agent_cls(**agent_kwargs)

    @staticmethod
    def _agent_params(config: AgentConfig, model_config: dict[str, Any]) -> dict[str, Any]:
        """CrewAI Agent constructor settings, from agent_settings or model_config.

        max_iter/max_rpm/max_execution_time historically travelled inside
        model_config (the untyped override), so both sources are honoured.
        """
        _INT_PARAMS = {"max_iter", "max_rpm", "max_execution_time", "max_retry_limit"}
        _BOOL_PARAMS = {
            "allow_delegation",
            "respect_context_window",
            "cache",
            "verbose",
            "inject_date",
            "use_system_prompt",
        }

        params: dict[str, Any] = {
            # Selector agents delegate by default; an explicit setting wins below.
            "allow_delegation": bool(config.is_selector),
            "max_iter": 20,
            "verbose": False,
        }
        for key in AGENT_PARAMS:
            value = model_config.get(key)
            if value is None:
                continue
            if key in _INT_PARAMS:
                params[key] = int(value)
            elif key in _BOOL_PARAMS:
                params[key] = bool(value)
            else:
                params[key] = value
        return params

    @staticmethod
    def _legacy_prefix_model(model: Any) -> str:
        """Pre-registry behavior for agents without a provider_id: glue the
        LLM_PROVIDER prefix onto bare model ids (defaults to openrouter)."""
        if not model:
            return os.getenv("LLM_MODEL", DEFAULT_FALLBACK_MODEL)
        model = str(model)
        if "/" in model and not model.startswith(("openrouter/", "ollama/", "azure/", "gemini/")):
            provider = os.getenv("LLM_PROVIDER", "openrouter")
            if provider == "openrouter":
                model = f"openrouter/{model}"
        return model

    @staticmethod
    def _sampling_params(
        model_config: dict[str, Any], crewai_provider: str | None = None
    ) -> dict[str, Any]:
        """Sampling/limit parameters for the LLM constructor.

        When a route is given, parameters it does not honour are dropped rather
        than passed through — CrewAI's provider classes ignore unknown kwargs
        silently, so an unsupported setting would look applied but do nothing.
        `crewai_provider=None` keeps the unfiltered legacy behaviour.
        """
        candidates = (
            "temperature",
            "max_tokens",
            "max_completion_tokens",
            "max_output_tokens",
            "timeout",
            "top_p",
            "top_k",
            "presence_penalty",
            "frequency_penalty",
            "seed",
            "reasoning_effort",
            "stop",
            "response_format",
        )
        params = {key: model_config.get(key) for key in candidates}
        params = {k: v for k, v in params.items() if v is not None}
        if crewai_provider is None:
            return params
        kept, dropped = filter_llm_params(crewai_provider, params)
        if dropped:
            logger.info(
                "llm_params_unsupported_by_route",
                crewai_provider=crewai_provider,
                dropped=dropped,
            )
        return kept

    def _resolve_llm_model(self, model_config: dict[str, Any]) -> Any:
        model = model_config.get("model")
        provider_id = model_config.get("provider_id")
        if provider_id:
            llm = self._resolve_registered_provider(str(provider_id), model, model_config)
            if llm is not None:
                return llm

        model = self._legacy_prefix_model(model)
        # When the studio config carries actual sampling/limit parameters, build a
        # full LLM object so they're honored; a bare model string otherwise keeps
        # existing behavior byte-for-byte.
        llm_params = self._sampling_params(model_config)
        if model_config.get("base_url"):
            llm_params["base_url"] = model_config["base_url"]
        api_key_env = model_config.get("api_key_env")
        if api_key_env:
            api_key = os.environ.get(str(api_key_env))
            if api_key:
                llm_params["api_key"] = api_key
        if not llm_params:
            return model

        try:
            from crewai import LLM

            return LLM(model=model, **llm_params)
        except Exception as e:
            logger.warning("crewai_llm_params_ignored", error=str(e), model=model)
            return model

    def _resolve_registered_provider(
        self, provider_id: str, model: Any, model_config: dict[str, Any]
    ) -> Any | None:
        """Build an LLM from the provider registry, or None to use legacy routing.

        CrewAI is handed an explicit ``provider`` so any model name is accepted.
        A native provider whose SDK is missing (Gemini without
        ``crewai[google-genai]``) retries against the provider's
        OpenAI-compatible endpoint before giving up.
        """
        try:
            from src.config.provider_registry import ProviderResolutionError, compat_fallback, resolve_llm
        except ImportError:
            return None

        try:
            resolved = resolve_llm(provider_id, str(model or ""))
        except ProviderResolutionError as e:
            logger.warning("provider_resolution_failed_using_legacy", provider_id=provider_id, error=str(e))
            return None

        try:
            from crewai import LLM
        except ImportError:
            return None

        attempts = [resolved]
        fallback = compat_fallback(resolved)
        if fallback is not None:
            attempts.append(fallback)

        last_error: Exception | None = None
        for attempt in attempts:
            # Keyed on the route actually being attempted: compat_fallback can
            # recast a native provider as openai-compatible, which has a
            # different parameter set and a different output-token spelling.
            llm_params = self._sampling_params(model_config, attempt.crewai_provider)
            # Agent-level overrides always win over the provider defaults
            base_url = model_config.get("base_url") or attempt.base_url
            if base_url:
                llm_params["base_url"] = base_url
            api_key = attempt.api_key
            api_key_env = model_config.get("api_key_env")
            if api_key_env:
                api_key = os.environ.get(str(api_key_env)) or api_key
            if api_key:
                llm_params["api_key"] = api_key
            try:
                return LLM(model=attempt.model, provider=attempt.crewai_provider, **llm_params)
            except Exception as e:
                last_error = e
                logger.warning(
                    "crewai_llm_provider_unavailable",
                    provider_id=provider_id,
                    crewai_provider=attempt.crewai_provider,
                    model=attempt.model,
                    error=str(e),
                )

        logger.warning(
            "provider_llm_construction_failed_using_legacy",
            provider_id=provider_id,
            error=str(last_error) if last_error else None,
        )
        return None

    def _get_crewai_tools(
        self,
        tool_ids: list[str],
        stack: contextlib.ExitStack | None = None,
        run_tool_cache: dict[str, list[Any]] | None = None,
        emitter: ExecutionEventEmitter | None = None,
    ) -> list[Any]:
        if not tool_ids:
            return []
        try:
            from crewai.tools import tool
        except Exception:
            return []

        registry = get_tool_registry()
        crew_tools: list[Any] = []
        for tool_id in tool_ids:
            tool_def = registry.get_tool(tool_id)
            if tool_def is None:
                logger.warning("crewai_tool_missing", tool_id=tool_id)
                continue

            factory = getattr(tool_def, "factory", None)
            if factory is not None and stack is not None:
                # Factory-backed tools (mcp/database/gmail) yield native BaseTool
                # instances with real argument schemas — they must NOT be re-wrapped
                # by _wrap_tool, which would clobber the schema with **kwargs.
                cache = run_tool_cache if run_tool_cache is not None else {}
                if tool_id not in cache:
                    try:
                        cache[tool_id] = factory.build(stack)
                    except Exception as e:
                        logger.error("crewai_tool_factory_failed", tool_id=tool_id, error=str(e))
                        cache[tool_id] = []
                crew_tools.extend(cache[tool_id])
                continue

            crew_tools.append(self._wrap_tool(tool, tool_def, emitter=emitter))
        return crew_tools

    def _wrap_tool(
        self,
        tool_decorator: Callable[..., Any],
        tool_def: ToolDefinition,
        emitter: ExecutionEventEmitter | None = None,
    ) -> Any:
        func = tool_def.function

        def run_tool(*args: Any, **kwargs: Any) -> Any:
            started_tool = time.perf_counter()
            logger.info("crewai_tool_call_started", tool_id=tool_def.tool_id, tool_name=tool_def.name)
            if emitter is not None:
                # Positional args are rare (crewai passes structured kwargs), but
                # record them so the inspector reflects the real call.
                recorded = dict(kwargs)
                if args:
                    recorded["_args"] = list(args)
                emitter.tool_started(tool_def.tool_id, tool_def.name, recorded)
            try:
                if inspect.iscoroutinefunction(func):
                    res = asyncio.run(func(*args, **kwargs))
                else:
                    res = func(*args, **kwargs)
                duration = time.perf_counter() - started_tool
                logger.info("crewai_tool_call_success", tool_id=tool_def.tool_id, duration_sec=round(duration, 3))
                if emitter is not None:
                    emitter.tool_finished(
                        tool_def.tool_id, tool_def.name, result=res, duration_ms=round(duration * 1000)
                    )
                return res
            except Exception as e:
                duration = time.perf_counter() - started_tool
                logger.error("crewai_tool_call_failed", tool_id=tool_def.tool_id, error=str(e), duration_sec=round(duration, 3))
                if emitter is not None:
                    emitter.tool_finished(
                        tool_def.tool_id, tool_def.name, error=str(e), duration_ms=round(duration * 1000)
                    )
                return f"Tool execution error: {str(e)}"

        run_tool.__name__ = tool_def.name
        run_tool.__doc__ = tool_def.description
        # Expose the underlying function's real signature so crewai builds a
        # typed argument schema (e.g. web_search's `query`). Without this the
        # wrapper is `(**kwargs)`, the schema is empty, and the model calls the
        # tool with no arguments — every plain-function tool silently fails.
        try:
            run_tool.__signature__ = inspect.signature(func)
            run_tool.__annotations__ = dict(getattr(func, "__annotations__", {}))
        except (ValueError, TypeError):
            pass
        return tool_decorator(tool_def.name)(run_tool)

    def _resolve_process(self, process_cls: type[Any], workflow: WorkflowConfig) -> Any:
        raw = (getattr(workflow, "process", None) or workflow.metadata.get("pattern") or workflow.execution_strategy or self.default_process)
        raw = str(getattr(raw, "value", raw)).lower()
        if raw in {"hierarchical", "selector", "group_chat"} and hasattr(process_cls, "hierarchical"):
            return process_cls.hierarchical
        return process_cls.sequential

    def _ordered_nodes(self, workflow: WorkflowConfig) -> list[Any]:
        topology = workflow.topology
        nodes_by_id = {node.id: node for node in topology.nodes}
        if not topology.edges:
            entry = nodes_by_id.get(topology.entry_node)
            rest = [node for node in topology.nodes if node.id != topology.entry_node]
            return ([entry] if entry else []) + rest

        ordered: list[Any] = []
        seen: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in seen or node_id not in nodes_by_id:
                return
            seen.add(node_id)
            ordered.append(nodes_by_id[node_id])
            for edge in topology.edges:
                if edge.from_node == node_id:
                    visit(edge.to_node)

        visit(topology.entry_node)
        ordered.extend(node for node in topology.nodes if node.id not in seen)
        return ordered

    @staticmethod
    def _human_input_enabled(agent_config: Any) -> bool:
        """Task-level human input, gated behind an explicit opt-in env var.

        CrewAI's human input blocks on stdin, which would hang a headless API
        worker — so honoring human_input_mode=ALWAYS requires
        OAK_ALLOW_HUMAN_INPUT=true.
        """
        mode = str(getattr(getattr(agent_config, "human_input_mode", ""), "value", getattr(agent_config, "human_input_mode", ""))).upper()
        if mode != "ALWAYS":
            return False
        if os.getenv("OAK_ALLOW_HUMAN_INPUT", "false").lower() == "true":
            return True
        logger.warning("crewai_human_input_suppressed", reason="OAK_ALLOW_HUMAN_INPUT is not enabled")
        return False

    @staticmethod
    def _make_output_guardrail(output_schema: str) -> Callable[[Any], tuple[bool, Any]]:
        """Simple final-output validator used when workflow.guardrails.enabled."""

        # No return annotation on purpose: `from __future__ import annotations`
        # stringifies it, and crewai's Task validator inspects the raw signature
        # (get_origin on a string fails → "must be Tuple[bool, Any]" error).
        def guardrail(task_output):  # type: (Any) -> tuple[bool, Any]
            raw = str(getattr(task_output, "raw", task_output) or "").strip()
            if not raw:
                return False, "The output was empty. Produce a complete answer."
            if str(output_schema).lower() == "json":
                import json as _json

                candidate = raw
                if candidate.startswith("```"):
                    candidate = candidate.strip("`")
                    candidate = candidate.split("\n", 1)[1] if "\n" in candidate else candidate
                    if candidate.rstrip().endswith("```"):
                        candidate = candidate.rstrip().removesuffix("```")
                try:
                    _json.loads(candidate)
                except Exception as exc:
                    return False, f"The output must be valid JSON (parse error: {exc}). Re-emit as pure JSON with no prose."
            return True, task_output

        return guardrail

    def _create_tasks(
        self,
        task_cls: type[Any],
        workflow: WorkflowConfig,
        ordered_nodes: list[Any],
        crew_agent_by_id: dict[str, Any],
        message: str,
        session_id: str,
        user_id: str,
        metadata: dict[str, Any],
        agent_configs: dict[str, Any] | None = None,
    ) -> tuple[list[Any], list[TaskMeta]]:
        """Build CrewAI tasks plus aligned per-node metadata.

        Tasks are named after their topology node id so ``TaskOutput.name``
        identifies the node in ``task_callback``. The returned ``TaskMeta``
        list is index-aligned with the task list (nodes whose agent is missing
        are skipped from both).
        """
        agent_configs = agent_configs or {}
        guardrails_enabled = bool(getattr(getattr(workflow, "guardrails", None), "enabled", False))
        guardrail_schema = str(getattr(getattr(workflow, "guardrails", None), "output_schema", "text"))

        def apply_task_extras(task_kwargs: dict[str, Any], agent_id: str | None, is_final: bool) -> None:
            config = agent_configs.get(agent_id) if agent_id else None
            if config is not None and self._human_input_enabled(config):
                task_kwargs["human_input"] = True
            if is_final and guardrails_enabled:
                task_kwargs["guardrail"] = self._make_output_guardrail(guardrail_schema)
                task_kwargs["guardrail_max_retries"] = 2

        explicit_tasks = getattr(workflow, "tasks", []) or []
        if explicit_tasks:
            tasks: list[Any] = []
            metas: list[TaskMeta] = []
            for index, task_config in enumerate(explicit_tasks):
                agent = crew_agent_by_id.get(task_config.agent_id)
                if not agent:
                    continue
                node_id = task_config.node_id or task_config.id or f"task-{index + 1}"
                description = self._task_description(
                    workflow,
                    message,
                    session_id,
                    user_id,
                    metadata,
                    step=index + 1,
                    node_id=task_config.node_id,
                    task_description=task_config.description,
                )
                task_kwargs = {
                    "name": node_id,
                    "description": description,
                    "expected_output": task_config.expected_output,
                    "agent": agent,
                }
                if tasks:
                    task_kwargs["context"] = tasks[:]
                apply_task_extras(task_kwargs, task_config.agent_id, is_final=index == len(explicit_tasks) - 1)
                tasks.append(task_cls(**task_kwargs))
                metas.append(
                    TaskMeta(
                        node_id=node_id,
                        agent_id=task_config.agent_id,
                        index=len(tasks) - 1,
                        description=description,
                        expected_output=task_config.expected_output,
                        # Explicit tasks receive every prior task as context.
                        upstream_node_ids=[meta.node_id for meta in metas],
                    )
                )
            if tasks:
                return tasks, metas

        tasks = []
        metas = []
        for index, node in enumerate(ordered_nodes):
            agent = crew_agent_by_id.get(node.agent_id)
            if not agent:
                continue
            node_goal = node.config_override.get("task") if node.config_override else None
            description = self._task_description(
                workflow,
                message,
                session_id,
                user_id,
                metadata,
                step=index + 1,
                node_id=node.id,
                task_description=node_goal or f"Execute and analyze workflow node {node.id} natively.",
            )
            expected_output = (node.config_override or {}).get(
                "expected_output",
                "A highly detailed, production-grade output supporting complete context validation.",
            )
            task_kwargs = {
                "name": node.id,
                "description": description,
                "expected_output": expected_output,
                "agent": agent,
            }
            upstream = self._upstream_task_pairs(workflow, node.id, metas, tasks)
            if upstream:
                task_kwargs["context"] = [task for _, task in upstream]
            apply_task_extras(task_kwargs, node.agent_id, is_final=index == len(ordered_nodes) - 1)
            tasks.append(task_cls(**task_kwargs))
            metas.append(
                TaskMeta(
                    node_id=node.id,
                    agent_id=node.agent_id,
                    index=len(tasks) - 1,
                    description=description,
                    expected_output=expected_output,
                    upstream_node_ids=[meta.node_id for meta, _ in upstream],
                )
            )
        return tasks, metas

    def _task_description(
        self,
        workflow: WorkflowConfig,
        message: str,
        session_id: str,
        user_id: str,
        metadata: dict[str, Any],
        step: int = 1,
        node_id: str | None = None,
        task_description: str | None = None,
    ) -> str:
        return (
            f"Workflow Blueprint: {workflow.name}\n"
            f"Domain Focus: {workflow.description}\n"
            f"Execution Phase Step: {step}\n"
            f"Active Node: {node_id or 'derived'}\n"
            f"Mandatory Task Objective: {task_description or 'Evaluate user query and provide definitive guidance.'}\n"
            f"Session Trace ID: {session_id}\n"
            f"Identity Context: {user_id}\n"
            f"Runtime Parameters: {metadata}\n\n"
            f"Incoming User Prompt:\n{message}\n\n"
            "Deliver an optimal, exhaustive answer utilizing any applicable configured tools automatically."
        )

    def _upstream_task_pairs(
        self,
        workflow: WorkflowConfig,
        node_id: str,
        created_metas: list[TaskMeta],
        created_tasks: list[Any],
    ) -> list[tuple[TaskMeta, Any]]:
        """Return (meta, task) context pairs for upstream topology nodes.

        Pairing created metas with created tasks (always index-aligned) instead
        of ordered_nodes avoids misattributing context when a node is skipped
        because its agent config is missing.
        """
        pairs = list(zip(created_metas, created_tasks))
        if not workflow.topology.edges:
            return pairs[-1:]

        upstream_ids = {
            edge.from_node
            for edge in workflow.topology.edges
            if edge.to_node == node_id
        }
        return [(meta, task) for meta, task in pairs if meta.node_id in upstream_ids]

    def _planning_trace(
        self,
        workflow: WorkflowConfig,
        task_metas: list[TaskMeta],
        tasks: list[Any],
        process: Any,
        crew_agents: list[Any],
    ) -> list[dict[str, Any]]:
        """Create normalized trace entries before CrewAI kickoff."""
        now = time.time()
        process_name = process.value if hasattr(process, "value") else str(process)
        trace_steps: list[dict[str, Any]] = [
            {
                "type": "crew_start",
                "agent": "CrewAI",
                "description": f"Supercharged workflow {workflow.id} kickoff with {len(tasks)} native tasks",
                "timestamp": now,
                "details": {
                    "process": process_name,
                    "workflow_type": getattr(workflow.workflow_type, "value", workflow.workflow_type),
                    "runtime": "crewai_advanced",
                },
            },
            {
                "type": "memory",
                "agent": "CrewAI",
                "description": "Enterprise Memory Subsystem Active",
                "timestamp": now,
                "details": workflow.memory.model_dump(mode="json") if hasattr(workflow, "memory") else {"enabled": self.memory_enabled},
            },
            {
                "type": "knowledge",
                "agent": "CrewAI",
                "description": "Dynamic Knowledge Sources Connected",
                "timestamp": now,
                "details": workflow.knowledge.model_dump(mode="json") if hasattr(workflow, "knowledge") else {"enabled": True, "sources_resolved": True},
            },
        ]
        for index, (meta, task) in enumerate(zip(task_metas, tasks), start=1):
            trace_steps.append(
                {
                    "type": "task_planned",
                    "agent": meta.agent_id,
                    "description": f"Orchestrated Task {index} mapped to state node {meta.node_id}",
                    "timestamp": now,
                    "details": {
                        "node_id": meta.node_id,
                        "task_preview": getattr(task, "description", "")[:240],
                        "expected_output": getattr(task, "expected_output", None),
                    },
                }
            )
        for agent in crew_agents:
            tools = getattr(agent, "tools", []) or []
            trace_steps.append(
                {
                    "type": "agent_ready",
                    "agent": getattr(agent, "role", "agent"),
                    "description": f"Specialist Agent online leveraging {len(tools)} embedded tool capabilities",
                    "timestamp": now,
                    "details": {"tool_count": len(tools)},
                }
            )
        return trace_steps

    def _workflow_tool_ids(
        self,
        workflow: WorkflowConfig,
        agent_configs: dict[str, AgentConfig],
    ) -> list[str]:
        """Return the configured tools expected to be available during execution."""
        tool_ids: list[str] = []
        for node in workflow.topology.nodes:
            config = agent_configs.get(node.agent_id)
            if not config:
                continue
            for tool_id in config.tools:
                if tool_id not in tool_ids:
                    tool_ids.append(tool_id)
        return tool_ids
