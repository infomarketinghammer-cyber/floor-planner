"""The visitor's IP address behind proxies, for rate limits."""

from fastapi import Request

from app.core.config import get_settings


def client_ip(request: Request) -> str:
    """Each proxy appends the address it received the request from to X-Forwarded-For, and the
    last proxy is the connection itself. With `trust_proxy` = N, the address N hops back is the
    visitor; anything further left was sent by the client and can't be trusted."""
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    chain = [*hops, request.client.host if request.client else "unknown"]
    n = max(get_settings().trust_proxy, 0)
    return chain[max(len(chain) - 1 - n, 0)]
