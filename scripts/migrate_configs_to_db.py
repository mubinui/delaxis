#!/usr/bin/env python3
"""
Migration script to populate the Library database from existing JSON configurations.

Usage:
    python scripts/migrate_configs_to_db.py

This will read existing configurations from configs/ and insert them into the database.
"""

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config.settings import get_settings
from src.infrastructure.database.config_store import ConfigStore


def load_json_file(file_path: Path) -> dict:
    """Load and parse a JSON file."""
    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def migrate_agents(store: ConfigStore, agents_file: Path):
    """Migrate agents from agents.json to database."""
    print(f"\n📋 Migrating agents from {agents_file}...")

    data = load_json_file(agents_file)
    agents = data.get("agents", [])

    migrated = 0
    for agent in agents:
        agent_id = agent.get("id")
        agent_name = agent.get("name", agent_id)
        agent_type = agent.get("type", "conversable")
        description = agent.get("description", "")

        # Use the entire agent config as the stored config
        config = {
            "id": agent.get("id"),
            "type": agent.get("type"),
            "name": agent.get("name"),
            "instruction": agent.get("instruction"),
            "model_config": agent.get("model_config"),
            "tools": agent.get("tools", []),
            "output_key": agent.get("output_key"),
            "is_selector": agent.get("is_selector", False),
            "description": agent.get("description"),
            "system_message": agent.get("system_message"),
            "llm_config": agent.get("llm_config"),
            "human_input_mode": agent.get("human_input_mode", "NEVER"),
            "code_execution_config": agent.get("code_execution_config", False),
            "max_consecutive_auto_reply": agent.get("max_consecutive_auto_reply", 10),
        }

        try:
            # Check if already exists (by matching name + type)
            # Since we don't have a search method, we'll just try to create
            store.create_item(
                item_type="agent",
                name=agent_name,
                description=description,
                config=config,
                type=agent_type,
            )
            print(f"  ✓ Migrated agent: {agent_name} ({agent_type})")
            migrated += 1
        except Exception as e:
            print(f"  ✗ Failed to migrate {agent_name}: {e}")

    print(f"✅ Migrated {migrated}/{len(agents)} agents")


def migrate_tools(store: ConfigStore, tools_file: Path):
    """Migrate tools from tools.json to database."""
    print(f"\n🔧 Migrating tools from {tools_file}...")

    data = load_json_file(tools_file)
    tools = data.get("tools", [])

    migrated = 0
    for tool in tools:
        tool_id = tool.get("id")
        tool_name = tool.get("name", tool_id)
        description = tool.get("description", "")

        # Determine tool type
        settings = tool.get("settings", {})
        if settings.get("type") == "api":
            tool_type = "api"
        else:
            tool_type = "function"

        # Use the entire tool config
        config = {
            "id": tool.get("id"),
            "name": tool.get("name"),
            "description": tool.get("description"),
            "entrypoint": tool.get("entrypoint"),
            "enabled": tool.get("enabled", True),
            "is_async": tool.get("is_async", False),
            "settings": tool.get("settings", {}),
            "version": tool.get("version", 1),
            "last_updated": tool.get("last_updated"),
        }

        try:
            store.create_item(
                item_type="tool",
                name=tool_name,
                description=description,
                config=config,
                type=tool_type,
            )
            print(f"  ✓ Migrated tool: {tool_name} ({tool_type})")
            migrated += 1
        except Exception as e:
            print(f"  ✗ Failed to migrate {tool_name}: {e}")

    print(f"✅ Migrated {migrated}/{len(tools)} tools")


def migrate_workflows(store: ConfigStore, workflows_file: Path):
    """Migrate workflows from workflows.json to database."""
    print(f"\n⚙️  Migrating workflows from {workflows_file}...")

    data = load_json_file(workflows_file)
    workflows = data.get("workflows", [])

    migrated = 0
    for workflow in workflows:
        workflow_id = workflow.get("id")
        workflow_name = workflow.get("name", workflow_id)
        description = workflow.get("description", "")

        # Use the entire workflow config
        config = {
            "id": workflow.get("id"),
            "name": workflow.get("name"),
            "description": workflow.get("description"),
            "enabled": workflow.get("enabled", True),
            "pattern": workflow.get("pattern"),
            "topology": workflow.get("topology", {}),
            "execution_strategy": workflow.get("execution_strategy", "sequential"),
            "metadata": workflow.get("metadata", {}),
        }

        try:
            store.create_item(
                item_type="workflow", name=workflow_name, description=description, config=config
            )
            print(f"  ✓ Migrated workflow: {workflow_name}")
            migrated += 1
        except Exception as e:
            print(f"  ✗ Failed to migrate {workflow_name}: {e}")

    print(f"✅ Migrated {migrated}/{len(workflows)} workflows")


def main():
    """Main migration function."""
    print("=" * 60)
    print("🚀 Starting Configuration Migration to Database")
    print("=" * 60)

    # Get settings and initialize store
    settings = get_settings()
    database_url = settings.memory.database_url

    if not database_url:
        print("❌ DATABASE_URL not configured in settings")
        return

    # Convert asyncpg to psycopg2 if needed
    if "asyncpg" in database_url:
        database_url = database_url.replace("+asyncpg", "")

    store = ConfigStore(database_url=database_url)

    # Define paths
    config_dir = Path(__file__).parent.parent / "configs"
    agents_file = config_dir / "agents.json"
    tools_file = config_dir / "tools.json"
    workflows_file = config_dir / "workflows.json"

    # Check files exist
    for file_path in [agents_file, tools_file, workflows_file]:
        if not file_path.exists():
            print(f"❌ File not found: {file_path}")
            return

    # Run migrations
    try:
        migrate_agents(store, agents_file)
        migrate_tools(store, tools_file)
        migrate_workflows(store, workflows_file)

        print("\n" + "=" * 60)
        print("✨ Migration completed successfully!")
        print("=" * 60)
        print("\nYou can now view these items in the workflow editor sidebar.")

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback

        traceback.print_exc()
    finally:
        store.close()


if __name__ == "__main__":
    main()
