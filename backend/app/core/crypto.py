"""Encryption at rest for stored files (plans, page thumbnails, evaluation copies).

AES-256-GCM with a key from FILE_ENCRYPTION_KEY (32 random bytes, base64). Each file gets its own
random nonce; the GCM tag detects tampering. Stored layout: MAGIC + nonce (12) + ciphertext+tag.
Files stored before encryption was turned on have no MAGIC and are read as they are, so turning
it on needs no downtime (`python -m app.maintenance encrypt-files` converts the old ones).

Generate a key with:
    python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
"""

import base64
import binascii
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

MAGIC = b"FPE1"  # Floor Planner Encrypted, format 1
_NONCE = 12
_AAD = b"floor-planner/file/v1"


class EncryptionError(Exception):
    pass


def _normalize(key_b64: str) -> str:
    """Forgive the usual copy-paste slips in a host's settings form: surrounding quotes or
    spaces, and a dropped "=" at the end."""
    key = key_b64.strip().strip("\"'").strip()
    return key + "=" * (-len(key) % 4)


@lru_cache
def _cipher(key_b64: str) -> AESGCM:
    try:
        key = base64.b64decode(_normalize(key_b64), validate=True)
    except (binascii.Error, ValueError):
        raise EncryptionError("FILE_ENCRYPTION_KEY isn't valid base64.") from None
    if len(key) != 32:
        raise EncryptionError("FILE_ENCRYPTION_KEY must be 32 bytes (44 base64 characters).")
    return AESGCM(key)


def enabled() -> bool:
    return bool(get_settings().file_encryption_key)


def check_key() -> None:
    """Fail at startup, not on the first upload, if a key is set but unusable."""
    key = get_settings().file_encryption_key
    if key:
        _cipher(key)


def is_encrypted(blob: bytes) -> bool:
    return blob[: len(MAGIC)] == MAGIC


def encrypt(data: bytes) -> bytes:
    key = get_settings().file_encryption_key
    if not key:
        return data
    nonce = os.urandom(_NONCE)
    return MAGIC + nonce + _cipher(key).encrypt(nonce, data, _AAD)


def decrypt(blob: bytes) -> bytes:
    if not is_encrypted(blob):
        return blob  # stored before encryption was turned on
    key = get_settings().file_encryption_key
    if not key:
        raise EncryptionError("This file is encrypted but FILE_ENCRYPTION_KEY isn't set.")
    nonce = blob[len(MAGIC) : len(MAGIC) + _NONCE]
    try:
        return _cipher(key).decrypt(nonce, blob[len(MAGIC) + _NONCE :], _AAD)
    except InvalidTag:
        raise EncryptionError(
            "This file couldn't be decrypted: the key is wrong or the file was changed."
        ) from None
