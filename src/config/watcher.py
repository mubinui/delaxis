"""File system watcher for hot reloading configurations."""

import time
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from src.audit_logging import get_logger

logger = get_logger(__name__)


class ConfigFileEventHandler(FileSystemEventHandler):
    """Handler for configuration file change events."""

    def __init__(
        self,
        on_change: Callable[[], None],
        debounce_seconds: float = 1.0,
    ) -> None:
        """
        Initialize the event handler.

        Args:
            on_change: Callback function to execute when files change
            debounce_seconds: Minimum time between reload triggers
        """
        super().__init__()
        self.on_change = on_change
        self.debounce_seconds = debounce_seconds
        self._last_reload_time = 0.0
        self._pending_reload = False

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle file modification events."""
        if event.is_directory:
            return

        # Only watch JSON files
        if not event.src_path.endswith(".json"):
            return

        logger.debug("Configuration file modified", file=event.src_path)

        # Debounce rapid changes
        current_time = time.time()
        if current_time - self._last_reload_time < self.debounce_seconds:
            self._pending_reload = True
            logger.debug("Debouncing reload")
            return

        self._trigger_reload()

    def _trigger_reload(self) -> None:
        """Trigger configuration reload."""
        try:
            self._last_reload_time = time.time()
            self._pending_reload = False

            logger.info("Triggering configuration reload")
            self.on_change()

        except Exception as e:
            logger.error("Failed to reload configuration", error=str(e))


class ConfigWatcher:
    """Watches configuration directory for changes and triggers reloads."""

    def __init__(
        self,
        config_dir: Path | str,
        on_reload: Callable[[], None],
        debounce_seconds: float = 1.0,
    ) -> None:
        """
        Initialize the configuration watcher.

        Args:
            config_dir: Directory to watch
            on_reload: Callback to execute when configuration changes
            debounce_seconds: Minimum time between reloads
        """
        self.config_dir = Path(config_dir)
        self.on_reload = on_reload
        self.debounce_seconds = debounce_seconds

        self._observer: Observer | None = None
        self._event_handler: ConfigFileEventHandler | None = None

    def start(self) -> None:
        """Start watching for configuration changes."""
        if self._observer is not None:
            logger.warning("Config watcher already started")
            return

        logger.info(
            "Starting configuration watcher",
            config_dir=str(self.config_dir),
        )

        self._event_handler = ConfigFileEventHandler(
            on_change=self.on_reload,
            debounce_seconds=self.debounce_seconds,
        )

        self._observer = Observer()
        self._observer.schedule(
            self._event_handler,
            str(self.config_dir),
            recursive=False,
        )
        self._observer.start()

        logger.info("Configuration watcher started")

    def stop(self) -> None:
        """Stop watching for configuration changes."""
        if self._observer is None:
            return

        logger.info("Stopping configuration watcher")

        self._observer.stop()
        self._observer.join(timeout=5.0)
        self._observer = None
        self._event_handler = None

        logger.info("Configuration watcher stopped")

    def is_running(self) -> bool:
        """Check if watcher is running."""
        return self._observer is not None and self._observer.is_alive()


async def watch_configs_async(
    config_dir: Path | str,
    on_reload: Callable[[], None],
    debounce_seconds: float = 1.0,
) -> ConfigWatcher:
    """
    Start watching configuration directory asynchronously.

    Args:
        config_dir: Directory to watch
        on_reload: Callback to execute when configuration changes
        debounce_seconds: Minimum time between reloads

    Returns:
        ConfigWatcher instance
    """
    watcher = ConfigWatcher(config_dir, on_reload, debounce_seconds)
    watcher.start()

    # Return watcher so caller can stop it later
    return watcher
