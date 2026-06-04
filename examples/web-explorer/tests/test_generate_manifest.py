#!/usr/bin/env python3
"""Contract tests for generate_manifest.py (on-disk scan + governance export adapter).

Asserts the emitted manifest satisfies the window.VAULT_* contract the explorer reads,
so the generator can never silently drift from index.html. Runs standalone
(`python tests/test_generate_manifest.py`) and under pytest.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from argparse import Namespace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import generate_manifest as gm  # noqa: E402


def _parse(js: str) -> dict:
    """Parse `window.NAME=<json|void 0>;` single-line statements into a dict."""
    out: dict = {}
    for line in js.splitlines():
        m = re.match(r"^window\.(\w+)=(.*);$", line)
        if not m:
            continue
        name, raw = m.group(1), m.group(2)
        if raw.strip() in ("void 0", "undefined"):
            out[name] = None
            continue
        # the on-disk clearer line packs two statements; handle the first
        raw = raw.split(";window.")[0]
        try:
            out[name] = json.loads(raw)
        except json.JSONDecodeError:
            out[name] = raw
    return out


def _ondisk_args(root: str, **kw) -> Namespace:
    base = dict(root=root, from_export=None, output="manifest.js", title=None, subtitle=None,
                desc=None, base=None, max_bytes=512 * 1024, no_content=False, ignore=None, all=False)
    base.update(kw)
    return Namespace(**base)


def _export_args(path: str, **kw) -> Namespace:
    base = dict(root=".", from_export=path, output="manifest.js", title=None, subtitle=None,
                desc=None, base=None, max_bytes=512 * 1024, no_content=False, ignore=None, all=False)
    base.update(kw)
    return Namespace(**base)


def test_ondisk_contract():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "sub").mkdir()
        (root / "a.md").write_text("# A\nfindme alpha\n", encoding="utf-8")
        (root / "sub" / "b.txt").write_text("beta body", encoding="utf-8")
        (root / "logo.png").write_bytes(b"\x00\x01binary\x00")
        g = _parse(gm.build(_ondisk_args(str(root))))

    assert g["VAULT_FILES"] == ["a.md", "logo.png", "sub/b.txt"], g["VAULT_FILES"]
    assert "findme alpha" in g["VAULT_CONTENT"]["a.md"]
    assert "logo.png" not in g["VAULT_CONTENT"], "binary content must not be inlined"
    assert g["VAULT_GOV"] == {}, "on-disk mode clears governance"
    assert g["VAULT_CHUNKS"] is None, "on-disk mode emits no chunks"
    assert re.match(r"\d{4}-\d{2}-\d{2}", g["VAULT_META"]["a.md"]["m"])


def test_ondisk_no_content():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "x.md").write_text("hi", encoding="utf-8")
        g = _parse(gm.build(_ondisk_args(d, no_content=True)))
    assert g["VAULT_FILES"] == ["x.md"]
    assert g["VAULT_CONTENT"] == {}, "no-content mode inlines nothing"


def test_export_governance_contract():
    g = _parse(gm.build_from_export(_export_args(str(ROOT / "sample-export.json"))))
    files = g["VAULT_FILES"]
    # tier-grouped, canonical first
    assert files[0].startswith("CANONICAL/"), files
    assert any(p.startswith("ARCHIVED/") for p in files)
    gov = g["VAULT_GOV"]
    hb = gov["CANONICAL/company-handbook.md"]
    assert hb["tier"] == "canonical"
    assert hb["cid"].startswith("vault://sha3-256/")
    assert hb["lifecycle"] == "active"
    # supersession chain resolves to a path
    q3 = gov["WORKING/q3-roadmap-draft.md"]
    assert q3["supersedes"] == "r-q2"
    assert g["VAULT_IDPATH"]["r-q2"] == "ARCHIVED/q2-roadmap.md"
    # chunks present for verification
    assert g["VAULT_CHUNKS"]["CANONICAL/company-handbook.md"], "chunks must be present"
    assert g["VAULT_CONTENT"] is None, "export derives content from chunks"


def test_export_cid_is_hash_consistent():
    """Every chunk CID must equal sha3-256 of its content (matches qp-vault's scheme)."""
    g = _parse(gm.build_from_export(_export_args(str(ROOT / "sample-export.json"))))
    n = 0
    for path, chunks in g["VAULT_CHUNKS"].items():
        for c in chunks:
            expect = "vault://sha3-256/" + hashlib.sha3_256(c["c"].encode()).hexdigest()
            assert c["h"] == expect, f"{path}: CID mismatch"
            n += 1
    assert n >= 5, "sample should have at least 5 verifiable chunks"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} contract tests passed")
