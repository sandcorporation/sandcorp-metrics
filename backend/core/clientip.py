"""Which address a request came from, shared by every rate limit."""

from django.conf import settings
from django.http import HttpRequest


def client_ip(request: HttpRequest) -> str:
    """The address NPMplus saw. It appends the peer to X-Forwarded-For, so the entry
    `PROXY_HOPS` from the right is trustworthy; the left part is client-supplied and
    forgeable. With 0 hops (no proxy) only REMOTE_ADDR is used."""
    hops: int = settings.PROXY_HOPS
    forwarded = [
        p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()
    ]
    if hops > 0 and len(forwarded) >= hops:
        return str(forwarded[-hops])
    return str(request.META.get("REMOTE_ADDR", ""))
