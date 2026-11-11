"""Throttling of the endpoints that check a password: login and password change (Redis-backed).

Failed attempts are counted per client IP and per account in a fixed window of LOGIN_THROTTLE_WINDOW_SECONDS
(default 900). From LOGIN_MAX_FAILURES_PER_ACCOUNT failures on one account (default 5) or
LOGIN_MAX_FAILURES_PER_IP failures from one IP (default 30) the endpoint answers 429, with Retry-After, until
that window ends. A successful attempt clears the account counter (not the IP one). A limit of 0 turns it off.

The client IP is the one ProxyFix takes from X-Forwarded-For (TRUSTED_PROXY_COUNT, the proxies between client
and backend): without it every request would come from the last proxy and the IP limit would apply to everyone
at once; with a count higher than the real one the client could choose its IP and bypass the limit.
If Redis does not answer the attempt is let through (logged): an outage of Redis must not lock users out.
"""
from __future__ import annotations

import hashlib
import math

import redis as redis_lib
import structlog
from flask import current_app, jsonify

from app.core.i18n import api_error

log = structlog.get_logger()

# One client per Redis URL, created on first use (the backend runs gevent workers: the pool is shared)
_clients: dict[str, redis_lib.Redis] = {}


def _client() -> redis_lib.Redis:
    url = current_app.config["REDIS_URL"]
    client = _clients.get(url)
    if client is None:
        client = redis_lib.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        _clients[url] = client
    return client


def _window() -> int:
    return max(1, int(current_app.config.get("LOGIN_THROTTLE_WINDOW_SECONDS", 900)))


def _keys(scope: str, ip: str | None, account: str | None) -> list[tuple[str, int]]:
    """(Redis key, limit) of the counters an attempt touches. The account goes in hashed: no e-mail in Redis."""
    cfg = current_app.config
    keys = []
    if ip:
        keys.append((f"throttle:{scope}:ip:{ip}", int(cfg.get("LOGIN_MAX_FAILURES_PER_IP", 30))))
    if account:
        digest = hashlib.sha256(account.strip().lower().encode("utf-8")).hexdigest()[:32]
        keys.append((f"throttle:{scope}:acct:{digest}", int(cfg.get("LOGIN_MAX_FAILURES_PER_ACCOUNT", 5))))
    return [(key, limit) for key, limit in keys if limit > 0]


def blocked_for(scope: str, ip: str | None, account: str | None) -> int:
    """Seconds before another attempt is allowed; 0 if it is allowed now."""
    try:
        client = _client()
        wait = 0
        for key, limit in _keys(scope, ip, account):
            count = client.get(key)
            if count is not None and int(count) >= limit:
                ttl = client.ttl(key)
                wait = max(wait, ttl if ttl and ttl > 0 else _window())
        return wait
    except redis_lib.RedisError as e:
        log.warning("login_throttle_unavailable", scope=scope, error=str(e)[:200])
        return 0


def record_failure(scope: str, ip: str | None, account: str | None) -> None:
    """Counts a failed attempt. The window starts at the first failure (EXPIRE NX), it is not extended."""
    keys = _keys(scope, ip, account)
    if not keys:
        return
    try:
        pipe = _client().pipeline(transaction=True)
        for key, _limit in keys:
            pipe.incr(key)
            pipe.expire(key, _window(), nx=True)
        pipe.execute()
    except redis_lib.RedisError as e:
        log.warning("login_throttle_unavailable", scope=scope, error=str(e)[:200])


def clear_account(scope: str, account: str | None) -> None:
    """After a successful attempt the account starts again from zero (the IP counter stays)."""
    keys = [key for key, _limit in _keys(scope, None, account)]
    if not keys:
        return
    try:
        _client().delete(*keys)
    except redis_lib.RedisError as e:
        log.warning("login_throttle_unavailable", scope=scope, error=str(e)[:200])


def too_many_attempts(wait: int):
    """429 with the minutes to wait, in the language of the request, and Retry-After in seconds."""
    minutes = max(1, math.ceil(wait / 60))
    response = jsonify({"error": api_error("too_many_attempts", minutes=minutes), "code": "too_many_attempts",
                        "retry_after": wait})
    response.status_code = 429
    response.headers["Retry-After"] = str(wait)
    return response
