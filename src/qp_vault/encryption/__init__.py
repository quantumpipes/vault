# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Encryption at rest for qp-vault.

Provides AES-256-GCM symmetric encryption for chunk content.
Requires: pip install qp-vault[encryption]
"""

from qp_vault.encryption.aes_gcm import AESGCMEncryptor

__all__ = ["AESGCMEncryptor"]
