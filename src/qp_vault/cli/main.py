"""qp-vault CLI: vault command for managing governed knowledge stores.

Usage:
    vault init <path>
    vault add <file> [--trust T] [--layer L] [--tags t1,t2]
    vault search <query> [--top-k N]
    vault inspect <resource-id>
    vault status
    vault verify [resource-id]
"""

import sys
from pathlib import Path
from typing import Any

try:
    import typer
    from rich.console import Console
    from rich.table import Table
except ImportError:
    print("CLI requires: pip install qp-vault[cli]", file=sys.stderr)
    sys.exit(1)

from qp_vault.vault import Vault

app = typer.Typer(
    name="vault",
    help="Governed knowledge store for autonomous organizations.",
    no_args_is_help=True,
)
console = Console()

# State: vault path is resolved from --path option or current directory
_vault_path: str = "."


def _get_vault(path: str | None = None) -> Vault:
    """Get a Vault instance for the given or default path."""
    vault_dir = Path(path or _vault_path)
    if not (vault_dir / "vault.db").exists() and path is None:
        console.print("[red]No vault found in current directory. Run 'vault init <path>' first.[/red]")
        raise typer.Exit(1)
    return Vault(vault_dir)


@app.command()
def init(
    path: str = typer.Argument(..., help="Directory path for the new vault"),
) -> None:
    """Initialize a new vault."""
    vault_dir = Path(path)
    if (vault_dir / "vault.db").exists():
        console.print(f"[yellow]Vault already exists at {vault_dir}[/yellow]")
        return

    vault = Vault(vault_dir)
    # Trigger initialization by calling status
    vault.status()
    console.print(f"[green]Vault initialized at {vault_dir.resolve()}[/green]")


