# dalboe-open-data

**The method by which DALBOE derives a product database from Open Food
Facts**, published under ODbL §4.6(b) — which allows a Derivative
Database to be offered either as the data or as *"a file containing all
of the alterations made to the Database or the method of making the
alterations to the Database (such as an algorithm)"*. This repository is
that method.

Generated from the DALBOE service source at commit `a0afba1` on 2026-10-07
(America/Chicago). Nothing here is hand-written; see
`scripts/make_open_data_repo.py` in the service repository.

## Source

https://openfoodfacts-ds.s3.eu-west-3.amazonaws.com/en.openfoodfacts.org.products.csv.gz

A single continuously updated file rather than a series of dated
releases. Anyone following this method later will fetch different data
and arrive at a different row count; that is the nature of the source.

## The alterations

Rows are taken from the Open Food Facts CSV export and changed as follows before storage:
  * filtered by country: a row is kept when its `countries_tags` carry the country each import run above names. **Products sold in other countries as well are kept** — the filter asks whether a product is sold there, not whether it is sold ONLY there. `countries_tags` is Open Food Facts' own contributor-supplied field; this service reproduces that tagging and does not verify where a product is actually sold;
  * the barcode is normalised to a 14-digit GTIN with a verified check digit (normalise_gtin); rows whose code is not a valid GTIN-8/12/13/14 are dropped;
  * eight-digit codes that read as BOTH a UPC-E and a GTIN-8 are dropped rather than guessed, because the export does not record which symbol was scanned;
  * the product name is required; rows without one are dropped;
  * where an import run sets a minimum scan count, rows whose `unique_scans_n` is below it, or absent, are dropped. No run has used this so far;
  * after normalising, a GTIN already seen in the same run is dropped and the FIRST row in export order is kept. A UPC-E and its expanded UPC-A are two rows in the export that normalise to one key, which is the point of normalising;
  * only the FIRST comma-separated entry of the `brands` field is kept, and it is stored as a brand, never as a manufacturer;
  * no other OFF field is imported. Nutrition, ingredients, categories, labels, images and contributor metadata are not read.
Nothing in the export is edited in place: each row is stored under its own source key, so an Open Food Facts value is never merged into, or overwritten by, a value from anywhere else.

The export is a single CONTINUOUSLY UPDATED file rather than a series of dated releases:
  https://openfoodfacts-ds.s3.eu-west-3.amazonaws.com/en.openfoodfacts.org.products.csv.gz
so anyone following this method later will fetch different data and arrive at a different row count. That is the nature of the source and not a discrepancy with the figures above — and it is why each import is stamped with the date it FETCHED rather than with a version. Where the size of the input is known it is stated with the import above, so a later reader can tell whether their copy is larger than the one these figures came from.

## Current figures

Row counts and the date of the import in production are published at
https://dalboe.app/open-data.html, and are generated from the live database rather than maintained
by hand. They are deliberately not duplicated here: one number, one
place.

## What is in this repository

    method/barcodes.py          GTIN normalisation and UPC-E expansion
    method/openfoodfacts.py     one OFF row -> one stored value
    method/import_off_dump.py   the streaming importer and its filters

The barcode rules are included rather than described because they are
part of the method: a code that normalises differently selects different
rows.

**What is deliberately absent**: user data, model output, the owned
category catalogue, infrastructure, configuration and secrets. The
repository boundary is the ODbL boundary.

`method/import_off_dump.py` imports from the service and is published to
be read and audited rather than to run unmodified; `barcodes.py` and
`openfoodfacts.py` carry the transform itself.

## Attribution

Contains data from Open Food Facts, available under the Open Database License.

Licence: Open Data Commons Open Database License (ODbL) v1.0
https://opendatacommons.org/licenses/odbl/1-0/

Data produced by this method is ODbL and carries the credit above. See
`DATA-LICENSE.md`.

## Licences

The **code** in this repository is MIT (`LICENSE`). The **data** it
produces is ODbL (`DATA-LICENSE.md`). They are different licences for
different things, which is why they are separate files.

## Contact

hello@dalboe.app
