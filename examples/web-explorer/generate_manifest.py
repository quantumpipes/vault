#!/usr/bin/env python3
"""Generate ``manifest.js`` for the QP Vault web explorer from a directory on disk.

The explorer (``index.html``) is a single, dependency-free, air-gap-safe page that
renders whatever this script writes into ``manifest.js``. It populates four globals:

    window.VAULT_BASE     base URL used to open files in a new tab + resolve images
    window.VAULT_FILES    sorted list of relative file paths (the tree is derived)
    window.VAULT_META     { "<relpath>": { "m": "YYYY-MM-DD" } }  (modified date)
    window.VAULT_CONTENT  { "<relpath>": "<text>" }  for readable/searchable files

and, optionally, header + governance hints:

    window.VAULT_TITLE / VAULT_SUBTITLE / VAULT_DESC
    window.VAULT_FOLDER_DESC  { "<folder>": "<one-line description>" }
    window.VAULT_TIERS        { "<folder>": ["Canonical", "canonical"] }   (tier pill)

The same contract can be emitted from a real qp-vault export, so this on-disk
generator is just the simplest producer. No third-party dependencies.

Examples
--------
    # browse the current directory
    python generate_manifest.py .

    # browse a vault, give it a title, write next to index.html
    python generate_manifest.py ~/work/policies --title "Policy Vault" -o manifest.js

    # names + tree only, skip file contents (smaller manifest, no full-text search)
    python generate_manifest.py . --no-content
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Extensions whose contents are inlined for the reader + full-text search.
TEXT_EXT = {
    "md", "markdown", "mdx", "txt", "text", "rst", "adoc",
    "json", "jsonc", "yaml", "yml", "toml", "ini", "cfg", "conf", "properties",
    "csv", "tsv", "log",
    "py", "pyi", "js", "mjs", "cjs", "ts", "tsx", "jsx",
    "css", "scss", "html", "htm", "xml", "svg",
    "sh", "bash", "zsh", "sql", "graphql", "proto", "dockerfile", "makefile",
    "typ", "tex", "bib",
}

# Directory names skipped entirely.
DEFAULT_IGNORE_DIRS = {
    ".git", ".hg", ".svn", ".bzr",
    "node_modules", ".venv", "venv", "env", "__pycache__",
    ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox",
    "dist", "build", ".next", ".cache", ".idea", ".vscode",
}

# Individual file names skipped.
DEFAULT_IGNORE_FILES = {".DS_Store", "Thumbs.db", "manifest.js"}


def looks_binary(path: Path, sniff: int = 2048) -> bool:
    """Cheap binary sniff: a NUL byte in the first ``sniff`` bytes means binary."""
    try:
        with path.open("rb") as fh:
            return b"\x00" in fh.read(sniff)
    except OSError:
        return True


def is_textual(path: Path) -> bool:
    ext = path.suffix.lower().lstrip(".")
    if ext in TEXT_EXT:
        return True
    if not ext and path.name.lower() in {"readme", "license", "notice", "authors", "changelog"}:
        return True
    return False


def iso_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def collect(root: Path, ignore_dirs: set[str], include_hidden: bool) -> list[Path]:
    """Walk ``root`` and return relative file paths, pruning ignored/hidden dirs."""
    files: list[Path] = []
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if not include_hidden and name.startswith("."):
                continue
            if entry.is_dir():
                if name in ignore_dirs:
                    continue
                stack.append(entry)
            elif entry.is_file():
                if name in DEFAULT_IGNORE_FILES:
                    continue
                files.append(entry.relative_to(root))
    files.sort(key=lambda p: str(p).lower())
    return files


def build(args: argparse.Namespace) -> str:
    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"error: not a directory: {root}")

    ignore_dirs = DEFAULT_IGNORE_DIRS | set(args.ignore or [])
    rels = collect(root, ignore_dirs, args.all)

    files: list[str] = []
    meta: dict[str, dict] = {}
    content: dict[str, str] = {}
    content_bytes = 0

    for rel in rels:
        posix = rel.as_posix()
        files.append(posix)
        full = root / rel
        try:
            meta[posix] = {"m": iso_day(full.stat().st_mtime)}
        except OSError:
            pass
        if args.no_content:
            continue
        if not is_textual(full) or looks_binary(full):
            continue
        try:
            size = full.stat().st_size
        except OSError:
            continue
        if size > args.max_bytes:
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        content[posix] = text
        content_bytes += len(text.encode("utf-8"))

    base = args.base if args.base is not None else root.as_uri().rstrip("/") + "/"

    parts = [
        "// Generated by generate_manifest.py. Do not edit by hand.",
        f"// {len(files)} files from {root}",
        f"window.VAULT_BASE={json.dumps(base)};",
    ]
    if args.title:
        parts.append(f"window.VAULT_TITLE={json.dumps(args.title)};")
    if args.subtitle:
        parts.append(f"window.VAULT_SUBTITLE={json.dumps(args.subtitle)};")
    if args.desc:
        parts.append(f"window.VAULT_DESC={json.dumps(args.desc)};")
    parts.append(f"window.VAULT_FILES={json.dumps(files, ensure_ascii=False)};")
    parts.append(f"window.VAULT_META={json.dumps(meta, ensure_ascii=False)};")
    parts.append(f"window.VAULT_CONTENT={json.dumps(content, ensure_ascii=False)};")

    sys.stderr.write(
        f"vault: {len(files)} files, {len(content)} with content "
        f"({content_bytes/1024:.0f} KB), base {base}\n"
    )
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("root", nargs="?", default=".", help="directory to index (default: .)")
    p.add_argument("-o", "--output", default="manifest.js", help="output file (default: manifest.js)")
    p.add_argument("--title", help="explorer header title")
    p.add_argument("--subtitle", help="explorer header subtitle")
    p.add_argument("--desc", help="root description line shown above the file list")
    p.add_argument("--base", help="base URL for opening files (default: file:// of the indexed dir; use '' for relative when served over http)")
    p.add_argument("--max-bytes", type=int, default=512 * 1024, help="per-file content cap in bytes (default: 524288)")
    p.add_argument("--no-content", action="store_true", help="index names + tree only; skip file contents (no full-text search)")
    p.add_argument("--ignore", action="append", help="extra directory name to skip (repeatable)")
    p.add_argument("--all", action="store_true", help="include hidden (dotfile) entries")
    args = p.parse_args(argv)

    manifest = build(args)
    Path(args.output).write_text(manifest, encoding="utf-8")
    sys.stderr.write(f"wrote {args.output}\n")


if __name__ == "__main__":
    main()
