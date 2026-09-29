"""Outbound URL validation that blocks SSRF to internal networks."""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

MAX_URL_LENGTH = 2048


class UnsafeUrlError(ValueError):
    """Raised when an outbound URL is malformed or targets a forbidden address."""


@dataclass(frozen=True)
class ResolvedTarget:
    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]


def _is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return _is_public(address.ipv4_mapped)
    return address.is_global and not (
        address.is_multicast or address.is_reserved or address.is_link_local
    )


def resolve_host(host: str, port: int) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"host {host!r} could not be resolved") from exc
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


def validate_outbound_url(
    url: str,
    *,
    allow_private: bool = False,
    resolve: bool = True,
) -> ResolvedTarget:
    """Validate scheme/host and ensure every resolved address is publicly routable.

    ``allow_private`` (dev only) permits http and private/loopback targets.
    """
    if not url or len(url) > MAX_URL_LENGTH:
        raise UnsafeUrlError("url is empty or too long")
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    allowed_schemes = {"https", "http"} if allow_private else {"https"}
    if scheme not in allowed_schemes:
        raise UnsafeUrlError(f"scheme must be one of {sorted(allowed_schemes)}")
    if parts.username or parts.password:
        raise UnsafeUrlError("credentials in url are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeUrlError("url has no host")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise UnsafeUrlError("invalid port") from exc

    addresses: tuple[str, ...] = ()
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
        if not allow_private and (
            host == "localhost" or host.endswith((".localhost", ".local", ".internal"))
        ):
            raise UnsafeUrlError("internal host names are not allowed") from None
    if literal is not None:
        addresses = (str(literal),)
    elif resolve:
        addresses = resolve_host(host, port)

    if not allow_private:
        for raw in addresses:
            if not _is_public(ipaddress.ip_address(raw)):
                raise UnsafeUrlError(f"url resolves to a non-public address ({raw})")
    return ResolvedTarget(url=url.strip(), scheme=scheme, host=host, port=port, addresses=addresses)
