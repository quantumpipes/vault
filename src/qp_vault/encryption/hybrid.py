# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Hybrid encryption: ML-KEM-768 key exchange + AES-256-GCM data encryption.

Combines post-quantum key encapsulation (FIPS 203) with classical
symmetric encryption (FIPS 197) for defense-in-depth:

1. ML-KEM-768 encapsulates a shared secret (32 bytes)
2. Shared secret is used as AES-256-GCM key
3. Data is encrypted with AES-256-GCM

Format: kem_ciphertext_len (4 bytes) || kem_ciphertext || aes_nonce (12) || aes_ciphertext || aes_tag (16)

Requires: pip install qp-vault[pq,encryption]
"""

from __future__ import annotations

import struct

from qp_vault.encryption.aes_gcm import AESGCMEncryptor
from qp_vault.encryption.ml_kem import MLKEMKeyManager


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

        # Step 2: AES-256-GCM encrypt with the shared secret as key
        aes = AESGCMEncryptor(key=shared_secret[:32])
        aes_encrypted = aes.encrypt(plaintext)

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
        # Step 1: Unpack kem_ct_len
        if len(data) < 4:
            raise ValueError("Hybrid ciphertext too short")
        kem_ct_len = struct.unpack(">I", data[:4])[0]

        # Step 2: Extract KEM ciphertext and AES ciphertext
        kem_ciphertext = data[4 : 4 + kem_ct_len]
        aes_encrypted = data[4 + kem_ct_len :]

        # Step 3: ML-KEM-768 decapsulation -> shared secret
        shared_secret = self._kem.decapsulate(kem_ciphertext, secret_key)

        # Step 4: AES-256-GCM decrypt
        aes = AESGCMEncryptor(key=shared_secret[:32])
        return aes.decrypt(aes_encrypted)
