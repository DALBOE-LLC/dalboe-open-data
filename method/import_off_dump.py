"""GENERATED FILE — do not edit here.

Copied from the DALBOE service source, scripts/import_off_dump.py, at commit a0afba1,
on 2026-10-07 (America/Chicago), by scripts/make_open_data_repo.py.

Edits belong in the service; re-running the generator replaces this file.
"""

"""Seed the product cache from Open Food Facts' bulk CSV export.

**Why the dump and not the API.** The paged search API throttles to a
standstill well before 500 requests -- measured 2 Oct 2026: ten clean
pages, then 503s, then a 401 on an endpoint that takes no credentials,
then nothing at all. OFF ask bulk users to take the published dumps, and
they are right. `import_openfoodfacts.py` remains the small-batch and
top-up tool; this is the seeder.

**Why the CSV and not the JSONL.** Measured, from their headers:

    en.openfoodfacts.org.products.csv.gz    1.28 GB   211 fields
    openfoodfacts-products.jsonl.gz        13.06 GB   332 fields

Ten times the download for fields this cache has no column for. The CSV
is named `.csv` and is **tab**-separated.

**On ranking, which is where the published documentation misled this
side.** `data-fields.txt` lists 150 fields and none of them is a
popularity or scan count, and that was taken at face value and written
down as "the CSV cannot be ranked". **The actual header has 211 fields
and two of them are `unique_scans_n` and `popularity_tags`.** The
documentation is behind the file. *Reading the docs instead of the
artifact is the same mistake as recalling instead of reading, and it
produced the same wrong answer.*

So ranking IS available -- and is still not the default, now for a
measured reason instead of a wrong one: **across the first 400,000 rows,
only 17% of US rows with a name carry `unique_scans_n` at all.** Ranking
on it means selecting from a sixth of the corpus and discarding the rest
unseen. `--min-scans` exists for anyone who wants it; the default takes
everything, because storage measured against the real schema is ~240
bytes a row -- all ~979,000 US products come to about 0.24 GB, and the
difference between that and a 50,000-row head is roughly five cents a
month, or four Gemini identify calls. *The thing this cache exists to
avoid costs four orders of magnitude more per unit than keeping the cache
does.*

**Nothing is written to disk.** The gzip is decompressed as it arrives
and rows are filtered on the way past, so the 1.28 GB never lands
anywhere. `--local` reads a file instead, for repeat runs.

**LICENCE and PROVENANCE are not this script's decision.** Both come from
`app.openfoodfacts.off_row_to_value`, which both OFF readers share so
they cannot drift: `source_key="openfoodfacts"` is the whole of it, and
the ODbL attribution and the segregated partition follow from the
registry.

**Writes are INSERT-IF-ABSENT** (`put_many`), so this is safe to run
against a live cache and safe to re-run. It cannot demote anybody's
correction because it never writes over anything.

Usage:

    python3 scripts/import_off_dump.py --dry-run --limit 50000
    python3 scripts/import_off_dump.py
    python3 scripts/import_off_dump.py --local products.csv.gz
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import io
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Settings                                  # noqa: E402
from app.openfoodfacts import (REQUIRED_FIELDS, import_stamp,  # noqa: E402
                               off_row_to_value, sold_in)
from app.product_cache import CachedValue                        # noqa: E402

# Imported rather than restated: the published method cites this URL, so a
# second copy here is a second thing to keep in step. See openfoodfacts.py.
from app.openfoodfacts import DUMP_URL  # noqa: E402
UA = "DALBOE/1.0 (inventory app; maxjman21@gmail.com)"

#: Tab. The file is named `.csv` and is not comma-separated; OFF's own
#: documentation says so and the header confirms it. Hard-coded rather
#: than sniffed because a wrong guess here yields ONE column containing
#: the whole line, every `product_name` empty, and a 100% skip rate that
#: reads as bad data. `inspect_off_dump.py` is where sniffing belongs.
DELIMITER = "\t"

#: The country filter runs on `countries_tags`, not `countries_en`, because
#: the tags are language-independent (`en:united-states`) while the
#: readable column is prose that varies.
COUNTRY_FIELD = "countries_tags"

#: Rows per write. The store chunks internally too; this bounds memory
#: and makes the progress line move at a human rate.
WRITE_BATCH = 2000

#: Rows between progress lines. A silent hour reads as a hang, and this
#: project has paid for that twice.
REPORT_EVERY = 100_000

CHECKPOINT = Path("probe-off-dump.json")

#: **Python's csv module refuses a field over 128 KB and OFF has fields
#: over 128 KB.** Found by running the whole export rather than a sample:
#: the stream died at row 2,003,528 of 4,789,118 with "field larger than
#: field limit (131072)", two thirds of the way through a four-minute
#: download. A `_csv.Error` is not a row this script can skip -- the
#: reader has already lost its place in the line -- so the limit is
#: raised rather than caught. 16 MB because `ingredients_text` and the
#: `_tags` columns on a heavily-edited product have no useful bound, and
#: a limit that exists to stop runaway memory is not doing that job at
#: 128 KB on a file this shape.
#:
#: Deliberately NOT `sys.maxsize`: a genuinely corrupt stream should
#: still fail rather than buffer until the machine dies.
CSV_FIELD_LIMIT = 16 * 1024 * 1024

#: Beyond REQUIRED_FIELDS. A header missing any of these means the export
#: changed shape, which is a stop rather than a filter that quietly
#: matches nothing.
NEEDED = (COUNTRY_FIELD, "unique_scans_n")


def open_rows(url: Optional[str], local: Optional[str]) -> TextIO:
    """A text stream of the dump, decompressed on the fly.

    Nothing is written to disk: the gzip is decoded as the bytes arrive
    and the rows are consumed as they are decoded, so peak usage is a
    buffer rather than 1.28 GB (or 13 GB decompressed).
    """
    if local:
        raw = gzip.open(local, "rb") if local.endswith(".gz") else open(local, "rb")
    else:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        raw = gzip.GzipFile(fileobj=urllib.request.urlopen(req, timeout=300))
    return io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")


def check_header(fieldnames: Optional[List[str]]) -> None:
    """Stop on a changed export rather than filtering everything away.

    The failure this prevents: a renamed column makes every row miss the
    country filter, the run reports "0 usable of 4,789,118", and that
    looks like the filter being too strict rather than like this code
    looking for a column that is no longer there.
    """
    if not fieldnames:
        raise SystemExit("the dump has no header row")
    missing = [f for f in list(REQUIRED_FIELDS) + list(NEEDED)
               if f not in fieldnames]
    if missing:
        raise SystemExit(
            f"the export no longer has {missing}. It has {len(fieldnames)} "
            f"fields; run scripts/inspect_off_dump.py and update this "
            f"script rather than loosening the check.")


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--country", default="united-states",
                    help="an exact countries_tags entry, with or without "
                         "the en: prefix; '' takes every country, which is "
                         "~4.8M rows and ~1.2 GB stored")
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after this many WRITTEN rows (0 = no limit)")
    ap.add_argument("--min-scans", type=int, default=0,
                    help="require unique_scans_n >= this. Off by default: "
                         "only ~17%% of US rows carry it at all, so this "
                         "selects from a sixth of the corpus")
    ap.add_argument("--local", help="read this file instead of downloading")
    ap.add_argument("--url", default=DUMP_URL)
    ap.add_argument("--dry-run", action="store_true",
                    help="stream and filter, write nothing")
    args = ap.parse_args()

    settings = Settings()
    if not args.dry_run and not settings.database_url:
        print("DALBOE_DATABASE_URL is not set; nothing to write to.",
              file=sys.stderr)
        return 2

    store = cache = None
    if not args.dry_run:
        from app.postgres import PostgresProductCache, PostgresUsageStore
        # A bulk tool opens its pool with its OWN timeout. The service's
        # 10 seconds is right for a phone and is what killed the first
        # catalogue seed -- one knob, two callers, again.
        store = await PostgresUsageStore.connect(settings.database_url,
                                                 command_timeout=180.0)
        cache = PostgresProductCache(store.pool)

    # Records the run's own filters, not just its date, so the
    # compliance report can say what happened rather than what the
    # tool can do. See `openfoodfacts.import_stamp`.
    stamp = import_stamp(date.today().isoformat(),
                         country=args.country, min_scans=args.min_scans)
    print("Open Food Facts bulk export -> product cache")
    print(f"  source        {args.local or args.url}")
    print(f"  country       {args.country or 'ALL'}")
    print(f"  min scans     {args.min_scans or 'none (take everything)'}")
    print(f"  limit         {args.limit or 'none'}")
    print("  licence       ODbL, segregated partition, attribution per row")
    print(f"  writes        insert-if-absent"
          f"{' — DRY RUN, nothing written' if args.dry_run else ''}")
    print()

    seen = kept = inserted = 0
    skipped: Dict[str, int] = {}
    examples: Dict[str, List[str]] = {}
    batch: List[CachedValue] = []
    gtins: set = set()
    started = time.monotonic()
    stopped_early: Optional[str] = None

    def note(reason: str, row: Dict[str, Any]) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1
        # A handful of examples per reason, so a count can be EYEBALLED
        # rather than trusted. This is how UPC-E was found: the filter was
        # discarding 'Diet Coke' and nobody could see it.
        if len(examples.setdefault(reason, [])) < 5:
            examples[reason].append(
                f"{(row.get('code') or '')!r} "
                f"{(row.get('product_name') or '')[:30]!r}")

    csv.field_size_limit(CSV_FIELD_LIMIT)

    try:
        stream = open_rows(args.url, args.local)
        reader = csv.DictReader(stream, delimiter=DELIMITER)
        check_header(reader.fieldnames)
        print(f"  header ok: {len(reader.fieldnames)} fields\n")

        for row in reader:
            seen += 1
            # **Before any `continue`, deliberately.** The first version of
            # this sat at the BOTTOM of the loop, after four `continue`s,
            # so a milestone row that happened to be filtered out printed
            # nothing -- and with a ~60% keep rate that is a two-in-five
            # chance per milestone. It showed up as a log reading
            # 400,000 then 800,000 with 500/600/700 simply absent, twice,
            # identically. A progress counter gated on the thing it exists
            # to be independent of is the same one-condition-two-purposes
            # fault as everything else in this file's history, and the
            # checkpoint was riding on it too.
            if seen % REPORT_EVERY == 0:
                rate = seen / max(time.monotonic() - started, 1e-9)
                print(f"  {seen:,} rows read, {kept:,} kept, "
                      f"{inserted:,} written ({rate:,.0f} rows/s)")
                CHECKPOINT.write_text(json.dumps(
                    {"seen": seen, "kept": kept, "inserted": inserted,
                     "skipped": skipped, "stamp": stamp}, indent=1))
            # Exact tag match, not a substring test -- `--country us` used
            # to match en:australia, en:austria, en:belarus, en:cyprus,
            # en:mauritius and en:russia. See `openfoodfacts.sold_in`.
            if not sold_in(row.get(COUNTRY_FIELD), args.country):
                skipped["other country"] = skipped.get("other country", 0) + 1
                continue
            if args.min_scans:
                raw = (row.get("unique_scans_n") or "").strip()
                if not raw or int(float(raw)) < args.min_scans:
                    note("below --min-scans", row)
                    continue

            value, reason = off_row_to_value(row, stamp)
            if value is None:
                note(reason, row)
                continue
            if value.gtin in gtins:
                # The export has one row per product, but a UPC-E and its
                # expanded UPC-A are two rows that normalise to one key --
                # which is the point of normalising, and also means the
                # batch must not carry the same primary key twice.
                note("duplicate after normalising", row)
                continue
            gtins.add(value.gtin)
            batch.append(value)
            kept += 1

            if len(batch) >= WRITE_BATCH:
                if cache is not None:
                    inserted += await cache.put_many(batch)
                batch = []
            if args.limit and kept >= args.limit:
                break
    except Exception as exc:                                  # noqa: BLE001
        # **A partial seed is worth having and a traceback is not.** This
        # streams 1.28 GB; a connection dropped at 80% still gathered
        # hundreds of thousands of good rows, and the summary is the only
        # record of what the filters did.
        stopped_early = f"{type(exc).__name__}: {exc}"

    if batch and cache is not None:
        inserted += await cache.put_many(batch)

    print()
    if stopped_early is not None:
        print(f"  STOPPED EARLY: {stopped_early}")
        print("  everything below was collected before that and is good.")
        print()
    print(f"  rows read  {seen:,}")
    print(f"  kept       {kept:,}")
    print(f"  written    {inserted:,}"
          f"{' (dry run: 0)' if args.dry_run else ''}")
    for reason, n in sorted(skipped.items(), key=lambda kv: -kv[1]):
        print(f"  skipped    {n:,}  {reason}")
        for ex in examples.get(reason, []):
            print(f"               e.g. {ex}")
    if cache is not None:
        stats = await cache.stats()
        print(f"\n  cache now holds {stats.get('products', 0):,} products, "
              f"{stats.get('values', 0):,} values")
        print(f"  of which share-alike: "
              f"{stats.get('licence:share-alike', 0):,}")
    if store is not None:
        await store.aclose()
    return 1 if stopped_early is not None else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
