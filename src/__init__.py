"""Delaxis multi-agent platform."""

from importlib.metadata import PackageNotFoundError, version

try:
    #: The installed package version; pyproject.toml is the single source.
    __version__ = version("delaxis")
except PackageNotFoundError:  # running from a checkout that was never installed
    __version__ = "0.0.0+unknown"
