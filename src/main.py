"""Delaxis command-line chat client.

Runs an interactive (or single-message) chat session against a configured
workflow using the same SessionManager the API uses.
"""

import argparse
import asyncio

from src.api.session_manager import SessionManager, get_session_manager
from src.audit_logging import configure_logging
from src.config.config_loader import get_config_loader
from src.config.registries import get_prompt_registry, get_provider_registry
from src.config.workflow_registry import get_workflow_registry


def _resolve_workflow_id(requested: str | None) -> str:
    """Pick the workflow to chat with: explicit flag, else first enabled workflow."""
    registry = get_workflow_registry()
    if requested:
        if registry.get_workflow(requested) is None:
            available = ", ".join(w.id for w in registry.list_workflows(enabled_only=True)) or "<none>"
            raise SystemExit(f"Workflow not found: {requested}. Available: {available}")
        return requested

    enabled = registry.list_workflows(enabled_only=True)
    if not enabled:
        raise SystemExit("No enabled workflows found in configs/workflows.json")
    return enabled[0].id


async def _print_history(manager: SessionManager, session_id) -> None:
    history = await manager.get_chat_history(session_id)
    print("\n--- Conversation History ---")
    for msg in history.get("messages", []):
        print(f"{msg['role'].capitalize()}: {msg['content']}")
    print(f"Turns: {history.get('turn_count', 0)}")
    print("--- End History ---\n")


def _print_status(session_id, turn_count: int) -> None:
    provider_registry = get_provider_registry()
    prompt_registry = get_prompt_registry()
    print("\n--- System Status ---")
    print(f"Active Session: {session_id}")
    print(f"Turn Count: {turn_count}")
    print(f"Registered Providers: {len(provider_registry.list_providers())}")
    print(f"Enabled Providers: {len(provider_registry.list_enabled_providers())}")
    print(f"Prompt Templates: {len(prompt_registry.list_prompts())}")
    print()


def _reload_configs() -> None:
    print("\nReloading configurations...")
    try:
        get_config_loader().reload_all()
        get_provider_registry().reload_from_config()
        get_prompt_registry().reload_from_config()
        print("✓ Configurations reloaded successfully\n")
    except Exception as e:
        print(f"✗ Failed to reload configurations: {e}\n")


def _print_providers() -> None:
    print("\n--- Available API Providers ---")
    provider_registry = get_provider_registry()
    for provider_id in provider_registry.list_providers():
        provider = provider_registry.get_provider(provider_id)
        if provider:
            status = "✓ enabled" if provider.enabled else "✗ disabled"
            print(f"  {provider_id}: {provider.name} ({provider.type.value}) [{status}]")
    print()


def _print_prompts() -> None:
    print("\n--- Available Prompt Templates ---")
    prompt_registry = get_prompt_registry()
    for prompt_id in prompt_registry.list_prompts():
        prompt = prompt_registry.get_prompt(prompt_id)
        if prompt:
            print(f"  {prompt_id}: {prompt.description} (target: {prompt.target})")
    print()


async def interactive_chat(workflow_id: str | None = None) -> None:
    """Run an interactive chat session."""
    configure_logging()
    manager = get_session_manager()
    workflow_id = _resolve_workflow_id(workflow_id)

    print("=" * 60)
    print("Delaxis — CLI Chat")
    print("=" * 60)
    print(f"\nWorkflow: {workflow_id}")
    print("\nCommands:")
    print("  quit/exit    - End the conversation")
    print("  history      - See conversation history")
    print("  new          - Start a new session")
    print("  reload       - Reload configuration files")
    print("  providers    - List available API providers")
    print("  prompts      - List available prompt templates")
    print("  status       - Show system status\n")

    session = await manager.create_session(workflow_id)
    session_id = session.session_id
    print(f"Session started: {session_id}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye!")
            break

        if not user_input:
            continue

        command = user_input.lower()
        if command in ("quit", "exit"):
            await manager.delete_session(session_id)
            print("\nSession ended. Goodbye!")
            break
        elif command == "new":
            await manager.delete_session(session_id)
            session = await manager.create_session(workflow_id)
            session_id = session.session_id
            print(f"\nNew session started: {session_id}\n")
        elif command == "history":
            await _print_history(manager, session_id)
        elif command == "reload":
            _reload_configs()
        elif command == "providers":
            _print_providers()
        elif command == "prompts":
            _print_prompts()
        elif command == "status":
            current = await manager.get_session(session_id)
            _print_status(session_id, current.turn_count if current else 0)
        else:
            print("Assistant: ", end="", flush=True)
            try:
                result = await manager.process_message(session_id, user_input)
                print(result.get("response", "No response"))
            except Exception as e:
                print(f"Error: {e}")
            print()


async def single_message_mode(message: str, workflow_id: str | None = None) -> None:
    """Process a single message (useful for testing)."""
    configure_logging()
    manager = get_session_manager()
    workflow_id = _resolve_workflow_id(workflow_id)

    session = await manager.create_session(workflow_id)
    try:
        result = await manager.process_message(session.session_id, message)
        print(f"User: {message}")
        print(f"Assistant: {result.get('response', 'No response')}")
    finally:
        await manager.delete_session(session.session_id)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(prog="delaxis", description="Delaxis CLI chat")
    parser.add_argument("--message", "-m", nargs="+", help="Send a single message and exit")
    parser.add_argument("--workflow", "-w", help="Workflow id to chat with (default: first enabled)")
    parser.add_argument("message_words", nargs="*", help="Message text (same as --message)")
    args = parser.parse_args()

    words = args.message or args.message_words
    if words:
        asyncio.run(single_message_mode(" ".join(words), args.workflow))
    else:
        asyncio.run(interactive_chat(args.workflow))


if __name__ == "__main__":
    main()
