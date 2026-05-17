# Capsule Chain Anchors

> Phase 3 forward-looking: how source documents in a qp-vault namespace anchor to the capsule chain for tamper-evident audit trails, post-quantum signatures, and IP attribution. Complements [Source Document Frontmatter](source-document-frontmatter.md) §Phase 3 fields.

> **Status**: experimental. The pattern is designed; the integration ships at portfolio scale when the capsule chain substrate completes. Use the Phase 2 schema for production today; expect Phase 3 fields to land automatically when integration is live.

## What this is

The capsule chain is the cryptographic audit substrate across the Synova portfolio. Every significant operation produces a capsule: an immutable record with classical and post-quantum signatures, hash-linked to the prior capsule in its chain, retention-layered for privacy.

This document describes how source documents in a vault namespace anchor to capsule chains. The result: every canonical document has a forensic provenance from creation through revision through eventual archival, verifiable independently of the vault itself.

## Why anchoring matters

A knowledge base without anchoring can be modified without trace. A regulator, an auditor, or an IP licensee evaluating the base has to trust the operator's word about content provenance. With capsule chain anchoring, modification is detectable and provenance is verifiable.

This shifts the trust posture from "trust the operator" to "verify the chain." For properties operating in regulated industries (HCBS, healthcare, finance), the shift is the difference between operational claims and structural evidence.

## The anchoring pattern

Every canonical-tier document carries Phase 3 frontmatter fields linking it to its capsule:

```yaml
capsule_id: "uuid-of-the-capsule-sealing-this-document-version"
capsule_chain_index: 42
capsule_prev_id: "uuid-of-the-previous-capsule"
capsule_hash: "sha3-256-of-the-capsule-content"
signature_ed25519: "base64-classical-signature"
signature_mldsa65: "base64-post-quantum-signature"
```

When a document is created:

1. The document content (frontmatter plus body) is hashed
2. A capsule is created with the hash, the prior capsule's ID, and the property's signing keys
3. The capsule is appended to the chain
4. The document's frontmatter is updated with the capsule's identifier, index, and hash

When a document is revised:

1. The revised content is hashed
2. A new capsule is created
3. The new capsule's `supersedes` field references the prior capsule
4. The document's frontmatter updates to the new capsule's identifier
5. The prior document version is preserved (per [Lifecycle](lifecycle.md) supersedes-discipline) with its old capsule reference intact

## The three retention layers

Capsules use a three-layer retention model:

| Layer | Retention | Content | Visible after expiration |
|---|---|---|---|
| Layer 1 | Permanent | Capsule ID, type, outcome, authority | Yes |
| Layer 2 | 90 days | Anonymized reasoning, redacted tool calls | No |
| Layer 3 | 7 days | Full context, encrypted with AES-256-GCM | No |

For source documents:

- Layer 1 (permanent): `{document_slug, version, hash, signatures, chain_pointer}`. Always retained. Forensically queryable forever.
- Layer 2 (90 days): the revision context (who edited, what changed, why). Retained for 90 days then purged.
- Layer 3 (7 days): the full pre-revision content cached for short-window rollback. Purged at 7 days.

For privacy compliance, the three-layer model means a document revision is fully visible for 7 days, summary-visible for 90 days, and minimally-traceable forever.

## Signature scheme

Each capsule is signed with two algorithms:

- **Ed25519**: classical elliptic-curve signature. Compact, fast, well-tested.
- **ML-DSA-65**: post-quantum signature (NIST standardized FIPS 204). Survives a future cryptographically-relevant quantum computer.

Both signatures are required. A verifier checks both. If either fails, the capsule is invalid.

The hybrid scheme means the capsule is secure under classical assumptions today and post-quantum assumptions for the foreseeable future. Migration to a pure post-quantum scheme can happen when the classical signature becomes redundant.

See [Security](security.md) for the algorithm specifications.

## Chain integrity

The chain hash field is the operative integrity check:

```
capsule_hash = SHA3-256(
    capsule_content
    || layer_1_data
    || layer_2_data (if not yet purged)
    || layer_3_encrypted (if not yet purged)
    || prev_capsule_hash
)
```

Tampering with any layer changes the hash. Tampering with the chain's prior link changes downstream hashes. The chain is forensically self-verifying.

A nightly integrity verification cron walks every chain in every namespace and confirms:

- Each capsule's stored hash matches the recomputed hash
- Each capsule's prev_id points to a real capsule
- Each capsule's signatures verify

Any failure produces a critical alert. The chain is the audit-trail moat; corruption is non-degradable.

## How to query the chain

qp-vault exposes capsule chain queries:

```python
from qp_vault import Vault

vault = Vault("./namespace")

# Get the capsule chain for a specific document
chain = vault.get_capsule_chain(slug="policy-5700-medication-management")
for capsule in chain:
    print(f"{capsule.chain_index}: {capsule.created_at} {capsule.outcome.summary}")

# Verify a specific capsule
capsule = vault.get_capsule(capsule_id="...")
assert capsule.verify_signatures()
assert capsule.verify_chain_link()

# Export a chain for external verification
exported = vault.export_chain(slug="...", format="json-with-signatures")
```

External tools (auditor's verifier, regulator's check) can verify exported chains without access to the vault internals; signatures and hash links are mechanically verifiable.

## IP attribution capsules

Phase 3 introduces specialized capsules for IP attribution:

