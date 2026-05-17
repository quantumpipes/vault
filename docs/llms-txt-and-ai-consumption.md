# llms.txt and AI Consumption

> The llms.txt format and its companion llms-full.txt as standard AI-consumption surfaces for a qp-vault namespace. How they are structured, how they are regenerated, and how AI agents use them to discover and read source documents efficiently.

## What llms.txt is

A markdown file at the root of a knowledge base or vault namespace that gives AI agents a curated entry point. The format follows the emerging community convention: a heading, a short orientation paragraph, and curated links into the most important documents grouped by purpose.

The pattern serves the same function as a sitemap for search engines, but optimized for AI agents that consume markdown content directly rather than HTML.

## Why llms.txt matters

An AI agent landing on a knowledge base for the first time faces a discovery problem: read every file (slow, expensive, often impossible within context windows) or guess based on filenames (fast, error-prone). The llms.txt index solves this: the agent reads one file (typically under 100 lines), understands the base's shape, and navigates to the documents it needs.

The pattern matters at scale. A 200-file vault is unreadable in a single agent context window. An llms.txt that points to the 20 most-important documents (the canonical-tier reference, the explanation documents, the operational entry points) lets the agent be effective without exceeding context.

## The two files

Most qp-vault namespaces ship two AI-consumption surfaces:

| File | Size | Regeneration | Purpose |
|---|---|---|---|
| `llms.txt` | Approximately 50 to 150 lines | Hand-curated; updated on structural changes | The orientation index |
| `llms-full.txt` | Approximately 5K to 50K lines | Auto-regenerated nightly | The full searchable corpus for AI context |

`llms.txt` is the discovery surface. `llms-full.txt` is the deep-dive corpus. Agents start with the first, drill into the second when needed.

## llms.txt format

```markdown
# {Namespace} Knowledge Base

> One paragraph orientation: what the base is, who maintains it, what scope.

## Quick orientation

- [Root README](README.md): What this is, who can see it, what is excluded
- [Visual sitemap](SITEMAP.md): Full directory tree with file counts and ownership
- [Conventions](_meta/conventions.md): Naming, linking, ownership rules
- [Roster](_meta/roster.md): Role-to-person mapping
- [Frontmatter schema](_meta/frontmatter-schema.md): The metadata fields every file carries

## Reference (the lookup material)

- [Section index 1](03-reference/section-1/README.md): description
- [Section index 2](03-reference/section-2/README.md): description
- [Glossary](03-reference/glossary/README.md): terms, acronyms, definitions

## How-to (the do-this-now articles)

- [Category 1](02-how-to/category-1/README.md): description
- [Category 2](02-how-to/category-2/README.md): description

## Explanation (the why)

- [Mission](04-explanation/our-mission.md): description
- [Thesis](04-explanation/the-thesis-story.md): description

## Regulatory (external rules)

- [Jurisdiction overview](06-regulatory/state/{jurisdiction}/README.md): description

## Tutorials (learning sequences)

(If populated; otherwise note that the section is empty by design.)

## Brand and configuration

- [Brand assets](_brand/README.md): logo files, palettes, brand reference

## What is NOT in this base

(Excluded categories from the README: legal, HR, PHI, commercial pricing, partnership negotiations, etc.)
```

The structure is rigid by convention; the content is flexible. The structure is rigid so AI agents that have seen one llms.txt can navigate any other.

## What goes in llms.txt vs SITEMAP.md

| Question | llms.txt | SITEMAP.md |
|---|---|---|
| Audience | AI agents (and humans who think like them) | Humans (and AI agents who want detail) |
| Format | Curated section links, short | Full directory tree, file counts, ownership |
| Update cadence | When structure changes | Same or more frequent |
| Length | Under 200 lines | Often longer; one section per directory |
| Purpose | Discovery and entry | Audit and ownership |

The two are complementary. llms.txt is the agent's first-read. SITEMAP.md is the human's audit-read.

## llms-full.txt format

Auto-regenerated nightly (typical) or on commit (high-frequency). The format concatenates every canonical-tier and active-lifecycle document, with separators:

```
================================================================
FILE: 03-reference/policy-book/policy-5700-medication-management.md
TRUST_TIER: canonical
LIFECYCLE: active
LAST_REVIEWED: 2025-11-01
================================================================

(Full document content here, including frontmatter and body.)


================================================================
FILE: 03-reference/noi-methodology/noi-calculation-methodology.md
TRUST_TIER: canonical
LIFECYCLE: active
LAST_REVIEWED: 2026-04-28
================================================================

(Full document content.)

(Repeat for every canonical-tier active document.)
```

The regeneration script:

1. Walks the namespace
2. Filters for `trust_tier: canonical` and `lifecycle: active` documents (Phase 2 schema)
3. Adds a header per file with key metadata
4. Concatenates the file content
5. Writes to `llms-full.txt`

Document order: typically by frontmatter `diataxis` (reference first, then explanation, then how-to, then tutorial), then by slug alphabetically within each type.

## How AI agents use these files

### Pattern 1: discover, then dive

The agent reads `llms.txt` first to understand the base's shape and scope. Then it reads the specific documents linked from llms.txt that match the user's query.

