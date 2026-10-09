"""Keep Redis optional even when it is configured but unreachable.

Redis is an optional accelerator for Delaxis, but two things key off the
``REDIS_URL`` environment variable at import time and then fail hard when the
server is down: CrewAI's lock store (``crewai.utilities.lock_store`` switches
to ``portalocker.RedisLock`` and every ``Crew(...)`` construction then tries
to connect) and our own cache manager. A developer whose ``.env`` still names
a Redis they stopped running would see every workflow run die with
"Error 61 connecting to localhost:6379" and nothing pointing at the cause.

``ensure_redis_or_disable()`` runs once, before anything imports CrewAI or
reads settings. If ``REDIS_URL`` is set and the server does not answer a ping
within a short timeout, the variable is blanked in the process environment and
a warning names what happened, so the rest of the process behaves exactly as if
Redis had never been configured. It is blanked rather than removed because the
settings also read ``.env`` directly, and a process variable (even an empty
one) takes precedence over the file.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

ENV_VAR = "REDIS_URL"
_PING_TIMEOUT_SECONDS = 1.0
_checked = False


def redis_reachable(url: str, timeout: float = _PING_TIMEOUT_SECONDS) -> bool:
    """Return True when a Redis server answers PING at ``url``."""
    try:
        import redis
    except ImportError:
        return False
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=timeout, socket_timeout=timeout)
        try:
            return bool(client.ping())
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001 - any failure means "not reachable"
        logger.debug("redis ping failed", extra={"url": url, "error": str(exc)})
        return False


def ensure_redis_or_disable(*, force: bool = False) -> bool:
    """Drop ``REDIS_URL`` from the environment when the server is unreachable.

    Returns True when Redis stays enabled (either not configured, or configured
    and answering), False when it was configured and has just been disabled.
    Idempotent: later calls are no-ops unless ``force`` is set.
    """
    global _checked
    if _checked and not force:
        return bool(os.environ.get(ENV_VAR, "").strip())
    _checked = True

    # The value usually comes from .env; load it now (without overriding real
    # process variables) so the decision sees what the settings will see.
    try:
        from dotenv import find_dotenv, load_dotenv

        # The working directory's .env, as the settings read it (see config.loader).
        load_dotenv(find_dotenv(usecwd=True), override=False)
    except ImportError:
        pass

    url = os.environ.get(ENV_VAR, "").strip()
    if not url:
        return True
    if redis_reachable(url):
        return True

    os.environ[ENV_VAR] = ""
    logger.warning(
        "REDIS_URL is set to %s but no Redis answered there. Running without Redis: "
        "sessions and caches stay in-process and CrewAI uses file locks. Start Redis "
        "or remove REDIS_URL from the environment to silence this.",
        url,
    )
    return False


def reset_for_tests() -> None:
    """Forget the cached decision so a test can exercise the check again."""
    global _checked
    _checked = False
