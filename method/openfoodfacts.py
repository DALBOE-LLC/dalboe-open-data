"""GENERATED FILE — do not edit here.

Copied from the DALBOE service source, app/openfoodfacts.py, at commit a0afba1,
on 2026-10-07 (America/Chicago), by scripts/make_open_data_repo.py.

Edits belong in the service; re-running the generator replaces this file.
"""

"""One Open Food Facts row -> one cache value. The rule, in one place.

**Why this is a module and not a function inside a script.** There are two
ways to take data out of Open Food Facts -- the paged search API and the
published bulk dumps -- and both of them need exactly this rule: which
codes are accepted, what counts as a name, which column is a brand and
which is not, and what the row says about its own licence. Writing it
twice is how the two copies come to disagree about what `brands` means,
and nothing would notice, because both would keep returning rows.

**LICENCE: the row lands in the segregated partition automatically**, and
that is the schema doing it rather than a script remembering to. Writing
under `source_key="openfoodfacts"` means `Licence.SHARE_ALIKE` and the
ODbL attribution come from the registry, `resolve(exclude_segregated=
True)` excludes it, and a row cannot exist without its notice. ODbL is
share-alike -- *"if you publicly use any adapted version of this database
you must also offer that adapted database under the ODbL"* -- so these
rows must stay separable from the owned corpus forever.

**PROVENANCE is AUTHORITATIVE, and the caveat is inside that name's own
definition.** A database keyed on the barcode answered, with no model in
the loop, so fabrication is not a failure mode available to it -- which
is what `AUTHORITATIVE` means, including its own words *"as good as its
source"*. Open Food Facts is volunteer-entered and has real error rates.
That is a different failure from a hallucination and the one the system
already handles: a person who corrects a row creates a `user` value that
outranks this one on both axes.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from app.product_cache import (BarcodeAmbiguous, BarcodeInvalid, CachedValue,
                               normalise_gtin)
from app.product_source import Provenance

#: The source key, which is also what pins the licence. Not a parameter.
SOURCE_KEY = "openfoodfacts"

#: The three fields any OFF reader must supply, under these names. The
#: dumps and the API spell some columns differently, so whichever reader
#: is in use maps its own column names onto these before calling in --
#: and a reader that gets it wrong fails on the first row rather than
#: skipping every row with a plausible-looking reason.
REQUIRED_FIELDS = ("code", "product_name", "brands")


#: The export this service reads. **Here rather than in the importer,
#: because the published method now CITES it** — a reader following the
#: method needs the exact file, and a URL that drifts out of step with the
#: paragraph describing it is the same class of bug as a filter drifting
#: out of step with its description.
DUMP_URL = ("https://openfoodfacts-ds.s3.eu-west-3.amazonaws.com/"
            "en.openfoodfacts.org.products.csv.gz")


def sold_in(countries_tags: Optional[str], country: Optional[str]) -> bool:
    """Is this row tagged as sold in `country`? Exact tag match.

    **The filter was a bare substring test and that is a real bug, not a
    tidy-up.** `country in (row.get("countries_tags") or "")` against a
    comma-joined tag string means a short value matches inside OTHER
    countries' names — measured 7 Oct 2026:

        --country us  matches  en:australia, en:austria, en:belarus,
                               en:cyprus, en:mauritius, en:russia

    `us` is an entirely plausible thing to type, and the result would be a
    corpus bearing no resemblance to US products while the Open Data page
    claimed it was one. The default `united-states` is long enough to be
    safe in practice (it would additionally admit
    `en:united-states-minor-outlying-islands`, which is US territory and
    so not a misstatement).

    **It matters more now than it did yesterday**: before the compliance
    report existed this was a filter, and a wrong filter produces a wrong
    corpus. Now the filter's description is a published claim, and a wrong
    filter produces a FALSE STATEMENT about what was taken.

    Accepts the country with or without the `en:` prefix, because the
    tags carry it and nobody typing `--country` should have to.
    """
    if not country:
        return True                       # no filter asked for
    tags = {t.strip() for t in (countries_tags or "").split(",") if t.strip()}
    wanted = country.strip()
    return wanted in tags or f"en:{wanted}" in tags


#: What an import run RECORDS ABOUT ITSELF, so the published description
#: can say what happened rather than what the tool is capable of.
#:
#: **The gap this closes, found 7 Oct 2026 while reading the first real
#: compliance report.** `source_version` held only `fetched-<date>`, so the
#: database could not say which country filter had run — and the published
#: paragraph had to hedge ("filtered to a single country WHERE THE IMPORTER
#: WAS GIVEN ONE"), which is a statement about the software rather than
#: about the data. On a page whose only job is to describe accurately what
#: was taken, that is the wrong tense.
#:
#: `;` separated so it stays one opaque string to everything that stores
#: it, and still parses. Nothing reads `source_version` for meaning today
#: — it is written, stored and read back — so extending the format breaks
#: nothing.
def import_stamp(fetched: str, *, country: Optional[str] = None,
                 min_scans: Optional[int] = None) -> str:
    """The value stored in `source_version` for every row of one run."""
    parts = [f"fetched-{fetched}"]
    parts.append(f"country={country.lower()}" if country else "country=all")
    if min_scans:
        parts.append(f"min_scans={min_scans}")
    return ";".join(parts)


#: Imports that ran BEFORE `import_stamp` existed, described by the person
#: who ran them.
#:
#: **Labelled as an attestation and not as a measurement, because that is
#: what it is.** The rows carry no record of their own filter; this is
#: James stating what he ran. The supporting evidence is real but local —
#: `probe-off-dump.json` in this repo records 3,593,131 rows skipped as
#: "other country" against 827,819 kept — and a file on a laptop is not
#: something the service can assert about itself.
#:
#: Nothing should be added here going forward. A new entry means an import
#: ran without recording its own parameters, which `import_stamp` now
#: prevents.
ATTESTED_IMPORTS = {
    "fetched-2026-10-05": "tagged in Open Food Facts as sold in the United "
                          "States, products also sold elsewhere included; "
                          "read from an export of 4,500,000 rows "
                          "(operator-attested; this run predates parameter "
                          "recording)",
}


def describe_import(source_version: Optional[str]) -> str:
    """One human line for a stored stamp: what was fetched, and filtered how."""
    raw = (source_version or "").strip()
    if not raw:
        return "unknown import (no version stamp on these rows)"

    bits = dict()
    fetched = None
    for part in raw.split(";"):
        if part.startswith("fetched-"):
            fetched = part[len("fetched-"):]
        elif "=" in part:
            key, _, value = part.partition("=")
            bits[key] = value

    country = bits.get("country")
    # The attestation replaces only the FILTER half. Dropping the fetch
    # date with it was a real regression, caught by a test asserting the
    # date appears -- and the date is part of the claim, because "which
    # export" is as much of the description as "which rows".
    attested = ATTESTED_IMPORTS.get(raw)
    # "sold in", never "only". The filter keeps a product tagged for this
    # country whether or not it is also sold elsewhere, so "US only" would
    # claim an exclusion that was never applied -- a materially different
    # statement on a page whose job is describing accurately what was taken.
    where = (attested if attested
             else "all countries" if country == "all"
             else f"tagged as sold in {country.upper()}" if country
             else "country filter not recorded")
    scans = f", minimum {bits['min_scans']} scans" if "min_scans" in bits else ""
    return f"export fetched {fetched or 'unknown'}: {where}{scans}"


#: **How the imported rows differ from Open Food Facts' own export — in
#: this file, next to the code that does it.**
#:
#: ODbL §4.6 lets a Derivative Database be published either as the data or
#: as "the method of making the alterations"; the method is what DALBOE
#: offers, so this text is a legally operative description rather than a
#: comment. It lives here because *a corrected filter with an uncorrected
#: description of it is the same bug* — change `off_row_to_value` below
#: and this paragraph is the next thing you read.
#:
#: Each line names the code that performs it, so a reader can check the
#: claim rather than trust it.
#: Where the method is published. **Verified reachable before it went into
#: the text**, because a URL in a §4.6(b) offer that 404s is the same
#: defect as the OFF record link that would have 404'd: the obligation is
#: to OFFER the method, and an offer nobody can follow is not one.
METHOD_REPO = "https://github.com/DALBOE-LLC/dalboe-open-data"


ALTERATIONS = (
    "Rows are taken from the Open Food Facts CSV export and changed as "
    "follows before storage:",
    "  * filtered by country: a row is kept when its `countries_tags` "
    "carry the country each import run above names. **Products sold in "
    "other countries as well are kept** — the filter asks whether a "
    "product is sold there, not whether it is sold ONLY there. "
    "`countries_tags` is Open Food Facts' own contributor-supplied "
    "field; this service reproduces that tagging and does not verify "
    "where a product is actually sold;",
    "  * the barcode is normalised to a 14-digit GTIN with a verified "
    "check digit (normalise_gtin); rows whose code is not a valid "
    "GTIN-8/12/13/14 are dropped;",
    "  * eight-digit codes that read as BOTH a UPC-E and a GTIN-8 are "
    "dropped rather than guessed, because the export does not record "
    "which symbol was scanned;",
    "  * the product name is required; rows without one are dropped;",
    "  * where an import run sets a minimum scan count, rows whose "
    "`unique_scans_n` is below it, or absent, are dropped. No run has "
    "used this so far;",
    "  * after normalising, a GTIN already seen in the same run is "
    "dropped and the FIRST row in export order is kept. A UPC-E and its "
    "expanded UPC-A are two rows in the export that normalise to one "
    "key, which is the point of normalising;",
    "  * only the FIRST comma-separated entry of the `brands` field is "
    "kept, and it is stored as a brand, never as a manufacturer;",
    "  * no other OFF field is imported. Nutrition, ingredients, "
    "categories, labels, images and contributor metadata are not read.",
    "Nothing in the export is edited in place: each row is stored under "
    "its own source key, so an Open Food Facts value is never merged "
    "into, or overwritten by, a value from anywhere else.",
    "",
    "The export is a single CONTINUOUSLY UPDATED file rather than a "
    "series of dated releases:",
    f"  {DUMP_URL}",
    "so anyone following this method later will fetch different data and "
    "arrive at a different row count. That is the nature of the source "
    "and not a discrepancy with the figures above — and it is why each "
    "import is stamped with the date it FETCHED rather than with a "
    "version. Where the size of the input is known it is stated with the "
    "import above, so a later reader can tell whether their copy is "
    "larger than the one these figures came from.",
)


def off_row_to_value(row: Mapping[str, Any], stamp: str
                     ) -> Tuple[Optional[CachedValue], Optional[str]]:
    """One OFF row -> one `CachedValue`, or a reason it was skipped.

    Returning the reason rather than silently dropping, because "we
    imported 41,000 of 50,000" is only actionable with a breakdown -- and
    a silent filter is how a bad rule survives. Each reason is counted
    and sampled by the caller.

    **A missing FIELD raises; a missing VALUE skips.** They are different
    failures and conflating them is the expensive mistake available here:
    if a renamed column arrived as an absent key, every row would skip
    with reason "no name" and a 100% skip rate would read as bad upstream
    data rather than as this code looking in the wrong place.
    """
    missing = [f for f in REQUIRED_FIELDS if f not in row]
    if missing:
        raise KeyError(
            f"this OFF reader is not supplying {missing}; map the source's "
            f"own column names onto {REQUIRED_FIELDS} before calling. "
            f"Got: {sorted(row)[:12]}")

    code = (row.get("code") or "").strip()
    name = (row.get("product_name") or "").strip()
    # `brands` is comma-separated and is the BRAND ON THE PACKAGE, not the
    # GS1 registrant. Those are different facts and the cache keeps them
    # in different columns -- measured: 038000138416 registers to
    # Kellogg's and says Pringles.
    brand = (row.get("brands") or "").split(",")[0].strip()

    if not name:
        return None, "no name"
    try:
        gtin = normalise_gtin(code)
    except BarcodeAmbiguous:
        # Eight digits that read as BOTH a UPC-E and a GTIN-8. OFF stores
        # the digits off the package and not the symbology, so there is
        # nothing here to break the tie with -- and guessing would write a
        # row for a product nobody scanned. Counted separately from bad
        # data because it is not bad data, and because the count is what
        # says whether resolving it is worth a second request per row.
        return None, "ambiguous 8-digit barcode"
    except BarcodeInvalid:
        # OFF holds internal codes and mistyped ones. A row keyed on a bad
        # barcode is a permanent wrong answer for whoever scans the real
        # one, so these are dropped rather than coerced.
        return None, "bad barcode"

    return CachedValue(
        gtin=gtin,
        source_key=SOURCE_KEY,
        product_name=name,
        brand=brand or None,
        # NOT set from `brands`: see above.
        manufacturer=None,
        provenance=Provenance.AUTHORITATIVE,
        # OFF is continuous rather than released, so the stamp is the date
        # the read ran. Honest about being a fetch date, not a version.
        # The caller composes this with `import_stamp`, so a run
        # records its own filters rather than only its date.
        source_version=stamp,
        # No model touched this.
        model=None,
    ), None
