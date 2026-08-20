"""Context tree — let an agent navigate a file tree instead of being handed a blob.

Dumping a whole corpus into a prompt is expensive and usually wrong: the agent
reads everything to use a fraction. These tools give it the same access a person
has — see the shape, search it, then open only what matters:

* :func:`context_tree` — the structure, depth-limited.
* :func:`search_context_tree` — find files by name or content.
* :func:`read_context_file` — open one file, or a line range of it.
* :func:`describe_context_file` — size, type, and an outline, without the body.

**Sandboxing.** Every path is resolved (symlinks included) and must land inside
a configured root, so ``../../.ssh/id_rsa`` fails whether it arrives as a
traversal, an absolute path, or a symlink planted inside the tree. Roots come
from ``DELAXIS_CONTEXT_ROOTS`` (os.pathsep-separated); the default is the
uploads directory plus ``data/context``, never the whole filesystem.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config.env_compat import env

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Directories that are never useful as agent context and are expensive to walk.
DEFAULT_IGNORES: tuple[str, ...] = (
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode",
    "dist", "build", ".next", ".cache", "htmlcov", ".DS_Store",
)

TEXT_SUFFIXES: frozenset[str] = frozenset({
    ".txt", ".md", ".markdown", ".rst", ".json", ".jsonl", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".env", ".csv", ".tsv", ".xml", ".html",
    ".htm", ".css", ".scss", ".js", ".jsx", ".ts", ".tsx", ".py", ".rb", ".go",
    ".rs", ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cs", ".php", ".sh",
    ".bash", ".zsh", ".sql", ".graphql", ".proto", ".log", ".tex", ".srt",
})

MAX_READ_BYTES = 256_000
MAX_SEARCH_FILES = 2_000
MAX_TREE_ENTRIES = 1_000


class ContextAccessError(Exception):
    """Raised when a path escapes the sandbox or does not exist."""


# --------------------------------------------------------------------------- #
# Root resolution and sandboxing
# --------------------------------------------------------------------------- #


def _data_dir() -> Path:
    default = str(_PROJECT_ROOT / "data")
    return Path(env("DELAXIS_DATA_DIR", default) or default)


def context_roots() -> list[Path]:
    """The directories agents may read. Configured, never implicit."""
    configured = env("DELAXIS_CONTEXT_ROOTS", "") or ""
    if configured.strip():
        roots = [Path(part).expanduser() for part in configured.split(os.pathsep) if part.strip()]
    else:
        data = _data_dir()
        roots = [data / "uploads", data / "context"]

    resolved: list[Path] = []
    for root in roots:
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            # A configured-but-uncreatable root is skipped rather than fatal;
            # the remaining roots still work.
            continue
        resolved.append(root.resolve())
    return resolved


def resolve_in_sandbox(path: str) -> Path:
    """Resolve ``path`` and confirm it sits inside a configured root.

    ``Path.resolve()`` runs before the containment check, so symlinks pointing
    out of the tree are caught rather than followed.
    """
    roots = context_roots()
    if not roots:
        raise ContextAccessError(
            "No context roots are configured or creatable. Set DELAXIS_CONTEXT_ROOTS."
        )

    candidate = Path(path).expanduser() if path else Path(".")
    if not candidate.is_absolute():
        # A relative path is interpreted against each root in turn, so an agent
        # can say "reports/q3.md" without knowing the absolute layout.
        for root in roots:
            merged = (root / candidate).resolve()
            if _within(merged, root) and merged.exists():
                return merged
        # Nothing exists yet — resolve against the first root so the caller gets
        # a "not found" naming a real path instead of a sandbox error.
        candidate = (roots[0] / candidate).resolve()
    else:
        candidate = candidate.resolve()

    for root in roots:
        if _within(candidate, root):
            return candidate

    raise ContextAccessError(
        f"Path '{path}' is outside every configured context root. "
        f"Allowed roots: {', '.join(str(root) for root in roots)}"
    )


def _within(candidate: Path, root: Path) -> bool:
    return candidate == root or root in candidate.parents


def _relative_label(path: Path) -> str:
    """Present paths relative to their root, so absolute layout never leaks."""
    for root in context_roots():
        if _within(path, root):
            relative = path.relative_to(root)
            return str(relative) if str(relative) != "." else root.name
    return path.name


def _ignored(name: str, extra: tuple[str, ...]) -> bool:
    if name in DEFAULT_IGNORES:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in extra)


def _is_texty(path: Path) -> bool:
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    try:
        chunk = path.open("rb").read(2048)
    except OSError:
        return False
    if b"\x00" in chunk:
        return False
    try:
        chunk.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _human_size(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}GB"


# --------------------------------------------------------------------------- #
# Tree
# --------------------------------------------------------------------------- #


@dataclass
class _TreeStats:
    directories: int = 0
    files: int = 0
    bytes: int = 0
    truncated: bool = False


def _walk_tree(
    directory: Path,
    depth: int,
    max_depth: int,
    prefix: str,
    ignores: tuple[str, ...],
    stats: _TreeStats,
    lines: list[str],
) -> None:
    if depth > max_depth or stats.files + stats.directories >= MAX_TREE_ENTRIES:
        return
    try:
        entries = sorted(
            (entry for entry in directory.iterdir() if not _ignored(entry.name, ignores)),
            # Directories first, then files, each alphabetically — the shape of
            # the tree is what the agent is reading for.
            key=lambda entry: (not entry.is_dir(), entry.name.lower()),
        )
    except (OSError, PermissionError) as exc:
        lines.append(f"{prefix}└── [unreadable: {exc.__class__.__name__}]")
        return

    for index, entry in enumerate(entries):
        if stats.files + stats.directories >= MAX_TREE_ENTRIES:
            stats.truncated = True
            return
        last = index == len(entries) - 1
        connector = "└── " if last else "├── "
        if entry.is_dir():
            stats.directories += 1
            lines.append(f"{prefix}{connector}{entry.name}/")
            if depth < max_depth:
                _walk_tree(
                    entry, depth + 1, max_depth,
                    prefix + ("    " if last else "│   "),
                    ignores, stats, lines,
                )
        else:
            stats.files += 1
            try:
                size = entry.stat().st_size
            except OSError:
                size = 0
            stats.bytes += size
            lines.append(f"{prefix}{connector}{entry.name}  ({_human_size(size)})")


def context_tree(path: str = "", max_depth: int = 3, ignore: str = "") -> str:
    """
    Show the structure of a directory as an indented tree.

    Start here to find out what context is available before reading anything.
    Files are listed with their size so you can judge what is worth opening.

    Args:
        path: Directory to describe, relative to a context root. Empty means
            every configured root.
        max_depth: How many levels to descend (1-10, default 3).
        ignore: Extra comma-separated glob patterns to skip, e.g. "*.log,tmp*".

    Returns:
        JSON: {"tree": str, "directories": int, "files": int, "total_size": str}
    """
    depth_limit = max(1, min(int(max_depth), 10))
    extra_ignores = tuple(part.strip() for part in ignore.split(",") if part.strip())
    stats = _TreeStats()
    lines: list[str] = []

    try:
        if path:
            targets = [resolve_in_sandbox(path)]
        else:
            targets = context_roots()
            if not targets:
                return json.dumps({"error": "No context roots are configured."})
    except ContextAccessError as exc:
        return json.dumps({"error": str(exc)})

    for target in targets:
        if not target.exists():
            return json.dumps({"error": f"'{path}' does not exist."})
        if target.is_file():
            return json.dumps(
                {"error": f"'{path}' is a file, not a directory. Use read_context_file instead."}
            )
        lines.append(f"{_relative_label(target)}/")
        _walk_tree(target, 1, depth_limit, "", extra_ignores, stats, lines)

    if stats.truncated:
        lines.append(f"... truncated at {MAX_TREE_ENTRIES} entries — narrow the path or depth")

    return json.dumps(
        {
            "tree": "\n".join(lines),
            "directories": stats.directories,
            "files": stats.files,
            "total_size": _human_size(stats.bytes),
            "truncated": stats.truncated,
        },
        indent=2,
    )


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #


def read_context_file(path: str, start_line: int = 1, end_line: int = 0) -> str:
    """
    Read a text file from the context tree, optionally just part of it.

    Args:
        path: File to read, relative to a context root.
        start_line: First line to return, 1-indexed (default 1).
        end_line: Last line to return. 0 means read to the end.

    Returns:
        JSON: {"path": str, "content": str, "lines": int, "truncated": bool}
    """
    try:
        target = resolve_in_sandbox(path)
    except ContextAccessError as exc:
        return json.dumps({"error": str(exc)})

    if not target.exists():
        return json.dumps({"error": f"'{path}' does not exist."})
    if target.is_dir():
        return json.dumps({"error": f"'{path}' is a directory. Use context_tree instead."})
    if not _is_texty(target):
        return json.dumps(
            {
                "error": f"'{path}' is not a text file. Use analyze_file for binary "
                "documents and images."
            }
        )

    try:
        size = target.stat().st_size
        with target.open("r", encoding="utf-8", errors="replace") as handle:
            body = handle.read(MAX_READ_BYTES)
    except OSError as exc:
        return json.dumps({"error": f"Could not read '{path}': {exc}"})

    truncated = size > MAX_READ_BYTES
    all_lines = body.splitlines()
    first = max(1, int(start_line))
    last = len(all_lines) if int(end_line) <= 0 else min(int(end_line), len(all_lines))
    selected = all_lines[first - 1 : last] if first <= len(all_lines) else []

    return json.dumps(
        {
            "path": _relative_label(target),
            "content": "\n".join(selected),
            "lines": len(selected),
            "total_lines": len(all_lines),
            "start_line": first,
            "end_line": last,
            "truncated": truncated,
        },
        indent=2,
    )


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #


def _candidate_files(root: Path, name_glob: str, ignores: tuple[str, ...]) -> Iterator[Path]:
    seen = 0
    for current, directories, filenames in os.walk(root):
        directories[:] = [name for name in directories if not _ignored(name, ignores)]
        for filename in filenames:
            if _ignored(filename, ignores):
                continue
            if name_glob and not fnmatch.fnmatch(filename, name_glob):
                continue
            seen += 1
            if seen > MAX_SEARCH_FILES:
                return
            yield Path(current) / filename


def search_context_tree(
    query: str,
    path: str = "",
    file_pattern: str = "",
    max_results: int = 30,
    case_sensitive: bool = False,
) -> str:
    """
    Search the context tree for text and return matching lines with their locations.

    Use this to locate the handful of files worth reading in full.

    Args:
        query: Text or regular expression to find.
        path: Directory to search within, relative to a context root. Empty
            means every root.
        file_pattern: Optional filename glob, e.g. "*.md" or "invoice-*.csv".
        max_results: Maximum matching lines to return (1-200, default 30).
        case_sensitive: Match case exactly (default false).

    Returns:
        JSON: {"count": int, "matches": [{"path", "line", "text"}], ...}
    """
    if not query or not query.strip():
        return json.dumps({"error": "A non-empty 'query' is required."})

    try:
        pattern = re.compile(query if case_sensitive else f"(?i){query}")
    except re.error as exc:
        # A plain string containing regex metacharacters is the common case, so
        # fall back to a literal search rather than failing the call.
        pattern = re.compile(re.escape(query) if case_sensitive else f"(?i){re.escape(query)}")
        del exc

    try:
        roots = [resolve_in_sandbox(path)] if path else context_roots()
    except ContextAccessError as exc:
        return json.dumps({"error": str(exc)})
    if not roots:
        return json.dumps({"error": "No context roots are configured."})

    limit = max(1, min(int(max_results), 200))
    matches: list[dict[str, Any]] = []
    files_scanned = 0

    for root in roots:
        if root.is_file():
            candidates: Iterator[Path] = iter([root])
        else:
            candidates = _candidate_files(root, file_pattern, ())
        for candidate in candidates:
            if len(matches) >= limit:
                break
            if not _is_texty(candidate):
                continue
            files_scanned += 1
            try:
                with candidate.open("r", encoding="utf-8", errors="replace") as handle:
                    for number, line in enumerate(handle, start=1):
                        if pattern.search(line):
                            matches.append(
                                {
                                    "path": _relative_label(candidate),
                                    "line": number,
                                    "text": line.strip()[:300],
                                }
                            )
                            if len(matches) >= limit:
                                break
            except OSError:
                continue

    return json.dumps(
        {
            "count": len(matches),
            "files_scanned": files_scanned,
            "truncated": len(matches) >= limit,
            "matches": matches,
        },
        indent=2,
    )


# --------------------------------------------------------------------------- #
# Describe
# --------------------------------------------------------------------------- #

_OUTLINE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (".md", re.compile(r"^(#{1,6})\s+(.*)$")),
    (".py", re.compile(r"^(?:class|def|async def)\s+(\w+)")),
    (".ts", re.compile(r"^(?:export\s+)?(?:class|function|const|interface|type)\s+(\w+)")),
    (".tsx", re.compile(r"^(?:export\s+)?(?:class|function|const|interface|type)\s+(\w+)")),
    (".js", re.compile(r"^(?:export\s+)?(?:class|function|const)\s+(\w+)")),
    (".sql", re.compile(r"(?i)^(?:create|alter|drop)\s+(?:table|view|index)\s+(\S+)")),
)


def _outline(path: Path, body: str) -> list[str]:
    rule = next((regex for suffix, regex in _OUTLINE_RULES if path.suffix.lower() == suffix), None)
    if rule is None:
        return []
    found: list[str] = []
    for line in body.splitlines():
        match = rule.match(line)
        if match:
            found.append(line.strip()[:120])
        if len(found) >= 60:
            break
    return found


def describe_context_file(path: str) -> str:
    """
    Summarise a file without returning its contents — size, type, and structure.

    Use this to decide whether a file is worth reading, especially a large one.
    For a Markdown file you get its headings; for source code, its top-level
    definitions.

    Args:
        path: File to describe, relative to a context root.

    Returns:
        JSON: {"path", "size", "kind", "lines", "outline": [...], "preview": str}
    """
    try:
        target = resolve_in_sandbox(path)
    except ContextAccessError as exc:
        return json.dumps({"error": str(exc)})

    if not target.exists():
        return json.dumps({"error": f"'{path}' does not exist."})
    if target.is_dir():
        return json.dumps({"error": f"'{path}' is a directory. Use context_tree instead."})

    try:
        stat = target.stat()
    except OSError as exc:
        return json.dumps({"error": f"Could not stat '{path}': {exc}"})

    from datetime import datetime, timezone

    report: dict[str, Any] = {
        "path": _relative_label(target),
        "size": _human_size(stat.st_size),
        "size_bytes": stat.st_size,
        "suffix": target.suffix.lower() or None,
        "modified": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }

    if not _is_texty(target):
        report["kind"] = "binary"
        report["note"] = "Binary file — use analyze_file to extract text or inspect an image."
        return json.dumps(report, indent=2)

    try:
        with target.open("r", encoding="utf-8", errors="replace") as handle:
            body = handle.read(MAX_READ_BYTES)
    except OSError as exc:
        return json.dumps({"error": f"Could not read '{path}': {exc}"})

    report["kind"] = "text"
    report["lines"] = body.count("\n") + 1
    report["outline"] = _outline(target, body)
    report["preview"] = body[:600]
    return json.dumps(report, indent=2)


def list_context_roots() -> str:
    """
    List the directories this agent is allowed to read from.

    Returns:
        JSON with each root, whether it exists, and how many entries it holds.
    """
    roots = []
    for root in context_roots():
        try:
            entries = sum(1 for _ in root.iterdir())
        except OSError:
            entries = 0
        roots.append({"root": root.name, "path": str(root), "entries": entries})
    return json.dumps({"count": len(roots), "roots": roots}, indent=2)
