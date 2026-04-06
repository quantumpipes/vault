# Knowledge Lifecycle

qp-vault models knowledge as a living system. Documents are not static files; they have lifecycles with creation, approval, activation, supersession, expiration, and archival.

## State Machine

```
DRAFT ----> REVIEW ----> ACTIVE ----> SUPERSEDED ----> ARCHIVED
  |            |            |
  |            |         EXPIRED ----> ACTIVE (re-activate)
  |            |            |               |
  +---> ARCHIVED    +---> ARCHIVED   +---> ARCHIVED
```

<!-- VERIFIED: lifecycle_engine.py:22-28 — VALID_TRANSITIONS dict -->

### Valid Transitions

| From | To | Description |
|------|----|-------------|
| DRAFT | REVIEW | Submit for review |
| DRAFT | ACTIVE | Skip review (emergency publish) |
| DRAFT | ARCHIVED | Abandon draft |
| REVIEW | ACTIVE | Approve |
| REVIEW | DRAFT | Send back for revision |
| REVIEW | ARCHIVED | Reject permanently |
| ACTIVE | SUPERSEDED | Replaced by newer version |
| ACTIVE | EXPIRED | Past valid_until date |
| ACTIVE | ARCHIVED | Retire manually |
| SUPERSEDED | ARCHIVED | Archive superseded version |
| EXPIRED | ACTIVE | Re-activate (extend validity) |
| EXPIRED | ARCHIVED | Archive expired version |
| ARCHIVED | (none) | Terminal state |

## Basic Usage

```python
from qp_vault import Vault, Lifecycle

vault = Vault("./knowledge")

# Create a draft
policy = vault.add(
    "Security policy for remote access...",
    name="security-policy-v2.md",
    trust="canonical",
    lifecycle="draft",
)

# Move through review
vault.transition(policy.id, "review", reason="Ready for security team review")
vault.transition(policy.id, "active")
```

<!-- VERIFIED: lifecycle_engine.py:55-96 — transition() method -->

Invalid transitions raise `LifecycleError`:

```python
# ACTIVE -> DRAFT is not allowed
try:
    vault.transition(active_resource.id, "draft")
except LifecycleError as e:
    print(e)  # "Cannot transition from active to draft. Allowed: superseded, expired, archived"
```

## Supersession

When a newer version replaces an older one:

```python
v1 = vault.add("Policy v1", name="policy-v1.md", trust="canonical")
v2 = vault.add("Policy v2 with PQ crypto", name="policy-v2.md", trust="canonical")

# Supersede: v1 -> SUPERSEDED, linked to v2
old, new = vault.supersede(v1.id, v2.id)

assert old.lifecycle == "superseded"
assert old.superseded_by == v2.id
assert new.supersedes == v1.id
```

<!-- VERIFIED: lifecycle_engine.py:98-147 — supersede() sets pointers -->

### Supersession Chains

Walk the full version history:

```python
chain = vault.chain(v1.id)
# Returns: [v1, v2, v3, ...] in chronological order

for version in chain:
    print(f"{version.name} [{version.lifecycle.value}]")
```

Chains are walked both directions (via `supersedes` and `superseded_by` pointers) and have cycle protection (max 1000 links).

<!-- VERIFIED: lifecycle_engine.py:205-252 — chain() with visited set + max_length -->

## Temporal Validity

Resources can have time windows during which they are considered authoritative:

```python
from datetime import date

vault.add(
    "Q4 2025 budget allocation",
    name="budget-q4-2025.md",
    trust="canonical",
    valid_from=date(2025, 10, 1),
    valid_until=date(2025, 12, 31),
)
```

### Point-in-Time Search

Query what was active at a specific date:

```python
# "What was our budget policy on November 15, 2025?"
results = vault.search("budget allocation", as_of=date(2025, 11, 15))
```

### Expiration Alerts

Find resources about to expire:

```python
# What's expiring in the next 90 days?
expiring = vault.expiring(days=90)

for r in expiring:
    print(f"{r.name} expires {r.valid_until}")
```

<!-- VERIFIED: lifecycle_engine.py:174-203 — expiring() with date comparison -->

### Auto-Expiration

Resources with `valid_until` in the past are automatically transitioned to EXPIRED when `check_expirations()` runs:

```python
expired = await vault._lifecycle.check_expirations()
```

<!-- VERIFIED: lifecycle_engine.py:149-172 — check_expirations auto-transitions -->

## Audit Trail

Every lifecycle transition emits a `LIFECYCLE_TRANSITION` VaultEvent:

```json
{
    "event_type": "lifecycle_transition",
    "resource_id": "abc-123",
    "details": {
        "from": "draft",
        "to": "active",
        "reason": "Approved by security team"
    }
}
```

Supersession emits both `LIFECYCLE_TRANSITION` (for the state change) and `SUPERSEDE` (for the pointer linkage).
