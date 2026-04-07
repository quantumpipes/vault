# Plugin Development

qp-vault is extensible via plugins. Add custom embedding models, file parsers, and governance policies without modifying core code.

## Plugin Categories

| Category | Decorator | Interface | Purpose |
|----------|-----------|-----------|---------|
| Embedder | `@embedder("name")` | `embed(texts) -> vectors` | Custom embedding models |
| Parser | `@parser("name")` | `parse(path) -> ParseResult` | Custom file formats |
| Policy | `@policy("name")` | `evaluate(resource, action, context) -> PolicyResult` | Governance rules |

## Writing a Plugin

### Custom Embedder

```python
from qp_vault.plugins import embedder

@embedder("my-model")
class MyEmbedder:
    dimensions = 768

    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Your embedding logic here
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("nomic-ai/nomic-embed-text-v1.5")
        return model.encode(texts).tolist()
```

<!-- VERIFIED: plugins/decorators.py:20-33 — @embedder decorator -->

### Custom Parser

```python
from pathlib import Path
from qp_vault.plugins import parser
from qp_vault.protocols import ParseResult

@parser("dicom")
class DicomParser:
    supported_extensions = {".dcm", ".dicom"}

    async def parse(self, path: Path) -> ParseResult:
        text = extract_dicom_text(path)
        return ParseResult(
            text=text,
            metadata={"format": "dicom", "patient_id": "redacted"},
            pages=0,
        )
```

<!-- VERIFIED: plugins/decorators.py:36-49 — @parser decorator -->

### Custom Policy

```python
from qp_vault.plugins import policy
from qp_vault.protocols import PolicyResult

@policy("itar")
class ItarPolicy:
    async def evaluate(self, resource, action, context) -> PolicyResult:
        if resource.data_classification == "restricted" and action == "search":
            if context.get("provider_type") == "cloud":
                return PolicyResult(allowed=False, reason="ITAR: restricted content cannot use cloud AI")
        return PolicyResult(allowed=True)
```

<!-- VERIFIED: plugins/decorators.py:52-65 — @policy decorator -->

## Registration Methods

### 1. Explicit Registration (Programmatic)

```python
vault = Vault("./knowledge")
vault.register_embedder(MyEmbedder())
vault.register_parser(DicomParser())
vault.register_policy(ItarPolicy())
```

<!-- VERIFIED: vault.py:644-656 — register_embedder/parser/policy methods -->

### 2. Entry Points (Installed Packages)

In your plugin package's `pyproject.toml`:

```toml
[project.entry-points."qp_vault.embedders"]
my-model = "my_package:MyEmbedder"

[project.entry-points."qp_vault.parsers"]
dicom = "my_package:DicomParser"

[project.entry-points."qp_vault.policies"]
itar = "my_package:ItarPolicy"
```

After `pip install my-package`, qp-vault discovers them automatically.

<!-- VERIFIED: plugins/registry.py:82-124 — discover_entry_points() -->

### 3. Plugins Directory (Air-Gap Mode)

For environments without internet access (SCIF, air-gapped networks):

```python
vault = Vault("./knowledge", plugins_dir="/opt/qp/plugins/")
```

Drop `.py` files in the plugins directory. Any class decorated with `@embedder`, `@parser`, or `@policy` is auto-discovered.

**A `manifest.json` is required.** This file maps each plugin filename to its SHA3-256 hash. Without it, the entire directory is skipped for security.

```
/opt/qp/plugins/
    manifest.json       # Required: SHA3-256 hashes for each .py file
    my_embedder.py      # Contains @embedder("local-model") class
    dicom_parser.py     # Contains @parser("dicom") class
    itar_policy.py      # Contains @policy("itar") class
```

Generate the manifest:

```python
import hashlib, json, pathlib

plugins_dir = pathlib.Path("/opt/qp/plugins")
manifest = {}
for f in sorted(plugins_dir.glob("*.py")):
    if not f.name.startswith("_"):
        manifest[f.name] = hashlib.sha3_256(f.read_bytes()).hexdigest()
(plugins_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
```

Security rules:
- Files not listed in the manifest are rejected
- Hash mismatches are logged and the file is skipped
- Files starting with `_` are always skipped
- Broken files log a warning and are skipped
- To disable hash verification: `discover_plugins_dir(path, verify_hashes=False)` (not recommended)

<!-- VERIFIED: plugins/registry.py:131-189 — manifest required, hash verification -->

## Discovery Order

When qp-vault initializes, plugins are discovered in this order:

1. **Explicit registration**: `vault.register_*(instance)`
2. **Entry points**: installed packages with `qp_vault.*` entry points
3. **Plugins directory**: `.py` files in `plugins_dir`

Later registrations override earlier ones for the same name.

## Plugin Registry API

```python
from qp_vault.plugins import get_registry

registry = get_registry()
registry.list_embedders()    # ["my-model", "openai"]
registry.list_parsers()      # ["dicom", "cad"]
registry.list_policies()     # ["itar", "hipaa"]

registry.get_embedder("my-model")           # Returns instance
registry.get_parser_for_extension(".dcm")   # Finds matching parser
```

<!-- VERIFIED: plugins/registry.py:56-78 — get/list methods -->

## Lifecycle Hooks

Register callbacks for vault events:

```python
from qp_vault.plugins import get_registry

registry = get_registry()
registry.register_hook("pre_index", my_callback)
registry.register_hook("post_search", my_callback)
registry.register_hook("on_trust_change", my_callback)
```

<!-- VERIFIED: plugins/registry.py:52-54 — register_hook method -->
