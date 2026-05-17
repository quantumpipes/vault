# Source Document Frontmatter

> The recommended frontmatter schema for markdown source documents that live inside a qp-vault namespace. Complements [Trust Tiers](trust-tiers.md) and [Lifecycle](lifecycle.md), which are vault-internal concerns; this document is about what should appear at the top of every source file you feed into qp-vault.

## Why frontmatter

A vault with hundreds of source documents needs metadata for the same reason a library needs a card catalog: so any consumer (a human, a search index, an AI agent) can find what they need without reading every file. With consistent metadata, queries are fast and trustworthy. Without it, queries are slow and lossy.

The single most important rule: every file uses the same field names. Inconsistent fields break filtering. If half the files say `author` and half say `authored_by`, queries miss half the results.

## Two phases

The schema has two phases:

- **Phase 2 (current)**: 14 fields that make a document navigable, filterable, AI-readable, and ownership-clear. Recommended for every source document going into qp-vault today.
- **Phase 3 (forward-looking)**: 14 additional fields that activate when the capsule chain integration ships at portfolio scale. Capsule audit references, post-quantum signatures, IP licensing details, verification capsule IDs.

Phase 3 fields are derivable from Phase 2 plus the capsule chain ledger. No file in this base needs hand-editing to migrate; a future migration script can append Phase 3 fields automatically.

This document covers both phases. Apply Phase 2 today; expect Phase 3 to land automatically.

## The Phase 2 schema (14 fields)

Every source document carries these 14 fields at the top, between two lines of three dashes. The block is YAML.

```yaml
---
title: "The full title of this document, in title case"
slug: "kebab-case-deterministic-slug"
description: "One sentence that explains what this is and why it exists."

diataxis: "tutorial | how-to | reference | explanation"

trust_tier: "canonical | working | ephemeral | archived"
lifecycle: "draft | review | active | superseded | archived"
last_reviewed: "YYYY-MM-DD"

data_classification: "public | internal"

author: ["Role Name"]
source_artifact: "What this content was derived from, if anything"

related:
  - "./relative/path/to/file.md"
entities: ["Role Names", "Organization Names", "Concepts"]
tags: ["lowercase-kebab-case-keywords"]

ai_context: |
  A multi-line note for AI tools consuming this document.
  What audience to consider, what to cite, what to flag.
---
```

### Identity fields (3)

- **title**: full document title, title case. Shown as the H1 if rendered.
- **slug**: kebab-case identifier, deterministic from the title. Should match the filename minus extension.
- **description**: a single sentence explaining what this document is. Used in search results, link previews, AI surfacing.

### Diátaxis field (1)

- **diataxis**: one of `tutorial`, `how-to`, `reference`, or `explanation`. The folder location should match this value. See [Diátaxis Organization](diataxis-organization.md) for folder conventions.

### Trust and lifecycle fields (3)

- **trust_tier**: see [Trust Tiers](trust-tiers.md). Affects vault search weight: canonical 1.5x, working 1.0x, ephemeral 0.7x, archived 0.25x.
- **lifecycle**: see [Lifecycle](lifecycle.md). One of `draft`, `review`, `active`, `superseded`, `archived`.
- **last_reviewed**: ISO date the owner last verified accuracy. Drives staleness alerts.

### Data classification field (1)

- **data_classification**: who can read this.
  - `public`: anyone, including external visitors. Brand assets, public regulatory references.
  - `internal`: every property-affiliated person. Default for most operational content.

This base does not contain `confidential` or `restricted` content. Those live elsewhere.

### Authorship fields (2)

- **author**: array of role names (e.g., `"Compliance Director"`), not person names. The role-to-person mapping lives in the property's roster document. Person names appear only under the three role-indirection exceptions (see [Role Indirection](../../../documentation/patterns/role-indirection.md)).
- **source_artifact**: what this content was derived from, if ingested from a source document. Example: `"Policy Book.pdf p93-97"` or `"Top 20 questions.docx, Benefits #1"`. Empty string if originally authored.

### Relationship fields (3)

- **related**: array of relative paths to documents that should be cross-linked. Pattern: `./path/to/file.md` or `../other-section/file.md`.
- **entities**: array of role names, organization names, and concepts this document mentions. Same person-name exceptions as `author`. Drives entity-relationship features in qp-vault.
- **tags**: array of lowercase kebab-case keywords. Used for filtering and search.

### AI context field (1)

- **ai_context**: multi-line note for AI tools. What audience to assume. What to cite. What to flag for human review. Plain English, no markup needed. Drives prompt-context surfacing.

## A complete Phase 2 example

```yaml
---
title: "Net Operating Income Calculation Methodology"
slug: "noi-calculation-methodology"
description: "How operating income is calculated for an affiliated organization. The basis for any benchmarking claims in the property's public storytelling."

diataxis: "reference"

trust_tier: "canonical"
lifecycle: "active"
last_reviewed: "2026-04-28"

data_classification: "internal"

author: ["Finance Lead"]
source_artifact: "NOI Calculation Methodology.docx"

related:
  - "../policy-book/policy-3800-fiscal-management.md"
  - "../policy-book/policy-5400-client-finance.md"
  - "../../04-explanation/the-thesis-story.md"
entities: ["Finance Lead", "Property Organization", "External Regulatory Body"]
tags: ["finance", "noi", "methodology", "benchmarking"]

ai_context: |
  This document is the canonical NOI calculation. When asked how the
  property calculates its NOI benchmark, cite this document. Pair with
  the thesis-story explanation document for context. The industry
  comparison source is referenced in the explanation document, not here.
---
```

