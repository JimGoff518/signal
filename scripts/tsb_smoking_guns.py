"""Surface "smoking gun" mass-tort candidates by cross-referencing TSBs.

Mass tort theory: when a manufacturer issues a Technical Service Bulletin
(TSB) instructing dealers to fix a defect — but doesn't issue a public
recall — that's the strongest leading indicator that "they knew." Combine
that signal with rising consumer complaints and you have the litigation
roadmap that defense counsel will eventually have to defend against.

This script:
  1. Reads recent NHTSA TSB flat-file dumps from data/raw/.
  2. Builds an index of (make, model, year, component) → TSB count.
  3. Queries clusters in the DB and surfaces ones where:
       a) a matching TSB exists,
       b) no recall has been issued, and
       c) complaint volume + velocity meet the configured floor.

Output is a printed table — no DB writes. Phase 1 of the TSB workstream
in docs/SIGNAL_PLAN_AND_GOALS.md. Future iteration will persist the
TSB flag to the cluster row and add a scoring escalator.

Usage:
    python scripts/tsb_smoking_guns.py
    python scripts/tsb_smoking_guns.py --min-complaints 10 --limit 30
    python scripts/tsb_smoking_guns.py --tsb-zips data/raw/TSBS_RECEIVED_2020-2024.zip data/raw/TSBS_RECEIVED_2025-2026.zip
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import click

# NHTSA TSB summaries occasionally include embedded newlines or large blobs
# that blow past Python's default CSV field limit (128 KB). Bump it.
csv.field_size_limit(10 * 1024 * 1024)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from signalwarn.db import connection  # noqa: E402
from signalwarn.normalize import normalize_component  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "raw"

# Default — most recent two 5-year TSB zips. Covers most TSBs relevant to
# 2015+ tracked vehicles (older TSBs are less actionable for current torts).
DEFAULT_TSB_ZIPS = [
    DATA_DIR / "TSBS_RECEIVED_2020-2024.zip",
    DATA_DIR / "TSBS_RECEIVED_2025-2026.zip",
]

# Field positions in the post-May-2024 TSB flat file format. The 2020-2024
# zip mixes old and new formats; we read by *position* (1-indexed in the
# data dictionary, 0-indexed here) since TSV without headers.
F_NHTSA_ID = 0
F_TSB_DOC_ID = 3
F_COMM_DATE = 4
F_COMM_TYPE = 6
F_MAKE = 7
F_MODEL = 8
F_YEAR = 9
F_COMPONENTS = 10


def _iter_tsb_records(zip_paths: list[Path]):
    """Yield dict rows from one or more TSB zip files."""
    for zp in zip_paths:
        if not zp.exists():
            click.echo(f"  ! skipping missing file: {zp}", err=True)
            continue
        with zipfile.ZipFile(zp) as z:
            name = z.namelist()[0]
            with z.open(name) as f:
                # latin-1 is permissive for the dirty NHTSA exports.
                text = io.TextIOWrapper(f, encoding="latin-1", newline="")
                reader = csv.reader(text, delimiter="\t")
                for row in reader:
                    if len(row) < 14:
                        continue
                    yield {
                        "nhtsa_id": row[F_NHTSA_ID].strip(),
                        "tsb_doc_id": row[F_TSB_DOC_ID].strip(),
                        "comm_date": row[F_COMM_DATE].strip(),
                        "comm_type": row[F_COMM_TYPE].strip(),
                        "make": row[F_MAKE].strip().upper(),
                        "model": row[F_MODEL].strip().upper(),
                        "year": row[F_YEAR].strip(),
                        "components_raw": row[F_COMPONENTS].strip(),
                    }


def _build_tsb_index(zip_paths: list[Path]) -> dict[tuple[str, str, int | None, str], int]:
    """Build (make, model, year, normalized_component) → TSB count index.

    Year is int when parseable, None when "9999" (unknown). Components are
    comma-separated; we explode and normalize each.
    """
    index: dict[tuple[str, str, int | None, str], int] = defaultdict(int)
    seen_tsbs: set[str] = set()
    total_records = 0

    for rec in _iter_tsb_records(zip_paths):
        total_records += 1
        try:
            year_int: int | None = int(rec["year"]) if rec["year"] != "9999" else None
        except ValueError:
            year_int = None
        components = [c.strip() for c in rec["components_raw"].split(",") if c.strip()]
        if not components:
            components = [""]
        for comp in components:
            key = (rec["make"], rec["model"], year_int, normalize_component(comp))
            index[key] += 1
        seen_tsbs.add(rec["nhtsa_id"])

    click.echo(
        f"  Indexed {total_records:,} TSB records ({len(seen_tsbs):,} unique TSBs) "
        f"into {len(index):,} (make, model, year, component) keys."
    )
    return index


def _model_matches(cluster_model: str, tsb_model: str) -> bool:
    """Return True when a cluster's model lines up with a TSB model.

    NHTSA TSB models often have suffixes ("F-150 SUPERCREW") that don't appear
    on the complaint side. Match if either string starts with the other plus
    a space, or they're equal.
    """
    if not cluster_model or not tsb_model:
        return False
    a, b = cluster_model.upper(), tsb_model.upper()
    return a == b or a.startswith(b + " ") or b.startswith(a + " ")


@click.command()
@click.option(
    "--tsb-zips",
    multiple=True,
    type=click.Path(exists=True, path_type=Path),
    help=f"TSB zip files to read. Default: {[p.name for p in DEFAULT_TSB_ZIPS]}",
)
@click.option(
    "--min-complaints",
    type=int,
    default=10,
    help="Only surface clusters with at least this many complaints (default 10).",
)
@click.option(
    "--require-velocity",
    is_flag=True,
    default=True,
    help="Only surface clusters with non-zero 30-day complaint velocity (default True).",
)
@click.option("--limit", type=int, default=25, help="Max rows to print.")
def main(tsb_zips: tuple[Path, ...], min_complaints: int, require_velocity: bool, limit: int) -> None:
    zips = list(tsb_zips) or DEFAULT_TSB_ZIPS
    click.echo(f"Reading TSBs from: {[p.name for p in zips]}")
    tsb_index = _build_tsb_index(zips)

    click.echo("\nQuerying clusters with rising complaints + no recall…")
    where = ["complaint_count >= %s", "recall_issued = FALSE"]
    params: list = [min_complaints]
    if require_velocity:
        where.append("velocity_30d > 0")

    sql = f"""
        SELECT id, classification, score, complaint_count, injury_count, death_count,
               velocity_30d, velocity_7d,
               make, model, model_year, component,
               nhtsa_investigation_open
          FROM clusters
         WHERE {' AND '.join(where)}
         ORDER BY score DESC, complaint_count DESC
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        clusters = [dict(r) for r in cur.fetchall()]

    smoking_guns: list[dict] = []
    for c in clusters:
        cluster_make = (c["make"] or "").upper()
        cluster_model = (c["model"] or "").upper()
        cluster_component = (c["component"] or "").upper()

        # Match strategies:
        # (a) exact (make, model, year, component) hit
        # (b) cross-year hit when the cluster is multi-year (model_year IS NULL)
        # (c) prefix-model match (TSB model has trim suffix etc.)
        tsb_count = 0
        for (tm, tmodel, tyear, tcomp), count in tsb_index.items():
            if tm != cluster_make:
                continue
            if not _model_matches(cluster_model, tmodel):
                continue
            if tcomp != cluster_component:
                continue
            if c["model_year"] is not None and tyear is not None and c["model_year"] != tyear:
                continue
            tsb_count += count

        if tsb_count > 0:
            smoking_guns.append({**c, "tsb_count": tsb_count})

    smoking_guns.sort(key=lambda r: (r["tsb_count"], r["score"], r["complaint_count"]), reverse=True)
    smoking_guns = smoking_guns[:limit]

    if not smoking_guns:
        click.echo("\nNo smoking-gun candidates found at this threshold.")
        click.echo("Try lowering --min-complaints, dropping --require-velocity, or seeding more data.")
        return

    print()
    print("SMOKING-GUN CANDIDATES (TSB exists, no recall issued, rising complaints)")
    print("=" * 120)
    print(
        f"{'#':>3}  {'CLASS':8}  {'SCORE':>5}  {'TSBs':>4}  {'CX':>5}  {'INJ':>4}  {'DTH':>3}  "
        f"{'V30':>4}  {'INV':>3}  VEHICLE / COMPONENT"
    )
    print("-" * 120)
    for i, r in enumerate(smoking_guns, 1):
        year = str(r["model_year"]) if r["model_year"] else "multi-yr"
        veh = f"{r['make']} {r['model']} {year} / {r['component']}"
        inv = "Y" if r["nhtsa_investigation_open"] else "-"
        print(
            f"{i:>3}  {r['classification']:8}  {r['score']:>5}  {r['tsb_count']:>4}  "
            f"{r['complaint_count']:>5}  {r['injury_count']:>4}  {r['death_count']:>3}  "
            f"{r['velocity_30d']:>4}  {inv:>3}  {veh}"
        )
    print()
    print("Legend: TSBs=count of matching manufacturer communications in the index")
    print("        CX=complaints  INJ=injuries  DTH=deaths  V30=last-30d complaint count")
    print("        INV=NHTSA investigation open")
    print()


if __name__ == "__main__":
    main()
