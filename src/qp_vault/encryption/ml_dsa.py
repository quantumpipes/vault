# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""ML-DSA-65 post-quantum signatures for provenance attestation.

Signs and verifies data using ML-DSA-65 (FIPS 204), providing
quantum-resistant digital signatures for provenance records,
Merkle proofs, and audit attestations.

Requires: pip install qp-vault[pq]
"""

from __future__ import annotations

try:
    import oqs
    HAS_OQS = True
except ImportError:
    HAS_OQS = False


class MLDSASigner:
    """ML-DSA-65 digital signature manager (FIPS 204).

    Generates keypairs, signs data, and verifies signatures.
    Used for provenance attestation and audit record signing.

    Usage:
        signer = MLDSASigner()
        pub, sec = signer.generate_keypair()
        signature = signer.sign(b"data", sec)
        assert signer.verify(b"data", signature, pub)
    """

    ALGORITHM = "ML-DSA-65"

    def __init__(self) -> None:
        if not HAS_OQS:
            raise ImportError(
                "liboqs-python is required for ML-DSA-65. "
                "Install with: pip install qp-vault[pq]"
            )

    def generate_keypair(self) -> tuple[bytes, bytes]:
        """Generate an ML-DSA-65 keypair.

        Returns:
            (public_key, secret_key) as bytes.
        """
        sig = oqs.Signature(self.ALGORITHM)
        public_key = sig.generate_keypair()
        secret_key = sig.export_secret_key()
        return public_key, secret_key

    def sign(self, message: bytes, secret_key: bytes) -> bytes:
        """Sign a message with ML-DSA-65.

        Args:
            message: The data to sign.
            secret_key: ML-DSA-65 secret key.

        Returns:
            The signature bytes.
        """
        sig = oqs.Signature(self.ALGORITHM, secret_key=secret_key)
        return sig.sign(message)

    def verify(self, message: bytes, signature: bytes, public_key: bytes) -> bool:
        """Verify an ML-DSA-65 signature.

        Args:
            message: The original signed data.
            signature: The signature to verify.
            public_key: ML-DSA-65 public key.

        Returns:
            True if signature is valid.
        """
        sig = oqs.Signature(self.ALGORITHM)
        return sig.verify(message, signature, public_key)
