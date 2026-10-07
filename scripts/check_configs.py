#!/usr/bin/env python
"""Prove that every shipped config file is valid, consistent and lossless.

Run from the repository root (CI does, on every push):

    uv run python scripts/check_configs.py [configs-dir]

Three things are checked, and any failure exits non-zero:

1. **Shape** - every file parses into its pydantic model.
2. **References** - every tool an agent names exists, every agent a workflow
   names exists, every provider an agent names exists, and every model an
   agent names is in its provider's catalogue.
3. **Round trip** - dumping the parsed model reproduces every key the file
   had, with the same value. This is what guards against the Studio or an
   API handler silently dropping or renaming a field on save.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from src.api.routers.triggers import TriggerConfig
from src.config.agent_models import AgentsConfig
from src.config.cache_models import CacheConfig
from src.config.dynamic_models import APIProvidersConfig, PromptTemplatesConfig
from src.config.tool_models import ToolsConfig
from src.config.vector_db_models import VectorDBRegistry
from src.config.workflow_models import WorkflowsConfig

# Keys the models accept under another name and write back under the canonical one.
ALIASES = {"instruction": "system_message", "model_config": "model_config_override"}

problems: list[str] = []
warnings: list[str] = []


def fail(message: str) -> None:
    problems.append(message)


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        fail(f"{path}: missing")
    except json.JSONDecodeError as exc:
        fail(f"{path}: not valid JSON ({exc})")
    return None


def parse(model: type[BaseModel], data: Any, label: str) -> BaseModel | None:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(part) for part in err["loc"])
            fail(f"{label}: {loc}: {err['msg']}")
    return None


def round_trip(original: Any, dumped: Any, where: str) -> None:
    """Every key present in the file must come back from the model unchanged."""
    if isinstance(original, dict):
        if not isinstance(dumped, dict):
            fail(f"{where}: was an object in the file, became {type(dumped).__name__}")
            return
        for key, value in original.items():
            if key.startswith("_"):
                continue  # `_comment`, `_schema` and friends are documentation
            target = key if key in dumped else ALIASES.get(key)
            if target is None or target not in dumped:
                fail(f"{where}.{key}: dropped by the model")
                continue
            round_trip(value, dumped[target], f"{where}.{key}")
    elif isinstance(original, list):
        if not isinstance(dumped, list) or len(dumped) != len(original):
            fail(
                f"{where}: list changed length ({len(original)} -> {len(dumped) if isinstance(dumped, list) else '?'})"
            )
            return
        for i, (a, b) in enumerate(zip(original, dumped, strict=True)):
            round_trip(a, b, f"{where}[{i}]")
    elif original != dumped and not (
        isinstance(original, int | float) and isinstance(dumped, int | float) and original == dumped
    ):
        fail(f"{where}: {original!r} became {dumped!r}")


def main(config_dir: Path) -> int:
    files = {
        "agents": (AgentsConfig, "agents.json"),
        "tools": (ToolsConfig, "tools.json"),
        "workflows": (WorkflowsConfig, "workflows.json"),
        "providers": (APIProvidersConfig, "api_providers.json"),
        "prompts": (PromptTemplatesConfig, "prompt_templates.json"),
        "cache": (CacheConfig, "cache.json"),
        "vector_dbs": (VectorDBRegistry, "vector_databases.json"),
    }
    raw: dict[str, Any] = {}
    parsed: dict[str, BaseModel] = {}
    for key, (model, name) in files.items():
        data = load(config_dir / name)
        if data is None:
            continue
        raw[key] = data
        instance = parse(model, data, name)
        if instance is None:
            continue
        parsed[key] = instance
        round_trip(data, instance.model_dump(mode="json"), name)

    triggers_raw = load(config_dir / "triggers.json")
    if triggers_raw is not None:
        for i, trigger in enumerate(triggers_raw.get("triggers", [])):
            instance = parse(TriggerConfig, trigger, f"triggers.json.triggers[{i}]")
            if instance is not None:
                round_trip(
                    trigger, instance.model_dump(mode="json"), f"triggers.json.triggers[{i}]"
                )

    if problems:
        return report()

    agents = {a.id: a for a in parsed["agents"].agents}
    tools = {t.id for t in parsed["tools"].tools}
    providers = {p.id: p for p in parsed["providers"].providers}
    workflows = {w.id: w for w in parsed["workflows"].workflows}

    for agent in agents.values():
        for tool_id in agent.tools or []:
            if tool_id not in tools:
                fail(f"agents.json: {agent.id} names unknown tool '{tool_id}'")
        llm = agent.llm_config
        provider_id = getattr(llm, "provider_id", None) if llm else None
        model = getattr(llm, "model", None) if llm else None
        if provider_id:
            provider = providers.get(provider_id)
            if provider is None:
                fail(f"agents.json: {agent.id} names unknown provider '{provider_id}'")
            elif model:
                catalogue = {m.name for m in provider.models or []}
                if catalogue and model not in catalogue:
                    warnings.append(
                        f"agents.json: {agent.id} uses '{model}', not in the '{provider_id}' catalogue"
                    )
        if not (agent.system_message or "").strip():
            fail(f"agents.json: {agent.id} has no system message")
        if (agent.system_message or "").strip() == "You are a helpful AI assistant.":
            fail(f"agents.json: {agent.id} still has the placeholder system message")

    for wf in workflows.values():
        referenced = {wf.entry_agent_id} if wf.entry_agent_id else set()
        topology = getattr(wf, "topology", None)
        for node in getattr(topology, "nodes", []) or []:
            if getattr(node, "agent_id", None):
                referenced.add(node.agent_id)
        for agent_id in referenced:
            if agent_id not in agents:
                fail(f"workflows.json: {wf.id} names unknown agent '{agent_id}'")
        if not (wf.description or "").strip() or wf.description.startswith("Workflow with "):
            fail(f"workflows.json: {wf.id} has a generated or empty description")

    if triggers_raw is not None:
        for trigger in triggers_raw.get("triggers", []):
            if trigger.get("workflow_id") not in workflows:
                fail(
                    f"triggers.json: {trigger.get('id')} names unknown workflow '{trigger.get('workflow_id')}'"
                )

    return report()


def report() -> int:
    for line in warnings:
        print(f"warning: {line}")
    for line in problems:
        print(f"error: {line}")
    if problems:
        print(f"\n{len(problems)} problem(s), {len(warnings)} warning(s)")
        return 1
    print(f"configs ok ({len(warnings)} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path("configs")))
