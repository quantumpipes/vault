# Web Explorer

A single-file, no-build, air-gap-safe browser UI for exploring a vault on disk. Open one HTML file and get a folder tree, an inline markdown reader, full-text search, semantic folder and document-file icons, a type filter, a document outline, and full keyboard navigation. No server, no framework, no external requests.

It lives in [`examples/web-explorer/`](../examples/web-explorer/). The explorer is `index.html`; a stdlib-only `generate_manifest.py` produces the data it reads.

## Quick start

```bash
cd examples/web-explorer

# point the generator at the directory you want to browse
python generate_manifest.py /path/to/your/vault --title "My Vault"

# open the explorer (it reads the manifest.js you just wrote)
open index.html          # macOS; xdg-open on Linux, or double-click
```

Browse this repository itself:

```bash
python generate_manifest.py ../.. --title "QP Vault"
open index.html
```

Regenerate the manifest and reload whenever the underlying files change.

## How it renders: the manifest contract

`index.html` is fully static. It renders whatever globals `manifest.js` defines:

| Global | Shape | Purpose |
|--------|-------|---------|
| `window.VAULT_BASE` | string | base URL for "open in tab" and image resolution |
| `window.VAULT_FILES` | `string[]` | relative file paths; the folder tree is derived from these |
| `window.VAULT_META` | `{ [path]: { m: "YYYY-MM-DD" } }` | modified date; drives "Recently updated" and sort |
| `window.VAULT_CONTENT` | `{ [path]: string }` | inlined text for the reader and full-text search |

Optional globals tune the chrome and governance display:

| Global | Shape | Purpose |
|--------|-------|---------|
| `window.VAULT_TITLE` / `VAULT_SUBTITLE` | string | header title and subtitle |
| `window.VAULT_DESC` | string | description line above the root file list |
| `window.VAULT_FOLDER_DESC` | `{ [folder]: string }` | one-line description per top-level folder |
| `window.VAULT_TIERS` | `{ [folder]: [label, cssClass] }` | governance tier pill, e.g. `["Canonical", "canonical"]` (classes: `canonical`, `working`, `ephemeral`) |

Because the explorer only depends on that contract, `generate_manifest.py` is just the simplest producer. The same `window.VAULT_*` shape can be emitted from a qp-vault export carrying real [trust tiers](trust-tiers.md), content-addressed IDs, and [lifecycle](lifecycle.md) state, so the same UI can front a governed vault instead of a raw directory.

## Generator

```
python generate_manifest.py [root] [options]

  root                 directory to index (default: .)
  -o, --output FILE    output file (default: manifest.js)
  --title / --subtitle / --desc TEXT   header and root description
  --base URL           base URL for opening files (default: file:// of the indexed dir;
                       use '' for relative paths when serving over http)
  --max-bytes N        per-file content cap (default: 524288)
  --no-content         index names and tree only; skip contents (no full-text search)
  --ignore NAME        extra directory name to skip (repeatable)
  --all                include hidden (dotfile) entries
```

Text files (markdown, code, config, csv, and similar) are inlined for the reader and search; binaries are listed in the tree and open in a new tab. The generator uses only the Python standard library. Common build and cache directories (`.git`, `node_modules`, `.venv`, `__pycache__`, `dist`, and others) are skipped by default.

## Theming

The look is driven entirely by CSS custom properties in the `:root` block at the top of `index.html`. Change those tokens to reskin; nothing else is hardcoded. The default is a neutral light theme with an indigo accent. File-type colors (the document-icon bands) and folder-category tints are intentionally fixed so file types stay recognizable across themes, the way a desktop file manager keeps type colors stable.

Folders get a category icon and tint inferred from their name (`docs`, `src`, `tests`, `config`, `assets`, `data`, plus knowledge-vault categories like `governance`, `research`, `risk`, and `archive`). Unrecognized names get a clean default folder.

## Air-gap and privacy

The explorer makes zero network requests: no fonts CDN, no analytics, no framework from a package host. Fonts are system fonts. Everything renders from the local manifest, so it is safe to open on an air-gapped machine.

A generated `manifest.js` embeds file contents in plain text, so treat it with the same care as the directory it indexes. Do not commit one that points at private paths; the example's `.gitignore` excludes `manifest.js` for that reason.

## When to use it

Reach for the web explorer for a quick, human-browsable view of a vault directory or export, for demos, and for read-only audits. It is a viewer, not a write path: use the [Python SDK](api-reference.md) or [FastAPI integration](fastapi.md) to add, govern, and search programmatically.

## See also

- [`examples/web-explorer/README.md`](../examples/web-explorer/README.md) for the full reference
- [Getting Started](getting-started.md), [Trust Tiers](trust-tiers.md), [CLI Reference](cli.md)
