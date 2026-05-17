# Diátaxis Organization for qp-vault Source Documents

> The recommended folder structure for markdown source documents under a qp-vault namespace. Inherits the Diátaxis four-category architecture from the portfolio patterns and adds qp-vault-specific guidance for namespace layout, _meta directories, and brand asset separation.

## Why Diátaxis

The four-category framework (Tutorials, How-to, Reference, Explanation) is the portfolio-wide convention for organizing operational content. It is mutually exclusive (one document is exactly one type) and collectively exhaustive (no content falls outside the four). For the rationale and full framework, see [Diátaxis Architecture](../../../documentation/patterns/diataxis-architecture.md).

This document covers the qp-vault-specific implementation: how to lay out the folders, where the meta directories go, how brand assets fit, how the layout maps to qp-vault namespaces.

## Recommended folder shape

```
{namespace}/
├── README.md                       The orientation document
├── llms.txt                        AI-readable index
├── llms-full.txt                   Full content for AI (regenerated nightly)
├── SITEMAP.md                      Visual sitemap with file counts and ownership
│
├── _meta/                          Organizational metadata, not content
│   ├── conventions.md              Local naming/linking/ownership rules
│   ├── frontmatter-schema.md       Or link to the canonical schema doc
│   └── roster.md                   Role-to-person mapping
│
├── _brand/                         Brand assets (if the property has its own brand)
│   └── {brand-id}/                 Per-brand subdirectory
│       ├── README.md
│       └── _assets/                Binary files (logos, palettes)
│
├── 01-tutorials/                   Diátaxis: tutorial
│   └── README.md
│
├── 02-how-to/                      Diátaxis: how-to
│   ├── README.md
│   └── {domain}/                   Sub-grouped by problem domain
│       ├── README.md
│       └── *.md
│
├── 03-reference/                   Diátaxis: reference
│   ├── README.md
│   └── {section}/                  Sub-grouped by source artifact
│       ├── README.md
│       └── *.md
│
├── 04-explanation/                 Diátaxis: explanation
│   ├── README.md
│   └── *.md
│
└── 06-regulatory/                  Optional: reference subset for external rules
    ├── README.md
    └── {jurisdiction}/             Per-jurisdiction subdirectory
        ├── README.md
        └── *.md
```

## The five conventions

### Numeric prefixes on top-level directories

`01-`, `02-`, `03-`, `04-`, `06-`. Numeric prefixes preserve ordering when directories are listed alphabetically. Number 05 is intentionally skipped (reserved for a property-specific category that does not fit cleanly in the four; most properties do not need it).

### Underscore prefix for organizational metadata

`_meta/` and `_brand/` carry leading underscores. The convention signals "this is metadata about the base, not content within it." Some renderers and search tools hide underscore-prefixed directories by default; this is acceptable because the content there is not for direct discovery.

### No numeric prefix on sub-directories

Within `02-how-to/`, sub-directories like `benefits/`, `compliance/`, `finance/` do not carry numeric prefixes unless ordering matters. The first-level Diátaxis grouping is ordered; second-level grouping is alphabetical.

### One Diátaxis type per top-level directory

Documents under `02-how-to/` are how-to type. Documents under `03-reference/` are reference type. The folder is the type. Mixing types within a folder is the most common Diátaxis failure mode.

### README per directory

Every directory has a README that:

- Declares the section owner (a role name per [Role Indirection](../../../documentation/patterns/role-indirection.md))
- Describes what lives in the section
- Describes how the section grows

The README is the navigation entry point. AI agents reading the base start with the READMEs to build a section map.

## How qp-vault namespaces map to Diátaxis

A qp-vault namespace is the logical scope of a vault instance. Common patterns:

| Namespace name | Scope | Diátaxis fit |
|---|---|---|
| `{property}-operational` | A property's full operational substrate | All four types active |
| `{property}-public` | Customer-facing public knowledge | Reference + Explanation mostly |
| `regulatory:us:{state}` | Per-state external rules | Reference only |
| `{property}-{topic}` | Topic-bounded subset of a property | Subset of types |

The Diátaxis shape applies to any namespace where operational content accumulates. For specialized namespaces (e.g., a per-state regulatory namespace), the namespace may contain only reference content; the directory shape still applies (with empty `01-tutorials/`, `02-how-to/`, `04-explanation/` if the property prefers consistency).

## How to populate the shape

For a new namespace, see [Knowledge-Base Bootstrap](../../../documentation/patterns/knowledge-base-bootstrap.md) for the 1-to-3-day checklist.

For an existing knowledge base migrating into qp-vault:

