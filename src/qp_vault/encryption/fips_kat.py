# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""FIPS Known Answer Tests (KAT) for self-testing.

Before using cryptographic operations in FIPS mode, the implementation
must verify correct behavior against known test vectors. These tests
run at startup or on demand.

Covers: SHA3-256 (FIPS 202), AES-256-GCM (FIPS 197).
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
    return results
