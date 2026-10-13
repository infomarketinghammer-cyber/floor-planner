import pytest

from app.api.v1.guest import _allowed
from app.core.guest import GuestScope, guest_user, is_guest

P = "/projects/0123456789abcdef01234567"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/projects"),
        ("GET", P),
        ("POST", f"{P}/rooms"),
        ("PATCH", f"{P}/rooms/abc"),
        ("PUT", f"{P}/rooms/abc/walls"),
        ("GET", f"{P}/rooms/abc/layout"),
        ("POST", f"{P}/files"),
        ("POST", f"{P}/files/0123456789abcdef01234567/extract"),
        ("GET", f"{P}/exports/report.pdf?area_unit=sqm"),
        ("PUT", f"{P}/cost/settings"),
        ("GET", f"{P}/scenarios"),
        ("GET", "/tiles?scope=mine"),
    ],
)
def test_guest_routes_allowed(method, path):
    assert _allowed(method, path)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/admin/users"),
        ("GET", "/projects"),  # listing is the browser's job
        ("DELETE", P),  # deleting too
        ("POST", f"{P}/duplicate"),
        ("POST", f"{P}/exports/shopping-list/email"),
        ("POST", f"{P}/feedback"),
        ("POST", f"{P}/evaluation"),
        ("POST", f"{P}/quotes"),
        ("DELETE", "/users/me"),
        ("POST", "/guest/call"),
        ("GET", f"{P}/../admin"),
    ],
)
def test_guest_routes_blocked(method, path):
    assert not _allowed(method, path)


def test_guest_scope_is_temporary():
    assert not is_guest()
    with GuestScope(object(), {}, {"_id": 1}):
        assert is_guest() and guest_user() == {"_id": 1}
    assert not is_guest()
