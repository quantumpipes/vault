# Encryption

qp-vault provides three tiers of encryption for data at rest.

## Tiers

| Tier | Algorithm | Standard | Install |
|------|-----------|----------|---------|
| **Classical** | AES-256-GCM | FIPS 197 | `pip install qp-vault[encryption]` |
| **Post-Quantum KEM** | ML-KEM-768 | FIPS 203 | `pip install qp-vault[pq]` |
| **Post-Quantum Signatures** | ML-DSA-65 | FIPS 204 | `pip install qp-vault[pq]` |
| **Hybrid** | ML-KEM-768 + AES-256-GCM | FIPS 203 + 197 | `pip install qp-vault[encryption,pq]` |

<!-- VERIFIED: encryption/__init__.py:7-13 — tier descriptions -->

## AES-256-GCM (Classical)

```python
from qp_vault.encryption import AESGCMEncryptor

enc = AESGCMEncryptor()           # Generates random 256-bit key
ciphertext = enc.encrypt(b"secret data")
plaintext = enc.decrypt(ciphertext)

# With associated data (authenticated but unencrypted)
ciphertext = enc.encrypt(b"secret", associated_data=b"resource-id")
plaintext = enc.decrypt(ciphertext, associated_data=b"resource-id")

# Text convenience methods
ciphertext = enc.encrypt_text("secret message")
text = enc.decrypt_text(ciphertext)
```

Each encrypt call generates a unique 12-byte nonce. Ciphertext format: `nonce (12 bytes) || ciphertext || tag (16 bytes)`.

<!-- VERIFIED: encryption/aes_gcm.py:59-73 — encrypt method with nonce generation -->

## ML-KEM-768 Key Encapsulation (Post-Quantum)

Wraps symmetric keys with quantum-resistant key encapsulation.

```python
from qp_vault.encryption import MLKEMKeyManager

km = MLKEMKeyManager()
public_key, secret_key = km.generate_keypair()

# Encapsulate: sender creates shared secret
ciphertext, shared_secret = km.encapsulate(public_key)
# shared_secret is 32 bytes, usable as AES-256-GCM key

# Decapsulate: receiver recovers shared secret
recovered = km.decapsulate(ciphertext, secret_key)
assert shared_secret == recovered
```

<!-- VERIFIED: encryption/ml_kem.py:40-81 — generate, encapsulate, decapsulate -->

## ML-DSA-65 Digital Signatures (Post-Quantum)

Quantum-resistant signatures for provenance attestation and audit records.

```python
from qp_vault.encryption import MLDSASigner

signer = MLDSASigner()
public_key, secret_key = signer.generate_keypair()

signature = signer.sign(b"provenance data", secret_key)
assert signer.verify(b"provenance data", signature, public_key)
```

<!-- VERIFIED: encryption/ml_dsa.py:40-80 — generate, sign, verify -->

## Hybrid Encryption (ML-KEM-768 + AES-256-GCM)

Combines post-quantum key encapsulation with classical symmetric encryption. The shared secret from ML-KEM-768 is used as the AES-256-GCM key.

```python
from qp_vault.encryption import HybridEncryptor

enc = HybridEncryptor()
public_key, secret_key = enc.generate_keypair()

ciphertext = enc.encrypt(b"classified data", public_key)
plaintext = enc.decrypt(ciphertext, secret_key)
```

Ciphertext format: `kem_ct_len (4 bytes) || kem_ciphertext || aes_nonce (12) || aes_ciphertext || aes_tag (16)`.

<!-- VERIFIED: encryption/hybrid.py:56-91 — encrypt/decrypt with format -->

## Key Zeroization

Securely erase key material from memory when no longer needed.

```python
from qp_vault.encryption.zeroize import zeroize

key = bytearray(32)
# ... use key ...
zeroize(key)  # Overwrites memory with zeros via ctypes memset
```

<!-- VERIFIED: encryption/zeroize.py:18-33 — zeroize function -->

## FIPS Known Answer Tests

Self-test cryptographic implementations against known vectors before use.

```python
from qp_vault.encryption.fips_kat import run_all_kat

results = run_all_kat()
# {"sha3_256": True, "aes_256_gcm": True}
```

Raises `FIPSKATError` if any test fails.

<!-- VERIFIED: encryption/fips_kat.py:56-66 — run_all_kat -->