## The Phase 3 schema (additional 14 fields, forward-looking)

When the capsule chain integration ships at portfolio scale, the following fields become available. They are derivable from Phase 2 plus the ledger, so the migration is automatic.

```yaml
# Phase 3 additions (automatic when capsule chain ships)

capsule_id: "uuid-of-the-capsule-sealing-this-document"
capsule_chain_index: 42
capsule_prev_id: "uuid-of-the-previous-capsule-in-this-chain"
capsule_hash: "sha3-256-of-the-capsule-content"

signature_ed25519: "base64-classical-signature"
signature_mldsa65: "base64-post-quantum-signature"

ip_owner: ["Role Name", "Organization Name"]
ip_license: "license-identifier-or-statement"
ip_attribution_required: true | false

effective_date: "YYYY-MM-DD"
expiration_date: "YYYY-MM-DD | null"
supersedes: ["slug-of-previous-version-if-any"]
superseded_by: "slug-of-new-version-if-any"

verification_capsule_id: "uuid-of-the-verification-capsule-if-claim-is-externally-verified"
```

### Capsule chain fields (4)

- **capsule_id**: the capsule that sealed this document version
- **capsule_chain_index**: position in the chain (integer)
- **capsule_prev_id**: the previous capsule's ID; enables forensic chain walks
- **capsule_hash**: SHA3-256 hash of the capsule content; for tamper detection

### Signature fields (2)

- **signature_ed25519**: classical Ed25519 signature over the document content plus capsule context
- **signature_mldsa65**: post-quantum ML-DSA-65 signature over the same; hybrid security model

### IP fields (3)

- **ip_owner**: who owns the IP in this document. Role names primarily; organization names where the IP is institutional. The three person-name exceptions apply.
- **ip_license**: license identifier (e.g., "internal", "Apache-2.0", "proprietary-attribution-required") or short statement
- **ip_attribution_required**: boolean; whether reuse requires attribution

### Lifecycle date fields (4)

- **effective_date**: the date this version of the content takes effect. Different from `last_reviewed` (which tracks freshness verification).
- **expiration_date**: optional date the content stops being valid
- **supersedes**: array of slugs this document replaces
- **superseded_by**: slug of the document that replaces this one when it is superseded

### Verification field (1)

- **verification_capsule_id**: optional reference to a capsule that records external verification of a claim in the document (e.g., a regulatory body confirmed the citation; an auditor confirmed the metric)

## Migration from Phase 2 to Phase 3

When Phase 3 ships:

1. A migration script reads every document in the vault namespace
2. For each, the script computes capsule chain fields from the ledger
3. Signatures are generated from the existing content
4. IP fields are populated from the property's IP-attribution roster
5. Date fields are populated from `last_reviewed` plus the lifecycle history
6. Verification capsule IDs are populated only where verification capsules already exist

No hand-edits required. A document moves from Phase 2 to Phase 3 automatically.

If a document is in Phase 2 and a Phase 3 field is queried, the query returns null with no error. The schema is forward-compatible.

## Validation

A validator script (typically at `_meta/validate.py` or in the property's CI pipeline) checks every document:

- All 14 Phase 2 fields present
- Field types correct (strings, arrays, dates)
- `diataxis` value matches folder location
- `slug` matches filename
- `related` paths resolve to real files
- `last_reviewed` is within 12 months for `active` content
- `author` and `entities` use role names (or are in the three exceptions)

Validation runs on every save when the base is wired into CI. For initial bootstrap, validation is manual: read the file, eyeball the metadata, check for obvious drift.

## Why these specific 14 fields

Trade-offs considered:

- More fields means more rigor but more friction for contributors
- Fewer fields means easier contribution but less filterability
- The 14 listed are the minimum for AI-mediated retrieval to work well, role-indirection to hold, ownership to be clear, and lifecycle to be visible

Removing any of the 14 produces measurable retrieval-quality degradation. Adding more than 14 produces measurable contributor friction without proportional benefit.

## How to apply the schema

For a new document:

1. Copy the schema block from a neighboring file in the same section
2. Replace each field with content-appropriate values
3. Set `trust_tier: working` and `lifecycle: draft` initially
4. Set `last_reviewed: <today>`
5. Leave Phase 3 fields out (they appear automatically when Phase 3 ships)

For an existing document missing fields:

1. Add the missing Phase 2 fields
2. Leave Phase 3 fields out
3. Update `last_reviewed`
4. If the document was created before role indirection was applied, audit `author` and `entities` for person names; replace with role names per the [Role Indirection](../../../documentation/patterns/role-indirection.md) pattern

## Related references

- [Trust Tiers](trust-tiers.md): vault-internal trust weighting
- [Lifecycle](lifecycle.md): vault-internal state machine
- [Diátaxis Organization](diataxis-organization.md): folder structure that matches the `diataxis` field
- [llms.txt and AI Consumption](llms-txt-and-ai-consumption.md): AI surface that consumes this metadata
- [Capsule Chain Anchors](capsule-chain-anchors.md): Phase 3 forward-looking
- [Role Indirection](../../../documentation/patterns/role-indirection.md): the portfolio-wide pattern for `author` and `entities`
- [Writing Conventions](../../../documentation/patterns/writing-conventions.md): how to write the content these fields describe
