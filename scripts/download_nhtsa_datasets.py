"""Download all NHTSA datasets and APIs reference files into data/raw/.

Mirrors what's listed on https://www.nhtsa.gov/nhtsa-datasets-and-apis except
for files larger than the size cap (default 150 MB) — by default the only
files that get skipped are FLAT_CMPL.zip (~346 MB, redundant with the
5-year COMPLAINTS_RECEIVED zips) and Recall_Communications.pdf (~179 MB,
not used by the pipeline). Override with --max-mb if you want everything.

    python scripts/download_nhtsa_datasets.py            # default skip-large
    python scripts/download_nhtsa_datasets.py --max-mb 500
    python scripts/download_nhtsa_datasets.py --include-all
    python scripts/download_nhtsa_datasets.py --force    # re-download existing
"""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TARGET_DIR = PROJECT_ROOT / "data" / "raw"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# (url, approx_mb) — order: small docs first, then progressively larger.
DATASETS: list[tuple[str, float]] = [
    # Data dictionaries / readmes — tiny but essential
    ("https://static.nhtsa.gov/odi/ffdd/cmpl/CMPL.txt", 0.01),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/RCL.txt", 0.003),
    ("https://static.nhtsa.gov/odi/ffdd/inv/INV.txt", 0.002),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/TSBS.txt", 0.006),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/RCL_Annual_Rpts.txt", 0.002),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/RCL_Qtrly_Rpts.txt", 0.001),
    ("https://static.nhtsa.gov/nhtsa/downloads/Safercar/Safercar_data_READ_ME_file.txt", 0.014),

    # Import instructions PDFs
    ("https://static.nhtsa.gov/odi/ffdd/cmpl/Import_Instructions_Excel_All.pdf", 0.672),
    ("https://static.nhtsa.gov/odi/ffdd/cmpl/Import_Instructions_Excel_5-year.pdf", 0.604),
    ("https://static.nhtsa.gov/odi/ffdd/cmpl/Import_Instructions_Access.pdf", 0.973),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/Import_Instructions_Recalls.pdf", 1.006),

    # Ratings (NCAP)
    ("https://static.nhtsa.gov/nhtsa/downloads/Safercar/Safercar_data.csv", 9),

    # Recall annual / quarterly summary zips (small)
    ("https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_Annual_Rpts.zip", 0.154),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_Qrtly_Rpts.zip", 1),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/RCL_FROM_2000_2004.zip", 0.001),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/RCL_FROM_2005_2009.zip", 0.004),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/RCL_FROM_2010_2014.zip", 0.111),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/RCL_FROM_2025_2025.zip", 0.089),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/RCL_FROM_2025_2026.zip", 0.090),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/RCL_FROM_2015_2019.zip", 6),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/RCL_FROM_2020_2024.zip", 4),

    # Recalls (full bulk)
    ("https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_PRE_2010.zip", 7),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/FLAT_RCL_POST_2010.zip", 14),

    # Investigations
    ("https://static.nhtsa.gov/odi/ffdd/inv/FLAT_INV.zip", 4),

    # Complaints — 5-year partitions (cover all years; total ~346 MB)
    ("https://static.nhtsa.gov/odi/ffdd/cmpl/COMPLAINTS_RECEIVED_1995-1999.zip", 14),
    ("https://static.nhtsa.gov/odi/ffdd/cmpl/COMPLAINTS_RECEIVED_2000-2004.zip", 40),
    ("https://static.nhtsa.gov/odi/ffdd/cmpl/COMPLAINTS_RECEIVED_2005-2009.zip", 44),
    ("https://static.nhtsa.gov/odi/ffdd/cmpl/COMPLAINTS_RECEIVED_2010-2014.zip", 69),
    ("https://static.nhtsa.gov/odi/ffdd/cmpl/COMPLAINTS_RECEIVED_2015-2019.zip", 78),
    ("https://static.nhtsa.gov/odi/ffdd/cmpl/COMPLAINTS_RECEIVED_2020-2024.zip", 72),
    ("https://static.nhtsa.gov/odi/ffdd/cmpl/COMPLAINTS_RECEIVED_2025-2026.zip", 29),

    # Manufacturer Communications + TSBs (Phase 2)
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/MFR_COMMS_RECEIVED_1995-1999.zip", 0.631),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/MFR_COMMS_RECEIVED_2000-2004.zip", 2),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/MFR_COMMS_RECEIVED_2005-2009.zip", 0.884),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/MFR_COMMS_RECEIVED_2010-2014.zip", 2),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/MFR_COMMS_RECEIVED_2015-2019.zip", 12),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/MFR_COMMS_RECEIVED_2020-2024.zip", 11),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/MFR_COMMS_RECEIVED_2025-2025.zip", 3),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/MFR_COMMS_RECEIVED_2025-2026.zip", 4),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/TSBS_RECEIVED_1995-1999.zip", 1),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/TSBS_RECEIVED_2000-2004.zip", 3),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/TSBS_RECEIVED_2005-2009.zip", 2),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/TSBS_RECEIVED_2010-2014.zip", 4),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/TSBS_RECEIVED_2015-2019.zip", 31),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/TSBS_RECEIVED_2020-2024.zip", 30),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/TSBS_RECEIVED_2025-2025.zip", 6),
    ("https://static.nhtsa.gov/odi/ffdd/tsbs/TSBS_RECEIVED_2025-2026.zip", 9),

    # Headliners over 150 MB — only fetched with --include-all or --max-mb large
    ("https://static.nhtsa.gov/odi/ffdd/cmpl/FLAT_CMPL.zip", 346),
    ("https://static.nhtsa.gov/odi/ffdd/rcl/Recall_Communications.pdf", 179),
]


