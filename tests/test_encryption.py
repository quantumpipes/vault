"""Tests for AES-256-GCM encryption module."""

from __future__ import annotations

import pytest

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401

    from qp_vault.encryption.aes_gcm import AESGCMEncryptor
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

pytestmark = pytest.mark.skipif(not HAS_CRYPTO, reason="cryptography not installed")


class TestAESGCMEncryptor:
    def test_encrypt_decrypt_roundtrip(self):
        enc = AESGCMEncryptor()
        plaintext = b"Hello, World!"
        ciphertext = enc.encrypt(plaintext)
        assert ciphertext != plaintext
        decrypted = enc.decrypt(ciphertext)
        assert decrypted == plaintext

    def test_encrypt_text_roundtrip(self):
        enc = AESGCMEncryptor()
        text = "Secret message"
        ciphertext = enc.encrypt_text(text)
        assert enc.decrypt_text(ciphertext) == text

    def test_different_nonce_each_time(self):
        enc = AESGCMEncryptor()
        c1 = enc.encrypt(b"same data")
        c2 = enc.encrypt(b"same data")
        assert c1 != c2  # Different nonces

    def test_wrong_key_fails(self):
        enc1 = AESGCMEncryptor()
        enc2 = AESGCMEncryptor()  # Different random key
        ciphertext = enc1.encrypt(b"secret")
        with pytest.raises(ValueError, match="Decryption failed"):
            enc2.decrypt(ciphertext)

    def test_tampered_data_fails(self):
        enc = AESGCMEncryptor()
        ciphertext = enc.encrypt(b"secret")
        tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 0xFF])
        with pytest.raises(ValueError):
            enc.decrypt(tampered)

    def test_too_short_data_fails(self):
        enc = AESGCMEncryptor()
        with pytest.raises(ValueError, match="too short"):
            enc.decrypt(b"short")

    def test_custom_key(self):
        key = b"\x00" * 32
        enc = AESGCMEncryptor(key=key)
        assert enc.key == key
        ciphertext = enc.encrypt(b"test")
        assert enc.decrypt(ciphertext) == b"test"

    def test_invalid_key_length(self):
        with pytest.raises(ValueError, match="32 bytes"):
            AESGCMEncryptor(key=b"short")

    def test_associated_data(self):
        enc = AESGCMEncryptor()
        ad = b"metadata"
        ciphertext = enc.encrypt(b"secret", associated_data=ad)
        assert enc.decrypt(ciphertext, associated_data=ad) == b"secret"

    def test_wrong_associated_data_fails(self):
        enc = AESGCMEncryptor()
        ciphertext = enc.encrypt(b"secret", associated_data=b"correct")
        with pytest.raises(ValueError):
            enc.decrypt(ciphertext, associated_data=b"wrong")

    def test_empty_plaintext(self):
        enc = AESGCMEncryptor()
        ciphertext = enc.encrypt(b"")
        assert enc.decrypt(ciphertext) == b""