@app.command()
def add(
    file: str = typer.Argument(..., help="File path or text content to add"),
    trust: str = typer.Option("working", "--trust", "-t", help="Trust tier: canonical, working, ephemeral, archived"),
    layer: str | None = typer.Option(None, "--layer", "-l", help="Memory layer: operational, strategic, compliance"),
    tags: str | None = typer.Option(None, "--tags", help="Comma-separated tags"),
    name: str | None = typer.Option(None, "--name", "-n", help="Display name (auto-detected from file)"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Add a resource to the vault."""
    vault = _get_vault(path)

    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    file_path = Path(file)
    if file_path.exists():
        source: str | Path = file_path
        display_name = name or file_path.name
    else:
        source = file
        display_name = name or "untitled.md"

    resource = vault.add(
        source,
        name=display_name,
        trust=trust,
        layer=layer,
        tags=tag_list,
    )

    console.print(f"[green]Added:[/green] {resource.name}")
    console.print(f"  ID: {resource.id}")
    console.print(f"  Trust: {resource.trust_tier.value if hasattr(resource.trust_tier, 'value') else resource.trust_tier}")
    console.print(f"  Chunks: {resource.chunk_count}")
    console.print(f"  CID: {resource.cid}")


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    top_k: int = typer.Option(10, "--top-k", "-k", help="Maximum results"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Search the vault with trust-weighted hybrid search."""
    vault = _get_vault(path)
    results = vault.search(query, top_k=top_k)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search: \"{query}\" ({len(results)} results)")
    table.add_column("#", style="dim", width=3)
    table.add_column("Trust", width=10)
    table.add_column("Resource", width=30)
    table.add_column("Relevance", width=10)
    table.add_column("Content", width=60)

    r: Any
    for i, r in enumerate(results, 1):
        tier = r.trust_tier.value if hasattr(r.trust_tier, "value") else str(r.trust_tier)
        tier_color = {
            "canonical": "green",
            "working": "blue",
            "ephemeral": "yellow",
            "archived": "dim",
        }.get(tier, "white")

        content_preview = r.content[:80].replace("\n", " ")
        if len(r.content) > 80:
            content_preview += "..."

        table.add_row(
            str(i),
            f"[{tier_color}]{tier}[/{tier_color}]",
            r.resource_name,
            f"{r.relevance:.3f}",
            content_preview,
        )

    console.print(table)


@app.command()
def inspect(
    resource_id: str = typer.Argument(..., help="Resource ID to inspect"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Inspect a resource's details."""
    vault = _get_vault(path)

    try:
        resource = vault.get(resource_id)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None

    console.print(f"[bold]{resource.name}[/bold]")
    console.print()

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Key", style="dim", width=20)
    table.add_column("Value")

    trust = resource.trust_tier.value if hasattr(resource.trust_tier, "value") else str(resource.trust_tier)
    status = resource.status.value if hasattr(resource.status, "value") else str(resource.status)
    lifecycle = resource.lifecycle.value if hasattr(resource.lifecycle, "value") else str(resource.lifecycle)

    table.add_row("ID", resource.id)
    table.add_row("CID", resource.cid)
    table.add_row("Content Hash", resource.content_hash)
    table.add_row("Trust Tier", trust)
    table.add_row("Status", status)
    table.add_row("Lifecycle", lifecycle)
    table.add_row("Chunks", str(resource.chunk_count))
    table.add_row("Size", f"{resource.size_bytes:,} bytes")
    if resource.mime_type:
        table.add_row("MIME Type", resource.mime_type)
    if resource.layer:
        layer = resource.layer.value if hasattr(resource.layer, "value") else str(resource.layer)
        table.add_row("Layer", layer)
    if resource.tags:
        table.add_row("Tags", ", ".join(resource.tags))
    table.add_row("Created", str(resource.created_at))
    table.add_row("Updated", str(resource.updated_at))
    if resource.indexed_at:
        table.add_row("Indexed", str(resource.indexed_at))

    console.print(table)


@app.command()
def status(
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Show vault status summary."""
    vault = _get_vault(path)
    s = vault.status()

    console.print(f"[bold]Vault Status[/bold]  ({s['vault_path']})")
    console.print()
    console.print(f"  Total resources: [bold]{s['total_resources']}[/bold]")
    console.print()

    if s["by_trust_tier"]:
        console.print("  [dim]By trust tier:[/dim]")
        for tier, count in sorted(s["by_trust_tier"].items()):
            console.print(f"    {tier}: {count}")

    if s["by_status"]:
        console.print("  [dim]By status:[/dim]")
        for st, count in sorted(s["by_status"].items()):
            console.print(f"    {st}: {count}")

    if s.get("by_layer"):
        console.print("  [dim]By layer:[/dim]")
        for layer, count in sorted(s["by_layer"].items()):
            console.print(f"    {layer}: {count}")


@app.command()
def verify(
    resource_id: str | None = typer.Argument(None, help="Resource ID (omit for full vault)"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Verify integrity of a resource or the entire vault."""
    vault = _get_vault(path)

    if resource_id:
        from qp_vault.models import VerificationResult
        r = vault.verify(resource_id)
        if not isinstance(r, VerificationResult):
            console.print("[red]Unexpected verification result type[/red]")
            raise typer.Exit(1)
        if r.passed:
            console.print(f"[green]PASS[/green]  {resource_id}")
            console.print(f"  Hash: {r.stored_hash}")
            console.print(f"  Chunks verified: {r.chunk_count}")
        else:
            console.print(f"[red]FAIL[/red]  {resource_id}")
            console.print(f"  Stored:   {r.stored_hash}")
            console.print(f"  Computed: {r.computed_hash}")
            if r.failed_chunks:
                console.print(f"  Failed chunks: {len(r.failed_chunks)}")
            raise typer.Exit(1)
    else:
        from qp_vault.models import VaultVerificationResult
        vr = vault.verify()
        if not isinstance(vr, VaultVerificationResult):
            console.print("[red]Unexpected verification result type[/red]")
            raise typer.Exit(1)
        if vr.passed:
            console.print("[green]PASS[/green]  Vault integrity verified")
            console.print(f"  Resources: {vr.resource_count}")
            console.print(f"  Merkle root: {vr.merkle_root}")
            console.print(f"  Duration: {vr.duration_ms}ms")
        else:
            console.print("[red]FAIL[/red]  Vault integrity check failed")
            console.print(f"  Failed: {len(vr.failed_resources)} resources")
            raise typer.Exit(1)


@app.command()
def health(
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Show vault health score."""
    vault = _get_vault(path)
    score = vault.health()
    console.print(f"[bold]Health Score: {score.overall}/100[/bold]")
    console.print(f"  Freshness:    {score.freshness}")
    console.print(f"  Uniqueness:   {score.uniqueness}")
    console.print(f"  Coherence:    {score.coherence}")
    console.print(f"  Connectivity: {score.connectivity}")
    console.print(f"  Issues:       {score.issue_count}")


@app.command(name="list")
def list_resources(
    trust: str | None = typer.Option(None, "--trust", "-t", help="Filter by trust tier"),
    layer: str | None = typer.Option(None, "--layer", "-l", help="Filter by layer"),
    tenant: str | None = typer.Option(None, "--tenant", help="Filter by tenant_id"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """List resources in the vault."""
    vault = _get_vault(path)
    resources = vault.list(trust=trust, layer=layer, tenant_id=tenant, limit=limit)

    if not resources:
        console.print("[yellow]No resources found.[/yellow]")
        return

    table = Table(title=f"{len(resources)} resources")
    table.add_column("Trust", width=10)
    table.add_column("Name", width=30)
    table.add_column("Status", width=10)
    table.add_column("ID", width=36, style="dim")

    for r in resources:
        tier = r.trust_tier.value if hasattr(r.trust_tier, "value") else str(r.trust_tier)
        st = r.status.value if hasattr(r.status, "value") else str(r.status)
        table.add_row(tier, r.name, st, r.id)

    console.print(table)


@app.command()
def delete(
    resource_id: str = typer.Argument(..., help="Resource ID to delete"),
    hard: bool = typer.Option(False, "--hard", help="Permanently delete"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Delete a resource."""
    vault = _get_vault(path)
    vault.delete(resource_id, hard=hard)
    mode = "permanently deleted" if hard else "soft-deleted"
    console.print(f"[green]{mode}[/green]  {resource_id}")


@app.command()
def transition(
    resource_id: str = typer.Argument(..., help="Resource ID"),
    target: str = typer.Argument(..., help="Target lifecycle state"),
    reason: str | None = typer.Option(None, "--reason", "-r", help="Reason"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Transition a resource's lifecycle state."""
    vault = _get_vault(path)
    try:
        r = vault.transition(resource_id, target, reason=reason)
        lc = r.lifecycle.value if hasattr(r.lifecycle, "value") else str(r.lifecycle)
        console.print(f"[green]Transitioned[/green]  {resource_id} -> {lc}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


@app.command()
def expiring(
    days: int = typer.Option(90, "--days", "-d", help="Days ahead to check"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Show resources expiring within N days."""
    vault = _get_vault(path)
    resources: list[Any] = vault.expiring(days=days)

    if not resources:
        console.print(f"[green]No resources expiring within {days} days.[/green]")
        return

    for r in resources:
        console.print(f"  {r.name}  expires {r.valid_until}")


@app.command()
def content(
    resource_id: str = typer.Argument(..., help="Resource ID"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Retrieve the full text content of a resource."""
    vault = _get_vault(path)
    try:
        text = vault.get_content(resource_id)
        console.print(text)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1) from None


@app.command()
def replace(
    resource_id: str = typer.Argument(..., help="Resource ID to replace"),
    file: str = typer.Argument(..., help="New content (file path or text)"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Replace a resource's content (creates new version, supersedes old)."""
    vault = _get_vault(path)
    file_path = Path(file)
    new_content = file_path.read_text() if file_path.exists() else file
    old, new = vault.replace(resource_id, new_content)
    console.print(f"[green]Replaced[/green]  {old.name}")
    console.print(f"  Old: {old.id} -> SUPERSEDED")
    console.print(f"  New: {new.id}")


@app.command()
def supersede(
    old_id: str = typer.Argument(..., help="Old resource ID"),
    new_id: str = typer.Argument(..., help="New resource ID"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Supersede a resource with a newer version."""
    vault = _get_vault(path)
    old, new = vault.supersede(old_id, new_id)
    console.print(f"[green]Superseded[/green]  {old.name} -> {new.name}")


@app.command()
def collections(
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """List all collections."""
    vault = _get_vault(path)
    colls: list[dict[str, Any]] = vault.list_collections()
    if not colls:
        console.print("[yellow]No collections.[/yellow]")
        return
    for c in colls:
        console.print(f"  {c.get('name', '?')}  ({c.get('id', '?')})")


@app.command()
def provenance(
    resource_id: str = typer.Argument(..., help="Resource ID"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Show provenance records for a resource."""
    vault = _get_vault(path)
    records: list[dict[str, Any]] = vault.get_provenance(resource_id)
    if not records:
        console.print("[yellow]No provenance records.[/yellow]")
        return
    for r in records:
        console.print(f"  {r.get('created_at', '?')}  by {r.get('uploader_id', 'unknown')}  via {r.get('upload_method', '?')}")


@app.command(name="export")
def export_vault(
    output: str = typer.Argument(..., help="Output file path"),
    path: str | None = typer.Option(None, "--path", "-p", help="Vault path"),
) -> None:
    """Export vault to a JSON file."""
    vault = _get_vault(path)
    import asyncio
    result = asyncio.run(vault._async.export_vault(output))
    console.print(f"[green]Exported[/green]  {result['resource_count']} resources to {result['path']}")


if __name__ == "__main__":
    app()
