"""Post-quantum cryptography tests. Requires liboqs-python (Docker or native).

Skipped automatically if liboqs is not installed.
"""

from __future__ import annotations

import pytest

try:
    import oqs  # noqa: F401
    HAS_OQS = True
except (ImportError, SystemExit):
    HAS_OQS = False

pytestmark = pytest.mark.skipif(not HAS_OQS, reason="liboqs not installed")


class TestMLKEM768:
    def test_generate_keypair(self) -> None:
        from qp_vault.encryption.ml_kem import MLKEMKeyManager

        km = MLKEMKeyManager()
        pub, sec = km.generate_keypair()
        assert len(pub) > 0
        assert len(sec) > 0

    def test_encapsulate_decapsulate_roundtrip(self) -> None:
        from qp_vault.encryption.ml_kem import MLKEMKeyManager

        km = MLKEMKeyManager()
        pub, sec = km.generate_keypair()
        ciphertext, shared_secret_enc = km.encapsulate(pub)
        shared_secret_dec = km.decapsulate(ciphertext, sec)
        assert shared_secret_enc == shared_secret_dec

    def test_tampered_ciphertext_fails(self) -> None:
        from qp_vault.encryption.ml_kem import MLKEMKeyManager

        km = MLKEMKeyManager()
        pub, sec = km.generate_keypair()
        ciphertext, shared_secret = km.encapsulate(pub)

        tampered = bytearray(ciphertext)
        tampered[0] ^= 0xFF
        bad_secret = km.decapsulate(bytes(tampered), sec)
        assert bad_secret != shared_secret


class TestMLDSA65:
    def test_generate_keypair(self) -> None:
        from qp_vault.encryption.ml_dsa import MLDSASigner

        signer = MLDSASigner()
        pub, sec = signer.generate_keypair()
        assert len(pub) > 0
        assert len(sec) > 0

    def test_sign_verify_roundtrip(self) -> None:
        from qp_vault.encryption.ml_dsa import MLDSASigner

        signer = MLDSASigner()
        pub, sec = signer.generate_keypair()
        message = b"Test message for ML-DSA-65"
        signature = signer.sign(message, sec)
        assert signer.verify(message, signature, pub) is True

    def test_tampered_message_fails(self) -> None:
        from qp_vault.encryption.ml_dsa import MLDSASigner

        signer = MLDSASigner()
        pub, sec = signer.generate_keypair()
        signature = signer.sign(b"Original message", sec)
        assert signer.verify(b"Tampered message", signature, pub) is False


class TestHybridEncryption:
    def test_encrypt_decrypt_roundtrip(self) -> None:
        from qp_vault.encryption.hybrid import HybridEncryptor

        enc = HybridEncryptor()
        pub, sec = enc.generate_keypair()
        plaintext = b"Top secret data for hybrid encryption test"
        ciphertext = enc.encrypt(plaintext, pub)
        decrypted = enc.decrypt(ciphertext, sec)
        assert decrypted == plaintext

    def test_different_keys_fail(self) -> None:
        from qp_vault.encryption.hybrid import HybridEncryptor

        enc = HybridEncryptor()
        pub1, _ = enc.generate_keypair()
        _, sec2 = enc.generate_keypair()
        ciphertext = enc.encrypt(b"secret", pub1)
        with pytest.raises((ValueError, RuntimeError)):
            enc.decrypt(ciphertext, sec2)


class TestFIPSKATWithOQS:
    def test_ml_kem_kat(self) -> None:
        from qp_vault.encryption.fips_kat import run_ml_kem_768_kat

        assert run_ml_kem_768_kat() is True

    def test_all_kat(self) -> None:
        from qp_vault.encryption.fips_kat import run_all_kat

        results = run_all_kat()
        assert results["sha3_256"] is True
        assert results["aes_256_gcm"] is True
        assert results["ml_kem_768"] is True
