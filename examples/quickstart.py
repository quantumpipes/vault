#!/usr/bin/env python3
# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""qp-vault quickstart example.

Run:
    pip install qp-vault
    python examples/quickstart.py
"""

from qp_vault import Vault, TrustTier, MemoryLayer

# Create a vault (SQLite, zero config)
vault = Vault("./example-vault")

# Add resources with trust tiers
sop = vault.add(
    "Standard operating procedure for incident response. "
    "When an incident is detected, the on-call engineer must "
    "acknowledge within 15 minutes and classify severity.",
    name="sop-incident-response.md",
    trust_tier="canonical",        # 1.5x search boost
    layer="operational",      # Operational memory
)
print(f"Added: {sop.name} [{sop.trust_tier.value}] ({sop.chunk_count} chunks)")
print(f"  CID: {sop.cid}")

draft = vault.add(
    "Draft proposal for new onboarding process. "
    "Current onboarding takes 3 weeks. We propose reducing to 2 weeks.",
    name="draft-onboarding.md",
    trust_tier="working",
    lifecycle="draft",
)
print(f"Added: {draft.name} [{draft.trust_tier.value}]")

# Trust-weighted search
print("\n--- Search: 'incident response' ---")
results = vault.search("incident response")
for i, r in enumerate(results, 1):
    print(f"  {i}. [{r.trust_tier.value}] {r.resource_name} "
          f"(relevance={r.relevance:.3f}, trust_weight={r.trust_weight})")

# Lifecycle transition
vault.transition(draft.id, "review")
vault.transition(draft.id, "active")
print(f"\n{draft.name}: draft -> review -> active")

# Merkle verification
result = vault.verify()
print(f"\nVault integrity: {'PASS' if result.passed else 'FAIL'}")
print(f"  Resources: {result.resource_count}")
print(f"  Merkle root: {result.merkle_root[:32]}...")

# Health score
health = vault.health()
print(f"\nHealth score: {health.overall}/100")

# Status
status = vault.status()
print(f"\nStatus: {status['total_resources']} resources")
print(f"  Trust tiers: {status['by_trust_tier']}")

# Export proof (for auditors)
proof = vault.export_proof(sop.id)
print(f"\nMerkle proof for {sop.name}:")
print(f"  Resource hash: {proof.resource_hash[:32]}...")
print(f"  Merkle root:   {proof.merkle_root[:32]}...")
print(f"  Proof path:    {len(proof.path)} nodes")

print("\nDone.")
