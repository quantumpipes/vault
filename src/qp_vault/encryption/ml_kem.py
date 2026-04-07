# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""ML-KEM-768 key encapsulation for post-quantum key exchange.

Wraps AES-256-GCM data encryption keys (DEK) with ML-KEM-768 (FIPS 203).
The encapsulated key can only be decapsulated by the holder of the
ML-KEM-768 secret key, providing quantum-resistant key protection.

Requires: pip install qp-vault[pq]
"""

from __future__ import annotations

try:
    import oqs
    HAS_OQS = True
except ImportError:
    HAS_OQS = False


class MLKEMKeyManager:
    """ML-KEM-768 key encapsulation manager (FIPS 203).

    Generates keypairs, encapsulates shared secrets, and decapsulates
    them. Used to wrap AES-256-GCM keys for post-quantum protection.

    Usage:
        km = MLKEMKeyManager()
        pub, sec = km.generate_keypair()
        ciphertext, shared_secret = km.encapsulate(pub)
        recovered = km.decapsulate(ciphertext, sec)
        assert shared_secret == recovered
    """

    ALGORITHM = "ML-KEM-768"

    def __init__(self) -> None:
        if not HAS_OQS:
            raise ImportError(
                "liboqs-python is required for ML-KEM-768. "
                "Install with: pip install qp-vault[pq]"
            )

    def generate_keypair(self) -> tuple[bytes, bytes]:
        """Generate an ML-KEM-768 keypair.

        Returns:
            (public_key, secret_key) as bytes.
        """
        kem = oqs.KeyEncapsulation(self.ALGORITHM)
        public_key = kem.generate_keypair()
        secret_key = kem.export_secret_key()
        return public_key, secret_key

    def encapsulate(self, public_key: bytes) -> tuple[bytes, bytes]:
        """Encapsulate a shared secret using a public key.

        Args:
            public_key: ML-KEM-768 public key.

        Returns:
            (ciphertext, shared_secret) — ciphertext is sent to key holder,
            shared_secret is used as AES-256-GCM key.
        """
        kem = oqs.KeyEncapsulation(self.ALGORITHM)
        ciphertext, shared_secret = kem.encap_secret(public_key)
        return ciphertext, shared_secret

    def decapsulate(self, ciphertext: bytes, secret_key: bytes) -> bytes:
        """Decapsulate a shared secret using the secret key.

        Args:
            ciphertext: The encapsulated ciphertext from encapsulate().
            secret_key: ML-KEM-768 secret key.

        Returns:
            The shared secret (same as returned by encapsulate).
        """
        kem = oqs.KeyEncapsulation(self.ALGORITHM, secret_key=secret_key)
        return kem.decap_secret(ciphertext)  # type: ignore[no-any-return]
