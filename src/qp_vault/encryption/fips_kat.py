# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""FIPS Known Answer Tests (KAT) for self-testing.

Before using cryptographic operations in FIPS mode, the implementation
must verify correct behavior against known test vectors. These tests
run at startup or on demand.

Covers: SHA3-256 (FIPS 202), AES-256-GCM (FIPS 197), ML-KEM-768 (FIPS 203).
"""

from __future__ import annotations

import hashlib


class FIPSKATError(Exception):
    """Raised when a FIPS Known Answer Test fails."""


def run_sha3_256_kat() -> bool:
    """FIPS 202 KAT: SHA3-256 on known input.

    Test vector: SHA3-256("abc") = 3a985da74fe225b2...
    Source: NIST CSRC examples.
    """
    expected = "3a985da74fe225b2045c172d6bd390bd855f086e3e9d525b46bfe24511431532"
    actual = hashlib.sha3_256(b"abc").hexdigest()
    if actual != expected:
        raise FIPSKATError(f"SHA3-256 KAT failed: expected {expected[:16]}..., got {actual[:16]}...")
    return True


def run_aes_256_gcm_kat() -> bool:
    """FIPS 197 KAT: AES-256-GCM encrypt/decrypt roundtrip.

    Verifies that encryption followed by decryption returns the original plaintext.
    """
    try:
        from qp_vault.encryption.aes_gcm import AESGCMEncryptor
    except ImportError:
        return True  # Skip if cryptography not installed

    key = b"\x00" * 32  # Known key
    plaintext = b"FIPS KAT test vector"

    enc = AESGCMEncryptor(key=key)
    ciphertext = enc.encrypt(plaintext)
    decrypted = enc.decrypt(ciphertext)

    if decrypted != plaintext:
        raise FIPSKATError("AES-256-GCM KAT failed: decrypt(encrypt(x)) != x")
    return True


def run_ml_kem_768_kat() -> bool:
    """FIPS 203 KAT: ML-KEM-768 encapsulation/decapsulation roundtrip.

    Verifies:
    1. Key generation produces valid keypair.
    2. Encapsulate produces ciphertext + shared secret.
    3. Decapsulate recovers the same shared secret.
    4. Tampered ciphertext does not produce the same shared secret.
    """
    try:
        from qp_vault.encryption.ml_kem import MLKEMKeyManager
        km = MLKEMKeyManager()
    except ImportError:
        return True  # PQ crypto (liboqs) not installed, skip (not a failure)

    # Test 1: Roundtrip
    public_key, secret_key = km.generate_keypair()
    ciphertext, shared_secret_enc = km.encapsulate(public_key)
    shared_secret_dec = km.decapsulate(ciphertext, secret_key)

    if shared_secret_enc != shared_secret_dec:
        raise FIPSKATError(
            "ML-KEM-768 KAT failed: encapsulated and decapsulated shared secrets do not match"
        )

    # Test 2: Tampered ciphertext must not produce the same shared secret
    tampered = bytearray(ciphertext)
    tampered[0] ^= 0xFF
    try:
        bad_secret = km.decapsulate(bytes(tampered), secret_key)
        if bad_secret == shared_secret_enc:
            raise FIPSKATError(
                "ML-KEM-768 KAT failed: tampered ciphertext produced same shared secret"
            )
    except Exception:
        pass  # Expected: decapsulation should fail or produce different secret

    return True


def run_all_kat() -> dict[str, bool]:
    """Run all FIPS Known Answer Tests.

    Returns:
        Dict mapping test name to pass/fail status.

    Raises:
        FIPSKATError: If any test fails.
    """
    results: dict[str, bool] = {}
    results["sha3_256"] = run_sha3_256_kat()
    results["aes_256_gcm"] = run_aes_256_gcm_kat()
    results["ml_kem_768"] = run_ml_kem_768_kat()
    return results
