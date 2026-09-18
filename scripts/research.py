"""CLI behind the `/investigate` Claude Code skill.

    python scripts/research.py candidates [--limit 15]
    python scripts/research.py show <cluster-id>
    python scripts/research.py save <cluster-id> --file addendum.md

Descrybe (Jim's legal-research connector) only works inside an interactive
Claude session, so the research itself happens in the skill; this script
just moves the cluster out of the DB and the finished addendum back in.
Whatever DATABASE_URL points at is the DB this touches.
"""
from __future__ import annotations

import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Complaint narratives carry characters the Windows console code page can't
# encode; never let a stray glyph abort the dossier.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from signalwarn import research


@click.group()
def cli() -> None:
    pass


@cli.command()
@click.option("--limit", type=int, default=15, show_default=True)
def candidates(limit: int) -> None:
    """CRITICAL/HOT clusters with no research addendum yet, best first."""
    rows = research.list_candidates(limit)
    if not rows:
        click.echo("No unresearched CRITICAL/HOT clusters.")
        return
    click.echo(
        f"{'id':>6}  {'class':<8} {'score':>5} {'cmpl':>5} {'inj':>3} {'dth':>3}"
        "  vehicle / component  [flags]  memo says"
    )
    for r in rows:
        year = "ALL" if r["is_multi_year"] or not r["model_year"] else str(r["model_year"])
        flag_bits = (
            ("R", r["recall_issued"]),
            ("P", r["nhtsa_investigation_open"]),
            ("F", r["class_action_filed"]),
        )
        flags = "".join(f for f, on in flag_bits if on)
        click.echo(
            f"{r['id']:>6}  {r['classification']:<8} {r['score']:>5} {r['complaint_count']:>5}"
            f" {r['injury_count']:>3} {r['death_count']:>3}"
            f"  {r['make']} {r['model']} {year} | {r['component']}  [{flags or '-'}]"
            f"  {r['recommended_action'] or 'no memo'}"
        )
    click.echo("\nflags: R recall | P NHTSA probe | F class action filed")


@cli.command()
@click.argument("cluster_id", type=int)
@click.option("--narratives", type=int, default=8, show_default=True)
def show(cluster_id: int, narratives: int) -> None:
    """Print the cluster dossier the skill researches from."""
    loaded = research.load_cluster(cluster_id, narratives=narratives)
    if loaded is None:
        raise click.ClickException(f"no cluster with id {cluster_id}")
    cluster, states, rows = loaded
    click.echo(research.format_show(cluster, states, rows))


@cli.command()
@click.argument("cluster_id", type=int)
@click.option(
    "--file",
    "path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
)
def save(cluster_id: int, path: Path) -> None:
    """Store a finished research addendum on the cluster row."""
    text = path.read_text(encoding="utf-8")
    try:
        research.save_research(cluster_id, text)
    except (ValueError, LookupError) as e:
        raise click.ClickException(str(e)) from e
    click.echo(f"Saved research addendum ({len(text.split())} words) to cluster {cluster_id}.")


if __name__ == "__main__":
    cli()
