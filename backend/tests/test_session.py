import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.core import client_ip as client_ip_module
from app.core.client_ip import client_ip
from app.core.ratelimit import RateLimiter


def request(xff: str | None, peer: str = "10.0.0.9") -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


@pytest.fixture
def trust(monkeypatch):
    def set_hops(n: int) -> None:
        class S:
            trust_proxy = n

        monkeypatch.setattr(client_ip_module, "get_settings", lambda: S())

    return set_hops


def test_no_proxy_uses_the_connection(trust):
    trust(0)
    assert client_ip(request(None)) == "10.0.0.9"
    assert client_ip(request("6.6.6.6")) == "10.0.0.9"  # a client-sent header is ignored


def test_counts_trusted_hops_from_the_right(trust):
    # Visitor 1.1.1.1 -> Vercel 2.2.2.2 -> Render load balancer 10.0.0.9 -> API
    trust(2)
    assert client_ip(request("1.1.1.1, 2.2.2.2")) == "1.1.1.1"
    # A faked entry on the left is beyond the trusted hops, so it's not used.
    assert client_ip(request("6.6.6.6, 1.1.1.1, 2.2.2.2")) == "1.1.1.1"


def test_fewer_hops_than_trusted_uses_the_leftmost(trust):
    trust(3)
    assert client_ip(request("1.1.1.1")) == "1.1.1.1"


def test_rate_limiter_counts_per_key():
    limiter = RateLimiter(2, 60, "slow down")
    limiter.check("a")
    limiter.check("a")
    with pytest.raises(HTTPException) as e:
        limiter.check("a")
    assert e.value.status_code == 429 and e.value.detail == "slow down"
    limiter.check("b")  # other keys are unaffected
