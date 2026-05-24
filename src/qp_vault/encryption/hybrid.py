# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Hybrid encryption: ML-KEM-768 key exchange + AES-256-GCM data encryption.

Combines post-quantum key encapsulation (FIPS 203) with classical
symmetric encryption (FIPS 197) for defense-in-depth:

1. ML-KEM-768 encapsulates a shared secret (32 bytes)
2. The shared secret is run through HKDF-SHA3-256 to derive the AES-256-GCM key
3. Data is encrypted with AES-256-GCM, with the KEM ciphertext bound as AAD

Format: kem_ciphertext_len (4 bytes) || kem_ciphertext || aes_nonce (12) || aes_ciphertext || aes_tag (16)

Requires: pip install qp-vault[pq,encryption]
"""

from __future__ import annotations

import hashlib
import hmac
import struct

from qp_vault.encryption.aes_gcm import AESGCMEncryptor
from qp_vault.encryption.ml_kem import MLKEMKeyManager

# ML-KEM-768 ciphertext is exactly 1088 bytes (FIPS 203). Enforced on decrypt
# so a malformed/oversized length prefix cannot drive slicing.
_ML_KEM_768_CIPHERTEXT_LEN = 1088

# AES-256-GCM overhead: 12-byte nonce + 16-byte tag.
_AES_GCM_OVERHEAD = 12 + 16

# Domain-separation label for the HKDF key derivation and the AES-GCM AAD.
_KDF_INFO = b"qp-vault/hybrid/ml-kem-768+aes-256-gcm/v1"
_AAD_CONTEXT = b"qp-vault/hybrid/v1"


def _derive_aes_key(shared_secret: bytes) -> bytes:
    """Derive a 32-byte AES-256 key from the KEM shared secret via HKDF-SHA3-256.

    Using HKDF (extract + expand) with a fixed ``info`` label adds domain
    separation and context binding rather than using the raw KEM secret as the
    key directly. Implemented with stdlib HMAC-SHA3-256 (no extra dependency).
    """
    # Extract: salt of zeros (the KEM secret is already a uniform 32 bytes).
    prk = hmac.new(b"\x00" * 32, shared_secret, hashlib.sha3_256).digest()
    # Expand: a single 32-byte block (T(1) = HMAC(PRK, info || 0x01)).
    okm = hmac.new(prk, _KDF_INFO + b"\x01", hashlib.sha3_256).digest()
    return okm[:32]


class HybridEncryptor:
    """ML-KEM-768 + AES-256-GCM hybrid encryption.

    Provides quantum-resistant data encryption by wrapping AES keys
    with ML-KEM-768 key encapsulation.

    Usage:
        enc = HybridEncryptor()
        pub, sec = enc.generate_keypair()
        ciphertext = enc.encrypt(b"secret data", pub)
        plaintext = enc.decrypt(ciphertext, sec)
    """

    def __init__(self) -> None:
        self._kem = MLKEMKeyManager()

    def generate_keypair(self) -> tuple[bytes, bytes]:
        """Generate an ML-KEM-768 keypair for hybrid encryption.

        Returns:
            (public_key, secret_key) — store secret_key securely.
        """
        return self._kem.generate_keypair()

    def encrypt(self, plaintext: bytes, public_key: bytes) -> bytes:
        """Encrypt data with hybrid ML-KEM-768 + AES-256-GCM.

        Args:
            plaintext: Data to encrypt.
            public_key: ML-KEM-768 public key.

        Returns:
            Hybrid ciphertext: kem_ct_len(4) || kem_ct || aes_encrypted
        """
        # Step 1: ML-KEM-768 key encapsulation -> shared secret (32 bytes)
        kem_ciphertext, shared_secret = self._kem.encapsulate(public_key)

        # Step 2: Derive the AES key via HKDF-SHA3-256 (not the raw KEM secret),
        # and bind the KEM ciphertext into the AES-GCM AAD so the two halves of
        # the message cannot be mixed/substituted.
        aes = AESGCMEncryptor(key=_derive_aes_key(shared_secret))
        aad = _AAD_CONTEXT + kem_ciphertext
        aes_encrypted = aes.encrypt(plaintext, associated_data=aad)

        # Step 3: Pack: kem_ct_len || kem_ct || aes_encrypted
        return struct.pack(">I", len(kem_ciphertext)) + kem_ciphertext + aes_encrypted

    def decrypt(self, data: bytes, secret_key: bytes) -> bytes:
        """Decrypt hybrid ML-KEM-768 + AES-256-GCM ciphertext.

        Args:
            data: Hybrid ciphertext from encrypt().
            secret_key: ML-KEM-768 secret key.

        Returns:
            Decrypted plaintext.
        """
        # Step 1: Unpack kem_ct_len and validate it before any slicing.
        if len(data) < 4:
            raise ValueError("Hybrid ciphertext too short")
        kem_ct_len = struct.unpack(">I", data[:4])[0]

        # H8: the length prefix is attacker-controlled; never trust it. Require
        # the exact ML-KEM-768 ciphertext size and that the full record (KEM
        # ciphertext + AES nonce/tag + at least empty body) fits in the buffer.
        if kem_ct_len != _ML_KEM_768_CIPHERTEXT_LEN:
            raise ValueError("Invalid KEM ciphertext length")
        if len(data) < 4 + kem_ct_len + _AES_GCM_OVERHEAD:
            raise ValueError("Hybrid ciphertext truncated")

        # Step 2: Extract KEM ciphertext and AES ciphertext
        kem_ciphertext = data[4 : 4 + kem_ct_len]
        aes_encrypted = data[4 + kem_ct_len :]

        # Step 3: ML-KEM-768 decapsulation -> shared secret
        shared_secret = self._kem.decapsulate(kem_ciphertext, secret_key)

        # Step 4: Derive the AES key the same way as encrypt and verify the AAD
        # binding to the KEM ciphertext (GCM auth fails on any mismatch).
        aes = AESGCMEncryptor(key=_derive_aes_key(shared_secret))
        aad = _AAD_CONTEXT + kem_ciphertext
        return aes.decrypt(aes_encrypted, associated_data=aad)
