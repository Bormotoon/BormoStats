"""Build authenticated Redis URLs shared by the backend, workers and scripts."""

from __future__ import annotations

from urllib.parse import quote, urlsplit, urlunsplit


def build_redis_url(url: str, password: str = "", username: str = "") -> str:
    """Inject credentials into a Redis URL unless it already carries a password.

    ``REDIS_URL`` stays credential-free in env templates, while ``REDIS_PASSWORD``
    (and optionally ``REDIS_USERNAME`` for ACL users) is kept separately so it can
    be sourced from a secret store.
    """
    if not password:
        return url

    parts = urlsplit(url)
    if parts.password:
        return url

    host = parts.hostname or "localhost"
    if ":" in host:
        host = f"[{host}]"
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    user = quote(username or parts.username or "", safe="")
    credentials = f"{user}:{quote(password, safe='')}"
    return urlunsplit((parts.scheme, f"{credentials}@{netloc}", parts.path, parts.query, ""))
