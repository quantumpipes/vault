# Trust Tiers

Every resource in qp-vault has a trust tier that governs its search relevance. Trust is not just metadata; it directly affects which results appear first.

## The Four Tiers

| Tier | Search Weight | Auto-Behavior | Use For |
|------|--------------|---------------|---------|
| **CANONICAL** | 1.5x | Immutable (content updates create new version) | Official SOPs, approved policies, signed contracts |
| **WORKING** | 1.0x (default) | Standard | Drafts, in-progress documents, proposals |
| **EPHEMERAL** | 0.7x | Auto-archives after TTL (default 90 days) | Meeting notes, chat transcripts, temporary memos |
| **ARCHIVED** | 0.25x | Low relevance | Superseded versions, retired procedures |

<!-- VERIFIED: enums.py:6-22 — TrustTier enum with docstrings -->
<!-- VERIFIED: search_engine.py:20-26 — TRUST_WEIGHTS dict -->

## How Trust Affects Search

The search ranking formula:

```
relevance = (0.7 * vector_similarity + 0.3 * text_rank) * trust_weight * freshness_decay
```

A CANONICAL document with 0.6 cosine similarity scores higher than a WORKING document with 0.8:
- CANONICAL: 0.6 * 1.5 = 0.90
- WORKING: 0.8 * 1.0 = 0.80

This means official SOPs always surface above drafts, even when drafts are slightly more textually relevant.

## Setting Trust

```python
# On creation
vault.add("SOP content", trust="canonical")
vault.add("Draft notes", trust="working")
vault.add("Standup notes", trust="ephemeral")

# After creation
vault.update(resource_id, trust="canonical")
```

Trust changes emit a `TRUST_CHANGE` audit event.

<!-- VERIFIED: resource_manager.py:233-265 — update() emits TRUST_CHANGE -->

## Freshness Decay

Trust tiers also control how quickly a document's relevance decays over time:

| Tier | Half-Life | Meaning |
|------|-----------|---------|
| CANONICAL | 365 days | Stays relevant for a year |
| WORKING | 180 days | Decays over 6 months |
| EPHEMERAL | 30 days | Decays in a month |
| ARCHIVED | 730 days | Slow decay (historical reference) |

The decay function: `freshness = exp(-age_days / half_life * ln(2))`

A 180-day-old WORKING document has 50% of its original freshness score. A CANONICAL document of the same age retains 70%.

<!-- VERIFIED: search_engine.py:28-36 — FRESHNESS_HALF_LIFE dict -->
<!-- VERIFIED: search_engine.py:49-69 — compute_freshness formula -->

## Custom Weights

Override trust weights via VaultConfig:

```python
from qp_vault.config import VaultConfig

config = VaultConfig(
    trust_weights={
        "canonical": 2.0,     # Even stronger boost
        "working": 1.0,
        "ephemeral": 0.3,     # Heavier penalty
        "archived": 0.1,
    },
    freshness_half_life={
        "canonical": 730,     # 2-year half-life
        "working": 90,        # 3-month half-life
        "ephemeral": 14,      # 2-week half-life
        "archived": 365,
    },
)

vault = Vault("./knowledge", config=config)
```

<!-- VERIFIED: config.py:42-57 — trust_weights and freshness_half_life fields -->

## Data Classification

Orthogonal to trust tiers, every resource also has a data classification that controls AI provider routing:

| Classification | Cloud AI | Local AI | Encryption | Audit |
|---------------|----------|----------|------------|-------|
| `public` | Allowed | Allowed | Optional | Standard |
| `internal` (default) | Allowed | Allowed | Optional | Standard |
| `confidential` | Blocked | Allowed | Required | Enhanced |
| `restricted` | Blocked | Allowed | Required | Every read |

<!-- VERIFIED: enums.py:25-38 — DataClassification enum -->

```python
vault.add("Public announcement", classification="public")
vault.add("Internal memo", classification="internal")
vault.add("Patient records", classification="confidential")
vault.add("Classified intel", classification="restricted")
```
