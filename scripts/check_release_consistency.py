#!/usr/bin/env python3
"""Refuse a release whose tag, ``pyproject`` and ``__version__`` disagree.

WHY THIS IS A SCRIPT AND NOT FOUR LINES OF YAML. It began as an inline ``run:`` block in the
publish job, which meant the only way to find out whether it worked was to cut a tag and watch.
A guard you cannot run red on purpose is a decoration, so it moved here where
``tests/test_release_guards.py`` can plant a mismatch and prove it fires.

WHAT IT PREVENTS. On 2026-08-30 ``pyproject.toml`` read ``1.7.0`` while ``main`` sat fourteen
commits past the ``v1.7.0`` tag, four of them features. Nothing in the build objected, because
nothing in the build looked. Publishing from that state would have put four unreleased features
on the index under a number already cut, and PyPI does not allow taking a version back.

    python3 scripts/check_release_consistency.py --tag v1.8.0
    python3 scripts/check_release_consistency.py --tag v1.8.0 --root /some/checkout
    python3 scripts/check_release_consistency.py --self-test   # prove it can still go red
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tempfile
import tomllib

INIT_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.M)


def declared_versions(root: pathlib.Path) -> tuple[str, str]:
    """Read the two places this package states its own version.

    Args:
        root: The repository checkout to read.

    Returns:
        ``(pyproject_version, dunder_version)``.

    Raises:
        FileNotFoundError: Either file is absent.
        ValueError: ``__init__.py`` carries no ``__version__`` assignment.
    """
    pyproject = root / "pyproject.toml"
    init = root / "src" / "qp_vault" / "__init__.py"

    with pyproject.open("rb") as handle:
        project_version = tomllib.load(handle)["project"]["version"]

    match = INIT_RE.search(init.read_text())
    if match is None:
        raise ValueError(f"no __version__ assignment in {init}")
    return project_version, match.group(1)


def check(root: pathlib.Path, tag: str) -> list[str]:
    """Compare a git tag against both declared versions.

    Args:
        root: The repository checkout to read.
        tag: The tag name, with or without its leading ``v``.

    Returns:
        A list of human-readable disagreements. Empty means consistent, and the emptiness is
        the whole result: callers must not treat a truthy return as success.
    """
    wanted = tag[1:] if tag.startswith("v") else tag
    project_version, dunder = declared_versions(root)

    problems = []
    if wanted != project_version:
        problems.append(f"tag {wanted} does not match pyproject version {project_version}")
    if wanted != dunder:
        problems.append(f"tag {wanted} does not match __version__ {dunder}")
    return problems


def _plant(root: pathlib.Path, project_version: str, dunder: str) -> pathlib.Path:
    """Write the smallest tree this guard can read, carrying the versions given.

    Args:
        root: A directory that must NOT already exist. See the refusal below.
        project_version: Version to write into ``pyproject.toml``.
        dunder: Version to write into ``__init__.py``.

    Returns:
        The tree root.

    Raises:
        FileExistsError: ``root`` already exists.
    """
    # `exist_ok=False` is the guard, not a default. This function writes two FIXED filenames,
    # `pyproject.toml` and `src/qp_vault/__init__.py`, into a directory the caller names. Pointed
    # at a real checkout it would silently overwrite this package's own version declarations,
    # which is the arbitrary-file-write shape a dir check plus a fixed name always has. Refusing
    # an existing directory means it can only ever land somewhere nothing lives yet.
    root.mkdir(parents=True, exist_ok=False)
    (root / "src" / "qp_vault").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "qp-vault"\nversion = "{project_version}"\n'
    )
    (root / "src" / "qp_vault" / "__init__.py").write_text(f'__version__ = "{dunder}"\n')
    return root


def self_test() -> int:
    """Prove this guard still fires, by planting the defect it claims to catch.

    A guard nobody can make go red is a decoration, and the publish job runs this before it
    trusts the real check. Both directions are asserted: a consistent tree must pass, or a guard
    that refused everything would satisfy the failing case and block every release.

    Returns:
        0 when the guard both fires on a mismatch and stays quiet on a match.
    """
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)

        agree = _plant(base / "agree", "9.9.9", "9.9.9")
        checks.append(
            ("passes when tag, pyproject and __version__ agree", not check(agree, "v9.9.9"))
        )

        stale = _plant(base / "stale", "9.9.8", "9.9.8")
        checks.append(("fires when the tag is ahead of pyproject", bool(check(stale, "v9.9.9"))))

        half = _plant(base / "half", "9.9.9", "9.9.8")
        checks.append(("fires when only __version__ was forgotten", bool(check(half, "v9.9.9"))))

        missing = base / "missing"
        try:
            check(missing, "v9.9.9")
            unreadable_refuses = False
        except (FileNotFoundError, KeyError, ValueError):
            unreadable_refuses = True
        checks.append(("refuses rather than passes when it cannot look", unreadable_refuses))

    for label, ok in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    failed = [label for label, ok in checks if not ok]
    if failed:
        print(f"\nself-test FAILED: {len(failed)} of {len(checks)}", file=sys.stderr)
        return 1
    print(f"\nself-test passed ({len(checks)} checks)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the guard, or its self-test, and report an exit code CI can act on.

    Args:
        argv: Command-line arguments, or None to read ``sys.argv``.

    Returns:
        0 when the versions agree (or the self-test passes), 1 when they disagree, and 2 when the
        tree could not be read at all. Two is deliberately distinct from one: "could not look" is
        not "nothing wrong", and a caller that collapses them turns an unreadable checkout into a
        pass.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="the git tag being published, e.g. v1.8.0")
    parser.add_argument("--root", default=".", help="repository checkout to read")
    parser.add_argument(
        "--self-test", action="store_true", help="prove the guard can still go red, then exit"
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.tag:
        parser.error("--tag is required unless --self-test is given")

    root = pathlib.Path(args.root).resolve()
    try:
        problems = check(root, args.tag)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        # An unreadable tree is NOT a pass. A guard that cannot look must say so and fail,
        # or "could not look" becomes indistinguishable from "nothing wrong".
        print(f"REFUSED: cannot read version declarations under {root}: {exc}", file=sys.stderr)
        return 2

    project_version, dunder = declared_versions(root)
    # Emit the measurement, never only the verdict. A reader needs the three numbers.
    print(f"tag={args.tag} pyproject={project_version} __version__={dunder}")

    if problems:
        for problem in problems:
            print(f"REFUSED: {problem}", file=sys.stderr)
        return 1
    print("release versions agree")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
