"""GENERATED FILE — do not edit here.

Copied from the DALBOE service source, app/product_cache.py and app/schemas.py, at commit 77d6438,
on 2026-10-07 (America/Chicago), by scripts/make_open_data_repo.py.

Edits belong in the service; re-running the generator replaces this file.
"""

from enum import Enum
from typing import Optional


class Symbology(str, Enum):
    """Which barcode SYMBOL a string of digits came off the package as.

    Only ever consulted at eight digits, and there it is not a nicety:
    58% of valid UPC-E codes are also valid GTIN-8 codes (measured, see
    `expand_upc_e`), so the digits alone cannot say. Every scanner knows
    the answer already -- iOS reports `.upce` and `.ean8` as distinct
    metadata object types -- so this is information being discarded
    rather than information nobody has.
    """

    UPC_E = "upce"
    GTIN_8 = "gtin8"


class BarcodeInvalid(ValueError):
    """Not a barcode this cache can key on.

    Raised rather than stored-as-given. A row keyed on a mistyped barcode
    is worse than a missing row: it is a permanent wrong answer for
    whoever scans the real one, and nothing will ever correct it because
    nothing knows it is wrong.
    """


class BarcodeAmbiguous(BarcodeInvalid):
    """Eight digits that read correctly as a UPC-E AND as a GTIN-8.

    Not a malformed code -- two well-formed codes, for two different
    products, wearing the same eight digits. Which one it is depends on
    the SYMBOL it was printed as, and that fact is not in the digits.
    Pass `symbology=` and this never arises.

    A subclass of `BarcodeInvalid` so every existing caller fails closed
    without being touched: the cache abstains, the importer skips.
    """

    def __init__(self, code: str, upc_a: str):
        self.code = code
        self.upc_a = upc_a
        super().__init__(
            f"{code!r} is a valid GTIN-8 and also a valid UPC-E for "
            f"{upc_a} -- two different products. Only the symbology can "
            f"tell them apart; pass symbology=Symbology.UPC_E or "
            f"Symbology.GTIN_8")


def gtin_check_digit(body: str) -> str:
    """The GS1 check digit for `body` (the code without its check digit).

    Weights alternate 3,1 from the RIGHT, which is what makes one function
    correct for GTIN-8, -12, -13 and -14 alike. Written right-to-left for
    exactly that reason: the left-to-right form needs a different parity
    per length, which is how a check-digit routine ends up correct for
    UPC-A and quietly wrong for EAN-13.
    """
    if not (body.isascii() and body.isdigit()):
        # **`isdigit()` alone is not the predicate `int()` uses, and the
        # gap is reachable from the wire.** `"²".isdigit()` is True while
        # `int("²")` raises, so a superscript anywhere but the final
        # position escaped this contract as a bare `ValueError` — past
        # `CacheSource.handles`, which catches only `BarcodeInvalid`,
        # aborting the whole resolver and putting the interpreter's own
        # `invalid literal for int() with base 10: '²'` on the wire as a
        # `message` field the client switches on.
        #
        # Found by the 5 Oct security fan-out. The report's example code
        # was wrong — it put the character in the check-digit position,
        # where the comparison catches it first — and the mechanism was
        # right at every other position. *Verifying a finding can confirm
        # it and correct it in the same minute.*
        #
        # A GTIN is ASCII digits. `isdecimal()` would also close the
        # superscript hole, and would still admit Arabic-Indic digits that
        # `int()` accepts and no scanner emits; `isascii()` says the
        # narrower, truer thing.
        raise BarcodeInvalid(f"not ASCII digits: {body!r}")
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return str((10 - (total % 10)) % 10)


def expand_upc_e(code: str) -> Optional[str]:
    """UPC-E (8 digits, compressed) -> the UPC-A it stands for, or None.

    **Found by looking at what an import filter was throwing away.** The
    Open Food Facts seed rejected ~1% of its rows as "bad barcode", and
    the examples were `'04965802' 'Diet Coke'` and `'01210806' 'Purified
    Drinking Water'` -- popular products, not junk data. They are UPC-E:
    the compressed eight-digit symbol printed on packages too small for a
    full UPC-A, which is to say cans and small bottles, which is to say a
    lot of what is in a house.

    `04965802` expands to `049000006582`, and `049000` is Coca-Cola's GS1
    company prefix. Treating these as GTIN-8 fails the check digit,
    because UPC-E's check digit belongs to the EXPANDED code -- so the
    naive reading rejects every one of them and the rejection looks like
    bad upstream data rather than a missing rule.

    The expansion is positional, keyed on the last body digit:

        last 0,1,2  ->  N d1 d2 d6 0 0 0 0 d3 d4 d5 C
        last 3      ->  N d1 d2 d3 0 0 0 0 0 d4 d5 C
        last 4      ->  N d1 d2 d3 d4 0 0 0 0 0 d5 C
        last 5..9   ->  N d1 d2 d3 d4 d5 0 0 0 0 d6 C

    Returns None rather than raising, so a caller can ask "is this a
    UPC-E?" without handling an exception to mean "no".

    **It does NOT answer "is this a UPC-E RATHER THAN a GTIN-8", and an
    earlier version of this comment claimed that it did.** The claim was
    that only one of the two readings could satisfy its own check digit,
    so choosing between them was a disambiguation rather than a guess.
    Enumerating all 20,000,000 eight-digit codes beginning 0 or 1 says
    otherwise:

        last body digit   valid UPC-E   also a valid GTIN-8
             0, 1, 2        200,000          40,000   ( 20%)
             3              200,000               0   (  0%)
             4              200,000          40,000   ( 20%)
             5 .. 9         200,000         200,000   (100%)

    **58% of valid UPC-E codes are also valid GTIN-8 codes**, and for a
    last body digit of 5-9 it is every single one. That is arithmetic
    rather than luck: the 5..9 branch inserts FOUR zeros, an even number,
    so every surviving digit keeps its 3-or-1 weight and the two check
    digits are sums of the same terms. A check digit cannot distinguish
    two readings it is identical under. (For a last body digit of 3 the
    collision is impossible for the mirror-image reason -- the difference
    between the two sums always comes out odd.)

    So eight digits with no stated symbology is genuinely undecidable,
    and `normalise_gtin` refuses instead of picking. See
    `BarcodeAmbiguous`.
    """
    if len(code) != 8 or not code.isdigit():
        return None
    n, body, check = code[0], code[1:7], code[7]
    if n not in "01":
        # UPC-E only defines number systems 0 and 1. Anything else is not
        # a compressed UPC and must not be expanded into a plausible one.
        return None
    d1, d2, d3, d4, d5, d6 = body
    if d6 in "012":
        digits = f"{n}{d1}{d2}{d6}0000{d3}{d4}{d5}"
    elif d6 == "3":
        digits = f"{n}{d1}{d2}{d3}00000{d4}{d5}"
    elif d6 == "4":
        digits = f"{n}{d1}{d2}{d3}{d4}00000{d5}"
    else:
        digits = f"{n}{d1}{d2}{d3}{d4}{d5}0000{d6}"
    if gtin_check_digit(digits) != check:
        # The expansion is only right if the check digit it implies
        # matches. A mismatch means this is not a UPC-E, so say so rather
        # than return a well-formed wrong barcode.
        return None
    return digits + check


