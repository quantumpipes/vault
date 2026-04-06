# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.5.x   | Yes                |
| < 0.5   | No                 |

## Reporting a Vulnerability

If you discover a security vulnerability in qp-vault, please report it responsibly.

**Do NOT open a public issue.**

Instead, email: security@quantumpipes.io

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge your report within 48 hours and provide a timeline for a fix.

## Security Design

qp-vault is designed with security as a foundation:

- **SHA3-256** for all content hashing (FIPS 202)
- **No deprecated crypto**: MD5, SHA1, DES, 3DES, RC4, RSA are never used
- **Parameterized SQL**: all queries use placeholders, never string interpolation
- **Input validation**: enum values, resource names, tags, metadata validated at boundary
- **Path traversal protection**: names sanitized, null bytes stripped
- **FTS5 injection prevention**: query sanitizer strips special operators
- **Post-quantum ready**: AES-256-GCM + ML-KEM-768 encryption (optional)
- **Capsule audit trail**: cryptographically sealed, hash-chained records (optional)
