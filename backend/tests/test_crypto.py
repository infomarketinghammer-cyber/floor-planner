import base64
import os

import pytest

from app.core import config, crypto

KEY = base64.b64encode(os.urandom(32)).decode()


@pytest.fixture
def key(monkeypatch):
    """Run with a given FILE_ENCRYPTION_KEY (None = encryption off)."""

    def use(value: str | None) -> None:
        settings = config.Settings(jwt_secret="test", file_encryption_key=value)
        monkeypatch.setattr(crypto, "get_settings", lambda: settings)

    return use


def test_round_trip_and_tamper_detection(key):
    key(KEY)
    sealed = crypto.encrypt(b"%PDF-1.7 plan")
    assert crypto.is_encrypted(sealed) and b"plan" not in sealed
    assert crypto.decrypt(sealed) == b"%PDF-1.7 plan"
    assert crypto.encrypt(b"same") != crypto.encrypt(b"same")  # fresh nonce every time

    tampered = sealed[:-1] + bytes([sealed[-1] ^ 1])
    with pytest.raises(crypto.EncryptionError, match="changed"):
        crypto.decrypt(tampered)


def test_files_from_before_encryption_still_read(key):
    key(KEY)
    assert crypto.decrypt(b"%PDF-1.7 old plain file") == b"%PDF-1.7 old plain file"


def test_off_without_a_key(key):
    key(None)
    assert not crypto.enabled()
    assert crypto.encrypt(b"data") == b"data"


def test_encrypted_file_needs_the_key(key):
    key(KEY)
    sealed = crypto.encrypt(b"data")
    key(None)
    with pytest.raises(crypto.EncryptionError, match="isn't set"):
        crypto.decrypt(sealed)


def test_wrong_key_is_detected(key):
    key(KEY)
    sealed = crypto.encrypt(b"data")
    key(base64.b64encode(os.urandom(32)).decode())
    with pytest.raises(crypto.EncryptionError, match="key is wrong"):
        crypto.decrypt(sealed)


@pytest.mark.parametrize("bad", ["not base64!", base64.b64encode(b"short").decode()])
def test_bad_keys_fail_at_startup(key, bad):
    key(bad)
    with pytest.raises(crypto.EncryptionError):
        crypto.check_key()


def test_key_survives_copy_paste_slips():
    import base64
    import os

    from app.core.crypto import _cipher

    key = base64.b64encode(os.urandom(32)).decode()  # 44 characters, ends with "="
    data = b"plan"
    nonce = os.urandom(12)
    sealed = _cipher(key).encrypt(nonce, data, None)
    for pasted in (f'"{key}"', f" {key} ", key.rstrip("="), f"'{key}'\n"):
        assert _cipher(pasted).decrypt(nonce, sealed, None) == data
