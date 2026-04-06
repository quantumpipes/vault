---
name: Plugin Request
about: Suggest a new plugin (embedder, parser, or policy)
title: "[Plugin] "
labels: plugin
assignees: ''
---

## Plugin Type

- [ ] Embedder (custom embedding model)
- [ ] Parser (new file format)
- [ ] Policy (governance rule)
- [ ] Storage backend

## Description

What would this plugin do?

## Use Case

Who would use this and why?

## Proposed Interface

```python
from qp_vault.plugins import embedder  # or parser, policy

@embedder("my-plugin")
class MyPlugin:
    # ...
```

## Additional Context

Links to relevant libraries, file format specs, or standards.
