"""The visitor's IP address behind proxies, for rate limits."""

from fastapi import Request

from app.core.config import get_settings


def forwarding_chain(request: Request) -> list[str]:
    """X-Forwarded-For entries, then the connecting address: the visitor is one of these."""
    hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    return [*hops, request.client.host if request.client else "unknown"]


def client_ip(request: Request) -> str:
    """Each proxy appends the address it received the request from to X-Forwarded-For, and the
    last proxy is the connection itself. With `trust_proxy` = N, the address N hops back is the
    visitor; anything further left was sent by the client and can't be trusted."""
    chain = forwarding_chain(request)
    n = max(get_settings().trust_proxy, 0)
    return chain[max(len(chain) - 1 - n, 0)]
