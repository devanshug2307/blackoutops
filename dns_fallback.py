"""DNS resilience for freshly-provisioned Cognee Cloud tenants.

Cognee Cloud tenant hostnames (tenant-<id>.aws.cognee.ai) are created on signup.
Some public resolvers (notably 1.1.1.1) hold a negative cache from lookups made
before the record existed, so a brand-new tenant can be unreachable for a while
even though it is live. If the system resolver fails for the tenant host, we
resolve it over DNS-over-HTTPS (Google) and pin the answer via a
socket.getaddrinfo patch, so httpx/aiohttp/requests all work unchanged.
"""

from __future__ import annotations

import json
import socket
import urllib.parse
import urllib.request

_real_getaddrinfo = socket.getaddrinfo
_pinned: dict[str, str] = {}


def _resolve_via_doh(hostname: str) -> str | None:
    url = "https://dns.google/resolve?" + urllib.parse.urlencode(
        {"name": hostname, "type": "A"}
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        answers = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
        return answers[0] if answers else None
    except Exception:
        return None


def _patched_getaddrinfo(host, *args, **kwargs):
    if host in _pinned:
        host = _pinned[host]
    return _real_getaddrinfo(host, *args, **kwargs)


def ensure_resolvable(hostname: str) -> str:
    """Make `hostname` resolvable in-process. Returns a note describing the path taken."""
    try:
        socket.getaddrinfo(hostname, 443)
        return f"{hostname}: system DNS OK"
    except socket.gaierror:
        pass

    ip = _resolve_via_doh(hostname)
    if not ip:
        return f"{hostname}: UNRESOLVABLE (system DNS and DoH both failed)"

    _pinned[hostname] = ip
    if socket.getaddrinfo is not _patched_getaddrinfo:
        socket.getaddrinfo = _patched_getaddrinfo
    return f"{hostname}: pinned to {ip} via DNS-over-HTTPS fallback"
