"""Tests for crypto_utils auto-start encryption."""

from qmt_gateway.core.crypto_utils import encrypt_for_auto_start, decrypt_for_auto_start


def test_encrypt_decrypt_auto_start_roundtrip():
    plaintext = "my-qmt-password"
    encrypted = encrypt_for_auto_start(plaintext)
    assert encrypted
    assert encrypted != plaintext

    decrypted = decrypt_for_auto_start(encrypted)
    assert decrypted == plaintext


def test_encrypt_for_auto_start_returns_empty_for_empty():
    assert encrypt_for_auto_start("") == ""
    assert encrypt_for_auto_start(None) == ""


def test_decrypt_for_auto_start_returns_empty_for_empty():
    assert decrypt_for_auto_start("") == ""
    assert decrypt_for_auto_start(None) == ""


def test_decrypt_for_auto_start_raises_on_corrupt_data():
    import pytest
    with pytest.raises(ValueError, match="auto-start 密码解密失败"):
        decrypt_for_auto_start("not-valid-base64-encrypted-data!!")


def test_different_plaintexts_produce_different_ciphertexts():
    e1 = encrypt_for_auto_start("password1")
    e2 = encrypt_for_auto_start("password2")
    assert e1 != e2


def test_same_plaintext_produces_different_ciphertexts():
    e1 = encrypt_for_auto_start("same-password")
    e2 = encrypt_for_auto_start("same-password")
    assert e1 != e2

    assert decrypt_for_auto_start(e1) == "same-password"
    assert decrypt_for_auto_start(e2) == "same-password"
