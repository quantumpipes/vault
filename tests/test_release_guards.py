"""Vacuity tests for the three release guards added on 2026-08-30.

WHY THIS FILE EXISTS. This repository shipped 1.5.2 to PyPI from a CI run whose overall
conclusion reads ``failure``, then tagged v1.6.0 and v1.7.0 and published neither, and nobody
noticed for five months. Every one of those states was visible to a check that did not exist.
The three guards added alongside this file close them:

  1. ``ruff format --check src/ tests/``      formatting is asserted, not merely available
  2. ``publish: needs: [... typecheck ...]``  a red typecheck can no longer ship an artifact
  3. ``scripts/check_release_consistency.py`` the tag must equal both declared versions

**A guard is not trusted here until it has been made to fail on purpose.** The dominant defect
shape in this estate is an instrument that reports success while checking nothing, so each test
below plants the specific defect the guard claims to catch and asserts the red, then asserts the
green on the real tree so the red is attributable to the plant and not to the guard being broken
in general.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "python-ci.yaml"
GUARD = REPO / "scripts" / "check_release_consistency.py"

# The two files the release guard reads, and the version they both carry on a consistent tree.
PYPROJECT = REPO / "pyproject.toml"
INIT = REPO / "src" / "qp_vault" / "__init__.py"


def _current_version() -> str:
    """Read the version this checkout declares.

    Returns:
        The ``project.version`` string from ``pyproject.toml``.
    """
    import tomllib

    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def _fixture_tree(root: pathlib.Path, project_version: str, dunder: str) -> pathlib.Path:
    """Build the smallest tree the release guard can read.

    Args:
        root: Directory to build under.
        project_version: Version to write into ``pyproject.toml``.
        dunder: Version to write into ``__init__.py``.

    Returns:
        The tree root.
    """
    (root / "src" / "qp_vault").mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "qp-vault"\nversion = "{project_version}"\n'
    )
    (root / "src" / "qp_vault" / "__init__.py").write_text(f'__version__ = "{dunder}"\n')
    return root


def _run_guard(root: pathlib.Path, tag: str) -> subprocess.CompletedProcess[str]:
    """Invoke the guard as CI does, out of process.

    Args:
        root: The tree the guard should read.
        tag: The tag to compare against, with or without its leading ``v``.

    Returns:
        The completed process, so a test can assert on the exit code AND the message.
    """
    return subprocess.run(
        [sys.executable, str(GUARD), "--tag", tag, "--root", str(root)],
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Guard 3: tag versus the two declared versions
# ---------------------------------------------------------------------------


def test_the_release_guard_passes_when_all_three_agree(tmp_path: pathlib.Path) -> None:
    """The positive control. Without it, a guard that failed on everything would pass below."""
    tree = _fixture_tree(tmp_path, "1.8.0", "1.8.0")

    result = _run_guard(tree, "v1.8.0")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "release versions agree" in result.stdout
    # The measurement, not only the verdict.
    assert "pyproject=1.8.0" in result.stdout


def test_the_release_guard_catches_a_tag_ahead_of_pyproject(tmp_path: pathlib.Path) -> None:
    """The exact 2026-08-30 defect: main moved on, pyproject did not."""
    tree = _fixture_tree(tmp_path, "1.7.0", "1.7.0")

    result = _run_guard(tree, "v1.8.0")

    assert result.returncode == 1
    assert "does not match pyproject version 1.7.0" in result.stderr


def test_the_release_guard_catches_a_half_bumped_version(tmp_path: pathlib.Path) -> None:
    """`pyproject` bumped and `__version__` forgotten is the likeliest human error.

    This repository has already made it once in the other direction: commit d870d7b reads
    "sync __version__ to 1.7.0 to match pyproject", which is a fix for a drift that shipped.
    """
    tree = _fixture_tree(tmp_path, "1.8.0", "1.7.0")

    result = _run_guard(tree, "v1.8.0")

    assert result.returncode == 1
    assert "__version__ 1.7.0" in result.stderr
    assert "pyproject" not in result.stderr  # only the half that actually drifted is named


def test_the_release_guard_refuses_rather_than_passes_when_it_cannot_look(
    tmp_path: pathlib.Path,
) -> None:
    """An unreadable tree must be a refusal, never a pass.

    "Could not look" and "nothing wrong" are different states, and collapsing them is how a
    guard reports healthy on a system it never inspected.
    """
    result = _run_guard(tmp_path / "does-not-exist", "v1.8.0")

    assert result.returncode == 2
    assert "cannot read" in result.stderr


def test_the_release_guard_agrees_with_the_real_tree() -> None:
    """Bind the guard to the object we actually care about, not only to fixtures."""
    version = _current_version()

    result = _run_guard(REPO, f"v{version}")

    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Guard 1: ruff format is checked, not merely installed
# ---------------------------------------------------------------------------


def _ruff() -> str:
    """Locate the ruff the workflow would run.

    Returns:
        Absolute path to the ruff executable.

    Raises:
        Skipped: Via ``pytest.skip`` when ruff is not installed.
    """
    ruff = shutil.which("ruff")
    if ruff is None:
        pytest.skip("ruff is not on PATH")
    return ruff


def test_ruff_format_check_fails_on_an_unformatted_file(tmp_path: pathlib.Path) -> None:
    """Plant unformatted source and prove the command the workflow runs goes red.

    95 files in this repository were unformatted when the check was added, so the workflow step
    would have been red on its first run had it not been formatted in the same change. That is
    the failure this asserts stays reachable.
    """
    victim = tmp_path / "unformatted.py"
    victim.write_text("x = {   'a':1,'b':2 }\ndef  f( a ,b ):\n  return a+b\n")

    result = subprocess.run(
        [_ruff(), "format", "--check", str(tmp_path)], capture_output=True, text=True
    )

    assert result.returncode != 0
    assert "unformatted.py" in result.stdout + result.stderr


def test_ruff_format_check_passes_on_the_real_source_tree() -> None:
    """The positive control, and the assertion that keeps the tree formatted."""
    result = subprocess.run(
        [_ruff(), "format", "--check", "src/", "tests/"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Guard 2: publish is gated on typecheck
# ---------------------------------------------------------------------------


def _workflow() -> dict:
    """Parse the CI workflow so its gates can be asserted rather than eyeballed.

    Returns:
        The parsed workflow document.

    Raises:
        Skipped: Via ``importorskip`` when PyYAML is absent, which should not happen: it is
            declared in the dev extra precisely so these assertions run instead of skipping.
    """
    yaml = pytest.importorskip(
        "yaml", reason="PyYAML is declared in the dev extra; a skip here means it went missing"
    )
    return yaml.safe_load(WORKFLOW.read_text())


def test_publish_is_gated_on_every_quality_job() -> None:
    """`publish` must not run while any check is red.

    It used to read ``needs: [lint, test]``, and that is precisely how 1.5.2 reached the index
    from a run whose conclusion reads ``failure``: only ``typecheck`` was red and publish did
    not care. Anyone reading the run instead of the job concluded 1.5.2 had never shipped.
    """
    jobs = _workflow()["jobs"]
    needs = set(jobs["publish"]["needs"])

    quality_jobs = {name for name in jobs if name != "publish"}
    missing = quality_jobs - needs
    assert not missing, f"publish can run while these are red: {sorted(missing)}"
    assert "typecheck" in needs


def test_the_gate_assertion_can_fail() -> None:
    """The vacuity test for the test above.

    Without this, `test_publish_is_gated_on_every_quality_job` would pass just as happily
    against a workflow with no quality jobs at all, which is the shape it exists to forbid.
    """
    jobs = {"lint": {}, "typecheck": {}, "test": {}, "publish": {"needs": ["lint", "test"]}}

    needs = set(jobs["publish"]["needs"])
    missing = {name for name in jobs if name != "publish"} - needs

    assert missing == {"typecheck"}


def test_the_workflow_pins_its_linters_to_exact_versions() -> None:
    """An unpinned linter turns `main` red with nobody having changed a line.

    That is not hypothetical here: ``pip install ruff`` with no pin is what this workflow ran
    while ``main`` sat red for five months, and a red lint keeps the last good artifact as the
    published one.
    """
    env = _workflow()["env"]

    assert env["RUFF_VERSION"].count(".") == 2, "ruff must be pinned to an exact patch version"
    text = WORKFLOW.read_text()
    assert "pip install ruff\n" not in text
    assert 'pip install "ruff==${{ env.RUFF_VERSION }}"' in text


def test_the_lint_job_covers_every_python_directory() -> None:
    """No directory of Python may sit outside the linter's named paths.

    The lint job named ``src/`` and ``tests/`` and stopped there, so ``scripts/`` was linted by
    nothing. That is where ``check_release_consistency.py`` lives: the one script CI runs to
    protect a release was itself unchecked, and it was unformatted when this test was written.
    A guard outside the guarded set is the shape this whole file exists to catch.
    """
    lint_steps = _workflow()["jobs"]["lint"]["steps"]
    commands = " ".join(step.get("run", "") for step in lint_steps)

    covered = {part.rstrip("/") for part in commands.split() if part.endswith("/")}
    python_dirs = {
        child.name
        for child in REPO.iterdir()
        if child.is_dir()
        and not child.name.startswith((".", "_"))
        and child.name not in {"dist", "docs", "examples", "evals", "node_modules"}
        and any(child.rglob("*.py"))
    }

    missing = python_dirs - covered
    assert not missing, f"lint does not cover: {sorted(missing)} (covers {sorted(covered)})"


def test_the_coverage_assertion_can_fail() -> None:
    """The vacuity test for the one above.

    Without it, that assertion would pass just as happily against a lint job that named no paths
    at all, since an empty `python_dirs` minus anything is still empty.
    """
    commands = "ruff check src/ tests/"

    covered = {part.rstrip("/") for part in commands.split() if part.endswith("/")}
    missing = {"src", "tests", "scripts"} - covered

    assert missing == {"scripts"}


def test_the_workflow_runs_on_a_schedule() -> None:
    """A silent red must become a dated red.

    Both tag failures went unnoticed for months because nothing ran again after the push that
    broke them. ``on.schedule`` is what turns "nobody has looked since August" into a run.
    """
    triggers = _workflow()[True]  # PyYAML parses the bare `on:` key as the boolean True

    assert "schedule" in triggers
    assert triggers["schedule"][0]["cron"]