def normalise_gtin(raw: Optional[str], *,
                   symbology: Optional[Symbology] = None) -> str:
    """Any GTIN-8/12/13/14 -> zero-padded GTIN-14, check digit verified.

    Verifying rather than trusting, because the client's barcode may have
    come from a camera in bad light. A scanner that drops a digit produces
    a string that is still all digits and still looks like a barcode.

    `symbology` is consulted only at eight digits, and is only needed
    there. Without it an eight-digit code is read as whichever of UPC-E
    and GTIN-8 it validly is -- and REFUSED with `BarcodeAmbiguous` when
    it is validly both, which is the common case rather than the corner
    one. Supplying it removes the question instead of answering it.
    """
    if raw is None:
        raise BarcodeInvalid("no barcode")
    # ASCII, for the reason in `gtin_check_digit`: a non-ASCII character
    # that `isdigit()` admits would be KEPT here and then fail inside
    # `int()`, which is how a bare ValueError reached the wire.
    digits = "".join(c for c in str(raw) if c.isascii() and c.isdigit())
    if len(digits) not in (8, 12, 13, 14):
        raise BarcodeInvalid(
            f"{raw!r} has {len(digits)} digits; expected a GTIN-8/12/13/14")

    if len(digits) == 8 and symbology is not Symbology.GTIN_8:
        expanded = expand_upc_e(digits)
        if symbology is Symbology.UPC_E:
            # The caller named the symbol, so a failure here is a real
            # failure and must not quietly fall through to the GTIN-8
            # reading -- that would key a row on a code the scanner never
            # saw, which is the one outcome this module exists to prevent.
            if expanded is None:
                raise BarcodeInvalid(
                    f"{raw!r} was declared UPC-E but does not expand to a "
                    f"UPC-A whose check digit matches")
            return expanded.rjust(GTIN_WIDTH, "0")
        if expanded is not None:
            if gtin_check_digit(digits[:-1]) == digits[-1]:
                raise BarcodeAmbiguous(digits, expanded)
            return expanded.rjust(GTIN_WIDTH, "0")

    expected = gtin_check_digit(digits[:-1])
    if digits[-1] != expected:
        raise BarcodeInvalid(
            f"{raw!r} fails its check digit (expected {expected}, got "
            f"{digits[-1]}) -- most likely a mistyped or misread code")
    return digits.rjust(GTIN_WIDTH, "0")


def off_record_url(gtin: str) -> Optional[str]:
    """The Open Food Facts product page for a GTIN we hold — or None.

    **This cannot be the stored GTIN with a prefix glued on, and that is
    the whole reason this function exists.** We normalise every barcode to
    14 digits. Open Food Facts normalises differently, and their rule is
    published: *"All barcodes with 7 digits or less (after leading 0s are
    removed) are padded with leading 0s so that they have 8 digits. All
    barcodes with 9 to 12 digits are padded with leading 0s so that they
    have 13 digits"*, while 14+ is kept as-is — and *"the `code` field in
    the product database, database dumps and exports is normalized in this
    way"* (openfoodfacts.github.io, barcode normalization reference, read
    7 Oct 2026).

    So the 12-digit UPC-A `038000138416` is `0038000138416` to them and
    `00038000138416` to us, and because they keep 14-digit codes as-is
    rather than shortening them, OUR form is a different code to their
    server. A link built from it would 404 — *which is worse than no link,
    because the obligation it exists to satisfy is attribution, and a
    broken credit is a credit nobody can follow.*

    This runs their rule on our digits: strip the padding we added, then
    re-pad the way they do.

    Returns None rather than a guess for anything that is not plain
    digits, on the same principle as everywhere else here: a link we are
    not sure of is not a link worth publishing.
    """
    digits = (gtin or "").strip()
    if not digits.isascii() or not digits.isdigit():
        return None
    bare = digits.lstrip("0")
    if not bare:
        return None
    if len(bare) <= 7:
        code = bare.rjust(8, "0")
    elif len(bare) <= 12:
        code = bare.rjust(13, "0")
    else:
        code = bare
    return f"https://world.openfoodfacts.org/product/{code}"


GTIN_WIDTH = 14
