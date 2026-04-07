# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Encryption at rest for qp-vault.

Classical: AES-256-GCM (FIPS 197)
Post-quantum: ML-KEM-768 key encapsulation (FIPS 203) + ML-DSA-65 signatures (FIPS 204)
Hybrid: ML-KEM-768 + AES-256-GCM (quantum-resistant data encryption)

Install:
    pip install qp-vault[encryption]     # AES-256-GCM only
    pip install qp-vault[pq]             # + ML-KEM-768 + ML-DSA-65
    pip install qp-vault[encryption,pq]  # Full hybrid encryption
"""

from qp_vault.encryption.aes_gcm import AESGCMEncryptor

__all__ = ["AESGCMEncryptor"]

# Conditional PQ exports (available when liboqs-python installed)
try:
    from qp_vault.encryption.hybrid import HybridEncryptor
    from qp_vault.encryption.ml_dsa import MLDSASigner
    from qp_vault.encryption.ml_kem import MLKEMKeyManager

    __all__ += ["MLKEMKeyManager", "MLDSASigner", "HybridEncryptor"]
except ImportError:
    pass
