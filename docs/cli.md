# CLI Reference

The `vault` command-line tool provides all core operations.

## Install

```bash
pip install qp-vault[cli]
```

Requires: `typer` and `rich` (installed automatically with the `[cli]` extra).

<!-- VERIFIED: pyproject.toml:42-45 — cli extra includes typer + rich -->

## Commands

### vault init

Create a new vault.

```bash
vault init <path>
```

Creates the directory, initializes SQLite database, and sets up the audit log.

```bash
$ vault init ./org-knowledge
Vault initialized at /home/user/org-knowledge
```

<!-- VERIFIED: cli/main.py:70-80 — init command -->

### vault add

Add a resource to the vault.

```bash
vault add <file> [options]
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--trust` | `-t` | `working` | Trust tier: canonical, working, ephemeral, archived |
| `--layer` | `-l` | (none) | Memory layer: operational, strategic, compliance |
| `--tags` | | (none) | Comma-separated tags |
| `--name` | `-n` | (auto) | Display name (auto-detected from filename) |
| `--path` | `-p` | `.` | Vault directory path |

```bash
$ vault add report.pdf --trust canonical --layer strategic --tags "q4,finance"
Added: report.pdf
  ID: a1b2c3d4-...
  Trust: canonical
  Chunks: 12
  CID: vault://sha3-256/...
```

<!-- VERIFIED: cli/main.py:82-117 — add command with options -->

### vault search

Search the vault with trust-weighted hybrid search.

```bash
vault search <query> [options]
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--top-k` | `-k` | `10` | Maximum results |
| `--path` | `-p` | `.` | Vault directory path |

```bash
$ vault search "incident response" --top-k 5
Search: "incident response" (2 results)
 #  Trust       Resource                Relevance  Content
 1  canonical   sop-incident.md         0.450      Incident response: acknowledge within...
 2  working     draft-response.md       0.280      Draft incident response improvements...
```

<!-- VERIFIED: cli/main.py:119-155 — search command with Rich table -->

### vault inspect

Show detailed information about a resource.

```bash
vault inspect <resource-id> [--path <vault-path>]
```

```bash
$ vault inspect a1b2c3d4-...
sop-incident-response.md

  ID              a1b2c3d4-...
  CID             vault://sha3-256/8c822da2...
  Content Hash    8c822da28547d9e9...
  Trust Tier      canonical
  Status          indexed
  Lifecycle       active
  Chunks          3
  Size            1,247 bytes
  Created         2026-04-06 14:30:00
```

<!-- VERIFIED: cli/main.py:157-200 — inspect command -->

### vault status

Show vault summary.

```bash
vault status [--path <vault-path>]
```

```bash
$ vault status
Vault Status  (./org-knowledge)

  Total resources: 42

  By trust tier:
    canonical: 12
    working: 25
    ephemeral: 5

  By status:
    indexed: 40
    pending: 2
```

<!-- VERIFIED: cli/main.py:202-229 — status command -->

### vault verify

Verify integrity of a resource or the entire vault.

```bash
# Verify entire vault (Merkle tree)
vault verify [--path <vault-path>]

# Verify single resource
vault verify <resource-id> [--path <vault-path>]
```

```bash
$ vault verify
PASS  Vault integrity verified
  Resources: 42
  Merkle root: a92f56269aaa0d8c...
  Duration: 12ms

$ vault verify a1b2c3d4-...
PASS  a1b2c3d4-...
  Hash: 8c822da28547d9e9...
  Chunks verified: 3
```

Exit code 1 if verification fails.

<!-- VERIFIED: cli/main.py:231-268 — verify command with exit code -->

## Global Options

All commands accept `--path` / `-p` to specify the vault directory. Defaults to the current directory.

```bash
vault search "query" --path /opt/knowledge
vault status --path ./my-vault
```