1. Inventory every document; tag with its Diátaxis type
2. Identify the mislabeled or split-personality documents; split them
3. Create the four top-level directories under the new namespace
4. Move documents into the correct directory
5. Add the frontmatter `diataxis` field
6. Add the `_meta/roster.md` and `_meta/conventions.md`
7. Add the `llms.txt` index
8. Validate

A 100-document base typically migrates in 1 to 2 days.

## How qp-vault consumes the shape

qp-vault's search and retrieval surface uses several fields from the Diátaxis-organized structure:

### Folder-derived filters

A query like "show me only how-to articles about benefits" maps to:

```python
vault.search("benefits", filter={"diataxis": "how-to"})
```

This is the cheapest filter qp-vault provides; it does not need to read document bodies.

### Section-owned retrieval

A query like "show me canonical content owned by the Compliance Director" maps to:

```python
vault.search(
    query,
    filter={
        "author": ["Compliance Director"],
        "trust_tier": "canonical",
    }
)
```

The role-indirection pattern means this filter stays correct across personnel changes.

### Cross-section traversal

A `related` array enables qp-vault's knowledge graph (see [Knowledge Graph](knowledge-graph.md)) to traverse relationships. A how-to article that references a Policy can return both documents when an AI agent asks "how do I handle medication errors":

```python
results = vault.search("medication errors")
# results include the how-to article
# follow related[] to retrieve the Policy
```

## The optional sixth top-level

Number 06 is reserved for external-rule subsets that are reference content but are usefully scoped separately (federal rules, state rules, vendor product manuals not authored by the property). Typical use:

```
06-regulatory/
├── README.md
├── federal/
│   └── *.md
└── state/
    ├── ca/
    │   └── *.md
    ├── ut/
    │   └── *.md
    └── ...
```

External-rule content sits under 06 rather than under 03-reference because:

- The owner is typically different (a regulatory-tracking role rather than the policy-authoring role)
- The growth axis is different (new jurisdictions add subdirectories; existing rules update on different cadences)
- The source artifact is external (regulatory body PDFs, not internal authored content)

If a property does not have external-rule content at scale, skip 06; the four standard Diátaxis directories are enough.

## Common mistakes

### Mistake 1: A `guides/` or `documentation/` directory

A catch-all category that accumulates everything not categorized. Becomes unnavigable.

**Fix**: split into the four Diátaxis types. Delete the catch-all.

### Mistake 2: Nested Diátaxis directories

`02-how-to/01-tutorials/` or similar. Confuses the four-category limit.

**Fix**: the four are top-level only. Sub-directories within a Diátaxis section group by domain, not by Diátaxis type.

### Mistake 3: Hex-numeric prefixes that drift

`02-how-to/`, `03-reference/`, `99-misc/`. The misc directory becomes a graveyard.

**Fix**: do not create misc. Force everything into the four. If something does not fit, it belongs in a different namespace.

### Mistake 4: Brand assets in 03-reference

`03-reference/brand/`. Brand is configuration (an input to surfaces), not knowledge (an output to readers).

**Fix**: brand goes in `_brand/`. The leading underscore signals "metadata not content."

### Mistake 5: Mixing Diátaxis types within a folder

`02-how-to/policy-5700.md` (a reference document filed under how-to).

**Fix**: move to `03-reference/policy-book/policy-5700.md`. Update cross-references.

## Validating Diátaxis compliance

A validator script can check:

- Folder location matches frontmatter `diataxis` field
- No documents at the top level outside of README, llms.txt, llms-full.txt, SITEMAP
- Every directory has a README
- No directory has more than one Diátaxis type's documents

Run validation on every save in CI, or manually during quarterly section reviews.

## How this grows

As the property matures:

- **More documents**: each category fills with content; the shape stays
- **More sub-domains**: new `{domain}/` subdirectories appear within `02-how-to/` and within `03-reference/`
- **More jurisdictions**: new state subdirectories appear in `06-regulatory/state/`
- **More tutorial sequences**: as Boot Camp or onboarding curriculum builds out, `01-tutorials/` fills
- **More explanation depth**: as the property's thesis matures, `04-explanation/` deepens

The four-category limit holds. New top-level categories are not added.

## Related references

- [Diátaxis Architecture (portfolio pattern)](../../../documentation/patterns/diataxis-architecture.md): the full framework and rationale
- [Knowledge-Base Bootstrap (portfolio pattern)](../../../documentation/patterns/knowledge-base-bootstrap.md): the checklist for starting a new base
- [Source Document Frontmatter](source-document-frontmatter.md): the 14-field schema that every document carries
- [Knowledge Graph](knowledge-graph.md): how qp-vault traverses relationships between Diátaxis-organized documents
- [llms.txt and AI Consumption](llms-txt-and-ai-consumption.md): the AI surface that consumes the Diátaxis-organized structure
