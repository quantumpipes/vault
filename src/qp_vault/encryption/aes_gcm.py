# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""AES-256-GCM encryption for vault content.

Each encrypt call generates a unique nonce. Ciphertext format:
    nonce (12 bytes) || ciphertext || tag (16 bytes)

Requires: pip install qp-vault[encryption]
"""

from __future__ import annotations

import os

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


class AESGCMEncryptor:
    """AES-256-GCM symmetric encryption.

    Args:
        key: 32-byte encryption key. If None, generates a random key.

    Usage:
        enc = AESGCMEncryptor()
        ciphertext = enc.encrypt(b"secret data")
        plaintext = enc.decrypt(ciphertext)
    """

    def __init__(self, key: bytes | None = None) -> None:
        if not HAS_CRYPTO:
            raise ImportError(
                "cryptography is required for encryption. "
                "Install with: pip install qp-vault[encryption]"
            )
        if key is None:
            key = AESGCM.generate_key(bit_length=256)
        if len(key) != 32:
            raise ValueError("Key must be exactly 32 bytes (256 bits)")
        self._key = key
        self._aesgcm = AESGCM(key)

    @property
    def key(self) -> bytes:
        """The encryption key (32 bytes)."""
        return self._key

    def encrypt(self, plaintext: bytes, associated_data: bytes | None = None) -> bytes:
        """Encrypt data with AES-256-GCM.

        Args:
            plaintext: Data to encrypt.
            associated_data: Optional authenticated but unencrypted data.

        Returns:
            nonce (12 bytes) || ciphertext || tag (16 bytes)
        """
        nonce = os.urandom(12)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, associated_data)
        return nonce + ciphertext

    def decrypt(self, data: bytes, associated_data: bytes | None = None) -> bytes:
        """Decrypt AES-256-GCM encrypted data.

        Args:
            data: nonce (12 bytes) || ciphertext || tag (16 bytes)
            associated_data: Must match what was passed to encrypt().

        Returns:
            Decrypted plaintext.

        Raises:
            ValueError: If decryption fails (tampered data or wrong key).
        """
        if len(data) < 28:  # 12 nonce + 16 tag minimum
            raise ValueError("Encrypted data too short")
        nonce = data[:12]
        ciphertext = data[12:]
        try:
            return self._aesgcm.decrypt(nonce, ciphertext, associated_data)
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}") from e

    def encrypt_text(self, text: str, associated_data: bytes | None = None) -> bytes:
        """Convenience: encrypt a UTF-8 string."""
        return self.encrypt(text.encode("utf-8"), associated_data)

    def decrypt_text(self, data: bytes, associated_data: bytes | None = None) -> str:
        """Convenience: decrypt to a UTF-8 string."""
        return self.decrypt(data, associated_data).decode("utf-8")
