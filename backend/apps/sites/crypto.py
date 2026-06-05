"""Fernet encryption for WooCommerce ``consumer_secret``.

Secret is stored in the DB as ciphertext (``Site.consumer_secret_enc``) and only
decrypted in memory when building a ``WooClient``. The key comes from
``settings.FERNET_KEY`` — never committed, never logged.
"""

from cryptography.fernet import Fernet
from django.conf import settings

_key = settings.FERNET_KEY
_fernet = Fernet(_key.encode() if isinstance(_key, str) else _key)


def encrypt_secret(plaintext: str) -> bytes:
    return _fernet.encrypt(plaintext.encode())


def decrypt_secret(token: bytes) -> str:
    # BinaryField may return memoryview/bytes depending on backend.
    return _fernet.decrypt(bytes(token)).decode()
