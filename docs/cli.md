# CLI Reference

The `vault` CLI provides 15 commands for managing governed knowledge stores.

```bash
pip install qp-vault[cli]
```

## Commands

### vault init

```bash
vault init <path>
```

Initialize a new vault. Creates SQLite database and audit log.

### vault add

```bash
vault add <file> [--trust T] [--layer L] [--tags t1,t2] [--name N] [--path P]
```

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--trust` | `-t` | `working` | Trust tier: canonical, working, ephemeral, archived |
| `--layer` | `-l` | (none) | Memory layer: operational, strategic, compliance |
| `--tags` | | (none) | Comma-separated tags |
| `--name` | `-n` | (auto) | Display name |
| `--path` | `-p` | `.` | Vault directory |

### vault search

```bash
vault search <query> [--top-k N] [--path P]
```

Trust-weighted hybrid search with Rich table output.

### vault list

```bash
vault list [--trust T] [--layer L] [--tenant ID] [--limit N] [--path P]
```

List resources with optional filters. Shows trust tier, name, status, and ID.

<!-- VERIFIED: cli/main.py:278-305 -->

### vault inspect

```bash
vault inspect <resource-id> [--path P]
```

Show detailed metadata: CID, content hash, trust tier, status, lifecycle, chunks, size, timestamps.

### vault status

```bash
vault status [--path P]
```

Vault summary: total resources, breakdown by trust tier, status, and layer.

### vault verify

```bash
vault verify [resource-id] [--path P]
```

Without resource-id: verify entire vault (Merkle root). With resource-id: verify single resource (SHA3-256 hash check). Exit code 1 on failure.

### vault health

```bash
vault health [--path P]
```

Composite health score (0-100): freshness, uniqueness, coherence, connectivity, issues.

<!-- VERIFIED: cli/main.py:263-275 -->

### vault delete

```bash
vault delete <resource-id> [--hard] [--path P]
```

Soft delete (default) or permanent hard delete.

<!-- VERIFIED: cli/main.py:308-317 -->

### vault transition

```bash
vault transition <resource-id> <target> [--reason R] [--path P]
```

Change lifecycle state. Valid targets depend on current state (see [Lifecycle](lifecycle.md)).

<!-- VERIFIED: cli/main.py:321-336 -->

### vault expiring

```bash
vault expiring [--days N] [--path P]
```

Show resources expiring within N days (default: 90).

<!-- VERIFIED: cli/main.py:339-352 -->

### vault content

```bash
vault content <resource-id> [--path P]
```

Retrieve and display the full text content of a resource.

<!-- VERIFIED: cli/main.py:356-367 -->

### vault replace

```bash
vault replace <resource-id> <file-or-text> [--path P]
```

Replace content atomically. Creates new version, supersedes old. Shows old ID (SUPERSEDED) and new ID.

<!-- VERIFIED: cli/main.py:370-383 -->

### vault supersede

```bash
vault supersede <old-id> <new-id> [--path P]
```

Link two resources: old becomes SUPERSEDED, new gets `supersedes` pointer.

<!-- VERIFIED: cli/main.py:386-395 -->

### vault collections

```bash
vault collections [--path P]
```

List all named collections.

<!-- VERIFIED: cli/main.py:398-409 -->

### vault provenance

```bash
vault provenance <resource-id> [--path P]
```

Show provenance records: upload timestamp, uploader, method.

<!-- VERIFIED: cli/main.py:412-424 -->

### vault export

```bash
vault export <output-file> [--path P]
```

Export vault to JSON file. Shows resource count.

<!-- VERIFIED: cli/main.py:427-436 -->

## Global Options

All commands accept `--path` / `-p` to specify the vault directory.

## Exit Codes

- `0`: Success
- `1`: Failure (verification failed, resource not found, invalid transition)

Designed for CI: `vault verify && deploy`.
