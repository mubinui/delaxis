"""Storage for API keys pasted into the studio.

``configs/api_providers.json`` is tracked by git, so writing a key there risks
publishing it. Keys live here instead, under the already-gitignored ``data/``
directory, and the tracked config keeps only non-secret provider settings.

The file is read fresh on every access so a key saved in the studio applies to
the next request without restarting the server. Environment variables remain
the recommended path for deployments; see ``provider_registry`` for precedence.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def secrets_path() -> Path:
    """Location of the secret store, honouring the OAK_DATA_DIR override."""
    data_dir = Path(os.environ.get("OAK_DATA_DIR", str(_PROJECT_ROOT / "data")))
    return data_dir / "provider_secrets.json"


def _load() -> dict[str, Any]:
    path = secrets_path()
    if not path.exists():
        return {"version": "1.0", "secrets": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": "1.0", "secrets": {}}
    if not isinstance(payload.get("secrets"), dict):
        payload["secrets"] = {}
    return payload


def _save(payload: dict[str, Any]) -> None:
    path = secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write via a temp file in the same directory so a crash cannot leave a
    # half-written secret store behind.
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".provider_secrets-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    # Re-assert the mode in case the file already existed with looser bits.
    os.chmod(path, 0o600)


def get_secret(provider_id: str) -> str | None:
    entry = _load()["secrets"].get(str(provider_id))
    if isinstance(entry, dict):
        key = entry.get("api_key")
        return str(key) if key else None
    return str(entry) if entry else None


def has_secret(provider_id: str) -> bool:
    return get_secret(provider_id) is not None


def set_secret(provider_id: str, api_key: str) -> None:
    if not api_key:
        raise ValueError("api_key must not be empty")
    payload = _load()
    payload["secrets"][str(provider_id)] = {
        "api_key": str(api_key),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _save(payload)


def delete_secret(provider_id: str) -> bool:
    payload = _load()
    if str(provider_id) not in payload["secrets"]:
        return False
    payload["secrets"].pop(str(provider_id))
    _save(payload)
    return True


def list_secret_ids() -> list[str]:
    return sorted(_load()["secrets"])
