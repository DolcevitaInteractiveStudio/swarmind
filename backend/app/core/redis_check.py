"""Start-up check of the Redis password (backend, worker and Flower all build the app through create_app).

Redis requires a password (REDIS_PASSWORD in Compose) and REDIS_URL has none, or has a wrong one, or has one
while Redis has none: the app refuses to start with a message that says what to change. Redis not reachable
is not a password problem: the start goes on (Compose starts Redis first, and Celery retries the broker).
"""
from __future__ import annotations

from urllib.parse import urlsplit

import redis as redis_lib

UPGRADE_HINT = ("Set REDIS_PASSWORD in .env (letters and digits only, e.g. openssl rand -hex 32) and recreate the "
                "services: docker compose up -d redis backend worker (see the manual, Operations > Redis password).")


def redis_password_problem(url: str, timeout: float = 3.0) -> str | None:
    """What is wrong with the password in url for the Redis it points to, or None (also when Redis is down)."""
    has_password = bool(urlsplit(url).password)
    client = redis_lib.from_url(url, socket_connect_timeout=timeout, socket_timeout=timeout)
    try:
        client.ping()
        return None
    except redis_lib.AuthenticationError as e:
        text = str(e)
        if "without any password configured" in text:
            return "REDIS_URL has a password but Redis has none: recreate Redis with the Compose file of this " \
                   "version (docker compose up -d redis)."
        if has_password:
            return f"Redis rejected the password in REDIS_URL ({text}). Check REDIS_PASSWORD in .env."
        return f"Redis requires a password and REDIS_URL has none. {UPGRADE_HINT}"
    except redis_lib.ResponseError as e:
        text = str(e)
        if "NOAUTH" in text:
            return f"Redis requires a password and REDIS_URL has none. {UPGRADE_HINT}"
        if "without any password configured" in text:
            return "REDIS_URL has a password but Redis has none: recreate Redis with the Compose file of this " \
                   "version (docker compose up -d redis)."
        return None
    except redis_lib.RedisError:
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass


def ensure_redis_password(url: str) -> None:
    """Raises RuntimeError with the reason when the Redis password is misconfigured."""
    problem = redis_password_problem(url)
    if problem:
        raise RuntimeError(f"SwarMind cannot start: {problem}")
