"""Where configuration files live.

Every reader and writer of ``configs/*.json`` asks this module, so the whole
platform follows one setting. ``DELAXIS_CONFIG_DIR`` overrides the default,
which is ``configs`` relative to the working directory (the repository root
in development).

The Docker image points it into the data volume so edits made in the Studio
survive the container being recreated; :func:`seed_config_dir` fills that
directory from the configs bundled in the image on first boot.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from src.config.env_compat import env

DEFAULT_CONFIG_DIR = "configs"


def config_dir() -> Path:
    """The directory holding the JSON configuration files."""
    return Path(env("DELAXIS_CONFIG_DIR", DEFAULT_CONFIG_DIR) or DEFAULT_CONFIG_DIR)


def config_path(name: str) -> Path:
    """A configuration file by name, e.g. ``config_path("workflows.json")``."""
    return config_dir() / name


def seed_config_dir(bundled: Path) -> list[str]:
    """Copy bundled config files that are missing from the config directory.

    Existing files are never overwritten: they hold the user's edits. Returns
    the names copied, so the caller can log what was seeded.
    """
    target = config_dir()
    if not bundled.is_dir() or bundled.resolve() == target.resolve():
        return []
    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for source in sorted(bundled.glob("*.json")):
        destination = target / source.name
        if not destination.exists():
            shutil.copy2(source, destination)
            copied.append(source.name)
    return copied
