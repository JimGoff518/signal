"""Surface the most likely mass-tort candidates in the DB.

The score column alone is misleading: a single complaint involving a death
becomes CRITICAL because of the +50 death escalator, even though one death
in isolation isn't a mass tort. This script ranks clusters by a combined
"tort signal" that weights both severity and volume.

    tort_signal = score * log10(complaint_count + 10)

That formula rewards clusters that are *both* severe and high-volume, and
heavily penalises single-incident severity flags. Result: the top of the
list is the actual list of cases worth reading viability memos for.

Usage:
    python scripts/top_clusters.py
    python scripts/top_clusters.py --limit 30
    python scripts/top_clusters.py --min-complaints 20
    python scripts/top_clusters.py --classification CRITICAL
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import click

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from signalwarn.db import connection  # noqa: E402


@click.command()
@click.option("--limit", type=int, default=20, help="How many rows to print.")
@click.option(
    "--min-complaints",
    type=int,
    default=5,
    help="Filter out clusters with fewer than this many complaints (default 5).",
)
@click.option(
    "--classification",
    type=click.Choice(["CRITICAL", "HOT", "WATCH", "MONITOR", "ALL"]),
    default="ALL",
    help="Restrict to one classification tier (default: HOT+CRITICAL only via tort signal).",
)
@click.option(
    "--by",
    type=click.Choice(["signal", "volume", "deaths", "velocity"]),
    default="signal",
    help="Ranking strategy.",
)
def main(limit: int, min_complaints: int, classification: str, by: str) -> None:
    rows = _fetch_rows(min_complaints, classification)
    if not rows:
        click.echo("No clusters match the filters.")
        return

    if by == "signal":
        for r in rows:
            r["tort_signal"] = round(r["score"] * math.log10(max(r["complaint_count"], 0) + 10), 1)
        rows.sort(key=lambda r: r["tort_signal"], reverse=True)
    elif by == "volume":
        rows.sort(key=lambda r: r["complaint_count"], reverse=True)
    elif by == "deaths":
        rows.sort(key=lambda r: (r["death_count"], r["score"]), reverse=True)
    elif by == "velocity":
        rows.sort(key=lambda r: (r["velocity_30d"], r["complaint_count"]), reverse=True)

    rows = rows[:limit]
    _print_table(rows, by)


def _fetch_rows(min_complaints: int, classification: str) -> list[dict]:
    where = ["complaint_count >= %s"]
    params: list = [min_complaints]
    if classification == "ALL":
        # Default = HOT+CRITICAL when ranking by tort signal; otherwise MONITOR+ to be useful.
        where.append("classification IN ('CRITICAL', 'HOT', 'WATCH', 'MONITOR')")
    else:
        where.append("classification = %s")
        params.append(classification)

    sql = f"""
        SELECT id, classification, score, complaint_count, injury_count, death_count,
               crash_count, fire_count, velocity_30d, velocity_7d,
               make, model, model_year, component,
               nhtsa_investigation_open, recall_issued
          FROM clusters
         WHERE {' AND '.join(where)}
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _print_table(rows: list[dict], by: str) -> None:
    by_label = {
        "signal": "RANKED BY TORT SIGNAL (score × log10(complaints+10))",
        "volume": "RANKED BY COMPLAINT VOLUME",
        "deaths": "RANKED BY DEATHS",
        "velocity": "RANKED BY 30-DAY VELOCITY",
    }[by]

    print()
    print(by_label)
    print("=" * 110)
    header = f"{'#':>3}  {'CLASS':8}  {'SCORE':>5}  {'CX':>5}  {'INJ':>4}  {'DTH':>3}  {'V30':>4}  {'FLAGS':5}  VEHICLE / COMPONENT"
    if by == "signal":
        header = f"{'#':>3}  {'CLASS':8}  {'SCORE':>5}  {'TORT':>5}  {'CX':>5}  {'INJ':>4}  {'DTH':>3}  {'V30':>4}  {'FLAGS':5}  VEHICLE / COMPONENT"
    print(header)
    print("-" * 110)

    for i, r in enumerate(rows, 1):
        flags = ""
        if r["nhtsa_investigation_open"]:
            flags += "I"
        if r["recall_issued"]:
            flags += "R"
        flags = flags or "-"
        year = str(r["model_year"]) if r["model_year"] else "multi-yr"
        veh = f"{r['make']} {r['model']} {year} / {r['component']}"

        if by == "signal":
            print(
                f"{i:>3}  {r['classification']:8}  {r['score']:>5}  {r.get('tort_signal', 0):>5}  "
                f"{r['complaint_count']:>5}  {r['injury_count']:>4}  {r['death_count']:>3}  "
                f"{r['velocity_30d']:>4}  {flags:5}  {veh}"
            )
        else:
            print(
                f"{i:>3}  {r['classification']:8}  {r['score']:>5}  "
                f"{r['complaint_count']:>5}  {r['injury_count']:>4}  {r['death_count']:>3}  "
                f"{r['velocity_30d']:>4}  {flags:5}  {veh}"
            )

    print()
    print("Legend: CX=complaints  INJ=injuries  DTH=deaths  V30=last-30d complaint count")
    print("        FLAGS: I=NHTSA investigation open  R=recall issued")
    print()


if __name__ == "__main__":
    main()