```yaml
# In a source document's frontmatter
ip_owner: ["RHE", "Compliance Director"]
ip_license: "internal-with-attribution-required"
ip_attribution_required: true

# The corresponding IP attribution capsule (in the chain) records:
# - The IP holders at time of capsule creation
# - The license terms
# - Any signed agreements (linked from the capsule)
# - The chain history of ownership transfers
```

For source documents derived from third-party IP (e.g., an externally authored Policy Book the property licenses), the IP attribution capsule is the operative legal evidence: it records when the license was granted, by whom, under what terms, and links the chain of revisions back to the original IP holder.

This becomes useful in three scenarios:

1. IP licensing conversations (the chain is the evidence of license compliance)
2. IP disputes (the chain is the evidence of ownership history)
3. Acquisitions or restructurings (the chain transfers cleanly with the IP)

## Verification capsules

Phase 3 introduces verification capsules for externally validated claims:

```yaml
# In a source document making an external claim
verification_capsule_id: "uuid-of-the-verification-capsule"
```

The verification capsule records:

- The external authority verifying the claim
- The verification method (audit, regulatory check, peer review)
- The verification timestamp
- The signed attestation from the external authority

Example use: a property's published metric (e.g., the operating-income benchmark) is verified by an external auditor. The auditor signs an attestation. The signed attestation becomes a capsule. The source document references the capsule.

A reader can then trace the claim from the document to the verification capsule to the external authority's signature.

## Migration from Phase 2 to Phase 3

When capsule chain integration ships at portfolio scale, the migration is automatic for documents already in Phase 2:

1. The migration script reads every document in the namespace
2. For each, the script creates a capsule with the document's current content hash
3. The capsule chain is initialized in source-document order (or by `last_reviewed` date)
4. The Phase 3 frontmatter fields populate
5. Subsequent revisions extend the chain naturally

For new documents created after integration ships, the chain starts at creation; no migration step needed.

## Air-gap compatibility

Capsule chain integration must work in air-gapped deployments per the portfolio architectural rule. The pattern:

- Signing keys are locally held (HSM or local key store; not cloud-dependent)
- Hash computation is local (SHA3-256, no external dependencies)
- Chain storage is local (PostgreSQL or other local DB)
- Verification is local

Cloud-deployed properties can optionally export chain snapshots to public anchor services (blockchain anchoring, certificate transparency-style logs) for additional external attestation. Air-gapped deployments skip this step; the chain is still cryptographically valid without external anchoring.

## Performance considerations

Capsule creation is non-trivial:

- Hashing the document content
- Generating two signatures (Ed25519 plus ML-DSA-65)
- Writing the capsule to storage

Typical capsule-creation latency: under 100ms in optimized implementations. For high-throughput document operations, batch capsule creation and asynchronous chain extension are recommended; the chain is still cryptographically valid because each capsule references its predecessor regardless of creation ordering.

The cost is acceptable for canonical-tier content (revisions are infrequent). For working-tier and ephemeral content, capsule creation can be deferred or skipped per the property's policy.

## What this enables in practice

For a property that ships Phase 3 capsule chain integration:

- **External audit**: a regulator can verify the property's claims by walking the chain and checking signatures. No trust of the operator required.
- **IP licensing**: an IP licensee receives a chain export with the document history. The terms and provenance are verifiable.
- **Acquisition due diligence**: an acquirer examines the operational substrate's chain history. The seven-year operating record becomes structurally verifiable, not just operator-asserted.
- **Compliance attestation**: an annual compliance report (e.g., 80/20 rule attestation in HCBS) is a derived view of the chain, not a separately authored document.
- **Time-travel queries**: an AI agent or human can ask "what did this document say on 2024-03-15" and get a verifiable answer from the chain.

These are not features of qp-vault; they are emergent properties of the capsule chain anchoring.

## Status and adoption

Phase 3 is experimental:

- The schema is defined
- The signature scheme is selected
- The retention model is documented
- Integration with qp-vault is designed
- Production deployment ships when the broader capsule chain substrate completes

Properties adopting Phase 3 today should expect:

- Schema is stable
- Implementation may iterate
- Migration from any iteration to v1.0 will be automatic (per the schema's forward-compatibility promise)

Properties adopting Phase 2 today are not blocked by Phase 3's experimental status. The Phase 2 schema is canonical and production-ready. Phase 3 layers on without disrupting Phase 2.

## Anti-patterns

### Anti-pattern 1: Treating capsule chain as a backup

The chain is for forensic integrity, not for content recovery. Layer 3 retention is only 7 days; do not depend on the chain to recover content older than that. Use separate backup mechanisms for content recovery.

### Anti-pattern 2: Skipping signatures

The two-signature scheme is mandatory for canonical-tier content. Skipping the post-quantum signature creates a forward-security gap that may matter in 10 to 30 years.

### Anti-pattern 3: Modifying capsules after creation

Capsules are immutable. Modification breaks the chain. If a document needs revision, create a new capsule and supersede the old one; do not modify the old capsule.

### Anti-pattern 4: Hardcoding chain IDs in body content

Capsule IDs go in frontmatter, not in document body content. Body content references documents by slug (relative-path link); the slug resolves through the vault to the current canonical version's capsule.

## Related references

- [Source Document Frontmatter](source-document-frontmatter.md): the Phase 2 schema this Phase 3 model extends
- [Trust Tiers](trust-tiers.md): the vault-internal trust weighting
- [Lifecycle](lifecycle.md): the state machine including supersedes-discipline
- [Security](security.md): the algorithm specifications for signatures and hashing
- [Encryption](encryption.md): the Layer 3 encryption scheme
- [Diátaxis Organization](diataxis-organization.md): the folder structure under which capsule-anchored documents live
