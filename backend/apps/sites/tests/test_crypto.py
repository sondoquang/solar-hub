from apps.sites.crypto import decrypt_secret, encrypt_secret


def test_encrypt_decrypt_round_trip():
    token = encrypt_secret("super-secret")
    assert token != b"super-secret"
    assert decrypt_secret(token) == "super-secret"


def test_ciphertext_differs_each_time():
    # Fernet embeds a random IV, so two encryptions differ but both decrypt back.
    a = encrypt_secret("x")
    b = encrypt_secret("x")
    assert a != b
    assert decrypt_secret(a) == decrypt_secret(b) == "x"