```
1. Agent receives user query: "what is the audit-defense process"
2. Agent reads llms.txt
3. Agent identifies the Reference and Regulatory sections as relevant
4. Agent reads the specific Policy and regulatory documents
5. Agent answers
```

This pattern is cheap: 1 file (llms.txt) plus 2 to 5 specific files. Typical token cost: under 10K.

### Pattern 2: corpus-load and search

The agent loads `llms-full.txt` once at the start of a session, then searches the concatenated text for relevant content. Higher upfront cost but better for sessions with many queries.

```
1. Agent loads llms-full.txt (50K lines, ~250K tokens; or chunked)
2. Agent searches for "medication errors" across the corpus
3. Agent surfaces the relevant Policy and how-to documents
4. Agent answers
```

This pattern works for agents with large context windows or that are chunking the corpus across retrieval calls.

### Pattern 3: vault search via API

When the agent has direct qp-vault API access, llms.txt may not be needed:

```python
results = vault.search("medication errors")
```

The vault returns ranked results using trust-tier weights and freshness decay. The llms.txt approach is the fallback for agents without API access; the vault search is the primary surface for agents with it.

## Regeneration

### llms.txt regeneration

Hand-curated. Updated when:

- A new section is added
- A new entry-point document is created (a new mission document, a new glossary, a new high-leverage how-to)
- The base's scope changes (a new property the base covers, a new excluded category)
- The roster reorganizes substantially

Typical cadence: monthly to quarterly review. The file is small enough that hand-curation is feasible indefinitely.

### llms-full.txt regeneration

Auto-regenerated by a script. Typical cadence: nightly via cron, or on every commit via CI.

```python
# Pseudo-code for llms-full.txt regeneration
def regenerate_llms_full(namespace):
    docs = vault.list_documents(
        namespace=namespace,
        filter={"trust_tier": "canonical", "lifecycle": "active"},
        order_by=["diataxis", "slug"],
    )
    with open("llms-full.txt", "w") as f:
        for doc in docs:
            f.write(separator(doc))
            f.write(doc.content)
            f.write("\n\n")
```

The script lives at `_meta/regenerate-llms-full.py` or similar. CI runs it; the output is committed (or hosted separately, with a stable URL).

## Versioning

For published vaults where AI agents may have cached prior versions of llms.txt, include a version stamp in the file:

```markdown
# {Namespace} Knowledge Base

> Version: 2026-05-17
> (Auto-regenerated llms-full.txt is timestamped at the top of the file.)

(rest of content)
```

The version stamp lets agents detect when they have a stale cache and re-fetch.

## Trust-tier interaction

llms.txt typically links to canonical-tier content only. Working and ephemeral content is not promoted to the index because it is not yet stable enough for agent consumption.

llms-full.txt filters for canonical-tier active content. This is deliberate: an agent reading the full corpus should not surface working-tier drafts as authoritative.

If a base wants to expose working-tier content to agents for partial relevance, regenerate a second file (e.g., `llms-working.txt`) and document it separately. The convention is that llms-full.txt is canonical-only.

## Privacy boundaries

llms.txt and llms-full.txt expose `data_classification: internal` content to AI agents that have access to the base. Properties that publish externally must filter:

- Public vault namespaces ship llms.txt and llms-full.txt directly
- Internal vault namespaces ship llms.txt and llms-full.txt to authorized agents only
- Confidential namespaces should not ship llms.txt at all; AI access is direct-API only with explicit authorization

The `data_classification` frontmatter field drives the filter; the regeneration script respects it.

## Anti-patterns

### Anti-pattern 1: llms.txt that is auto-generated

If llms.txt auto-generates from the directory tree, it becomes a duplicate of SITEMAP.md. The point of llms.txt is curation: an agent reading the file should be able to identify the 10 to 20 most-important documents without reading everything. Curate by hand.

### Anti-pattern 2: llms-full.txt that includes drafts

A draft document in the full corpus reads as authoritative to an agent that does not check frontmatter. Filter for canonical-tier active content.

### Anti-pattern 3: No regeneration cadence

llms-full.txt that goes stale becomes worse than no file. Set up the cron or CI job before populating the file.

### Anti-pattern 4: Linking outside the base

llms.txt is the base's index, not the property's external map. Do not link to external URLs (sales pages, marketing sites). External material has its own discovery surface.

### Anti-pattern 5: Hardcoded person names in llms.txt

Same role-indirection rule applies. If the README mentions a role, llms.txt references the role.

## How llms.txt scales across the portfolio

Every Synova-portfolio property's vault namespace ships its own llms.txt and llms-full.txt. The convention is identical across properties. An AI agent that has navigated one property's llms.txt can navigate any other property's llms.txt without retraining.

This is the value of standardizing the format: AI agents become portfolio-aware once they have learned the pattern. Future agents inherit the discovery surface without re-learning.

## Related references

- [Diátaxis Organization](diataxis-organization.md): the folder structure that llms.txt indexes
- [Source Document Frontmatter](source-document-frontmatter.md): the metadata that drives llms-full.txt filtering
- [Trust Tiers](trust-tiers.md): the filter for what content is canonical enough to surface
- [Lifecycle](lifecycle.md): the filter for what content is active enough to surface
- [Knowledge-Base Bootstrap](../../../documentation/patterns/knowledge-base-bootstrap.md): how llms.txt fits into the bootstrap checklist