def _download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        tmp = dest.with_suffix(dest.suffix + ".part")
        bytes_read = 0
        chunk = 1 << 16
        last_print = time.time()
        with open(tmp, "wb") as f:
            while True:
                buf = resp.read(chunk)
                if not buf:
                    break
                f.write(buf)
                bytes_read += len(buf)
                now = time.time()
                if total and now - last_print >= 0.5:
                    pct = bytes_read * 100 // total
                    print(
                        f"    ... {bytes_read/1_000_000:6.1f} / {total/1_000_000:6.1f} MB ({pct}%)",
                        end="\r",
                        flush=True,
                    )
                    last_print = now
        tmp.replace(dest)
        return bytes_read


@click.command()
@click.option("--max-mb", type=float, default=150.0, help="Skip files larger than this (MB).")
@click.option("--include-all", is_flag=True, help="Download every file, no size cap.")
@click.option("--force", is_flag=True, help="Re-download files that already exist.")
def main(max_mb: float, include_all: bool, force: bool) -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    cap = float("inf") if include_all else max_mb

    print(f"Target: {TARGET_DIR}")
    print(f"Cap:    {'none' if include_all else f'{cap:.0f} MB'}")
    print()

    skipped_size: list[tuple[str, float]] = []
    skipped_existing: list[str] = []
    downloaded: list[tuple[str, int]] = []
    failed: list[tuple[str, str]] = []

    for url, mb in DATASETS:
        name = url.rsplit("/", 1)[-1]
        dest = TARGET_DIR / name
        if mb > cap:
            skipped_size.append((name, mb))
            continue
        if dest.exists() and not force:
            skipped_existing.append(name)
            continue
        print(f"  {name} ({mb:.1f} MB)")
        try:
            n = _download(url, dest)
            downloaded.append((name, n))
            print(f"    done — {n/1_000_000:.1f} MB                                  ")
        except Exception as e:  # noqa: BLE001
            failed.append((name, str(e)))
            print(f"    FAILED: {e}")

    total_downloaded = sum(n for _, n in downloaded)
    print()
    print(f"Downloaded:  {len(downloaded)} files, {total_downloaded/1_000_000:.1f} MB total")
    if skipped_existing:
        print(f"Skipped (already present): {len(skipped_existing)}")
    if skipped_size:
        print(f"Skipped (over {cap:.0f} MB cap):")
        for name, mb in skipped_size:
            print(f"  - {name} ({mb:.0f} MB)  — re-run with --include-all to fetch")
    if failed:
        print("FAILED:")
        for name, err in failed:
            print(f"  - {name}: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
