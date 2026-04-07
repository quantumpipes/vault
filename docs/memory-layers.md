# Memory Layers

Organizations don't think in folders. They think in operational urgency ("how do I do this right now?"), strategic context ("why did we decide this?"), and regulatory obligation ("can we prove compliance?").

qp-vault models this with three memory layers, each with its own defaults for trust, search behavior, and retention.

## The Three Layers

| Layer | Default Trust | Search Boost | Retention | Audit Reads | Use For |
|-------|--------------|-------------|-----------|-------------|---------|
| **OPERATIONAL** | WORKING | 1.5x | Standard | No | SOPs, runbooks, deploy procedures |
| **STRATEGIC** | CANONICAL | 1.0x | Standard | No | ADRs, OKRs, architecture decisions |
| **COMPLIANCE** | CANONICAL | 1.0x | Permanent | **Yes** | Audit evidence, certifications, regulatory docs |

<!-- VERIFIED: layer_manager.py:37-65 — DEFAULT_LAYER_CONFIGS -->

## Usage

```python
from qp_vault import Vault, MemoryLayer

vault = Vault("./org-knowledge")

# Add to specific layers
vault.add("Deploy: check health, scale down, deploy, scale up",
          name="deploy-runbook.md", layer="operational")

vault.add("ADR-001: Chose PostgreSQL for ACID compliance",
          name="adr-001.md", layer="strategic")

vault.add("SOC2 Type II audit completed 2025-12-15",
          name="soc2-cert.pdf", layer="compliance")
```

## Scoped Operations with LayerView

Get a scoped view that auto-applies layer defaults:

```python
# OPERATIONAL: adds with trust_tier=WORKING by default
ops = vault.layer(MemoryLayer.OPERATIONAL)
await ops.add("runbook-content", name="runbook.md")
# Equivalent to: vault.add(..., trust_tier="working", layer="operational")

# STRATEGIC: adds with trust_tier=CANONICAL by default
strategic = vault.layer(MemoryLayer.STRATEGIC)
await strategic.add("architecture decision", name="adr.md")

# COMPLIANCE: adds with trust_tier=CANONICAL, and every search is audited
compliance = vault.layer(MemoryLayer.COMPLIANCE)
await compliance.add("audit evidence", name="audit.pdf")
results = await compliance.search("SOC2")
# ^^ This search is recorded in the audit trail
```

<!-- VERIFIED: layer_manager.py:130-199 — LayerView with add(), search(), list() -->

## Layer-Scoped Search

```python
# Search only operational knowledge
ops = vault.layer("operational")
results = await ops.list()  # Only operational resources

# Cross-layer search with vault.search() still works
all_results = vault.search("deploy procedure")
# Returns results from all layers, ranked by relevance + layer boost
```

## Compliance Layer: Read Auditing

The COMPLIANCE layer is special: every search operation is recorded in the audit trail. This creates a verifiable log of who accessed compliance evidence and when.

```python
compliance = vault.layer(MemoryLayer.COMPLIANCE)
results = await compliance.search("SOC2 certification")
# Creates audit event: {"event_type": "search", "details": {"query": "SOC2...", "layer": "compliance"}}
```

<!-- VERIFIED: layer_manager.py:170-184 — audit_reads check in LayerView.search() -->

## Layer Statistics

```python
status = vault.status()
print(status["layer_details"])
# {
#   "operational":  {"resource_count": 12, "default_trust": "working", ...},
#   "strategic":    {"resource_count": 5,  "default_trust": "canonical", ...},
#   "compliance":   {"resource_count": 3,  "default_trust": "canonical", "audit_reads": true, ...},
# }
```

<!-- VERIFIED: layer_manager.py:107-126 — get_stats() method -->

## Custom Layer Configuration

Override defaults via VaultConfig:

```python
from qp_vault.config import VaultConfig, LayerDefaults

config = VaultConfig(
    layer_defaults={
        "operational": LayerDefaults(
            trust_tier="working",
            half_life_days=60,        # Faster freshness decay
            search_boost=2.0,         # Higher priority in search
        ),
        "compliance": LayerDefaults(
            trust_tier="canonical",
            retention="permanent",
            audit_reads=True,
        ),
    },
)

vault = Vault("./knowledge", config=config)
```

<!-- VERIFIED: config.py:13-17 — LayerDefaults dataclass -->
