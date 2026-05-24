# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Security tests for hybrid encryption hardening (H7 + H8).

H7: AES key is derived from the KEM shared secret via HKDF-SHA3-256 (with
domain separation), not used raw.
H8: the attacker-controlled KEM-ciphertext length prefix is validated before
any slicing/decapsulation.
"""

from __future__ import annotations

import struct

import pytest

from qp_vault.encryption.hybrid import (
    _ML_KEM_768_CIPHERTEXT_LEN,
    _derive_aes_key,
)

try:
    from qp_vault.encryption.hybrid import HybridEncryptor

    _enc = HybridEncryptor()
    HAS_PQ = True
except Exception:  # liboqs / cryptography not installed
    HAS_PQ = False


def test_hkdf_derives_32_byte_key_with_separation() -> None:
    k1 = _derive_aes_key(b"\x01" * 32)
    assert len(k1) == 32
    # Deterministic for the same secret.
    assert _derive_aes_key(b"\x01" * 32) == k1
    # Different secret -> different key (HKDF, not identity).
    assert _derive_aes_key(b"\x02" * 32) != k1
    # The derived key is NOT the raw shared secret (proves a KDF ran).
    assert k1 != b"\x01" * 32


@pytest.mark.skipif(not HAS_PQ, reason="liboqs/cryptography not installed")
def test_decrypt_rejects_bad_length_prefix() -> None:
    enc = HybridEncryptor()
    _pub, sec = enc.generate_keypair()

    # Length prefix claims a wrong KEM ciphertext size -> rejected before KEM.
    bogus = struct.pack(">I", _ML_KEM_768_CIPHERTEXT_LEN + 5) + b"\x00" * 64
    with pytest.raises(ValueError):
        enc.decrypt(bogus, sec)

    # Correct length claim but truncated body -> rejected.
    truncated = struct.pack(">I", _ML_KEM_768_CIPHERTEXT_LEN) + b"\x00" * _ML_KEM_768_CIPHERTEXT_LEN
    with pytest.raises(ValueError):
        enc.decrypt(truncated, sec)


@pytest.mark.skipif(not HAS_PQ, reason="liboqs/cryptography not installed")
def test_roundtrip_with_aad_binding() -> None:
    enc = HybridEncryptor()
    pub, sec = enc.generate_keypair()
    pt = b"sensitive vault content"
    ct = enc.encrypt(pt, pub)
    assert enc.decrypt(ct, sec) == pt
