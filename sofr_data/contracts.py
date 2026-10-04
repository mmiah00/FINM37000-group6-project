"""CME SOFR futures contract identifiers and settlement reference periods.

Two things are needed downstream and neither is in a Databento record as such:

1. A *stable* contract identifier. Databento gives raw CME symbols such as
   ``SR3H5``, whose one-digit year is ambiguous over a long sample. We turn
   those into ``SR3-2025-03``.
2. The *reference period* each contract settles against. The pricing model has
   to know which days of SOFR a contract averages or compounds over.

Conventions implemented (CME product specs):

- **SR1 (One-Month SOFR)** settles on the arithmetic average of daily SOFR over
  the *contract month*. Trading terminates on the last business day of that
  month, so the expiration month equals the contract month.
- **SR3 (Three-Month SOFR)** settles on compounded daily SOFR over a *reference
  quarter* running from the third Wednesday of the contract month up to, but
  not including, the third Wednesday three months later. Trading terminates at
  the end of that quarter, so the expiration month is the contract month plus
  three.

The second convention is the easy one to get backwards, so nothing here trusts
it blindly: `check_expiration_convention` re-derives the expiration month from
the symbol and the quality report counts how often that disagrees with the
exchange's own `expiration` field.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

MONTH_CODES: dict[str, int] = {
    "F": 1, "G": 2, "H": 3, "J": 4, "K": 5, "M": 6,
    "N": 7, "Q": 8, "U": 9, "V": 10, "X": 11, "Z": 12,
}
"""CME delivery-month letter codes."""

CODE_FOR_MONTH: dict[int, str] = {m: c for c, m in MONTH_CODES.items()}

EXPIRY_MONTH_OFFSET: dict[str, int] = {"SR1": 0, "SR3": 3}
"""Months from a contract's named month to the month trading terminates in."""

REFERENCE_MONTHS: dict[str, int] = {"SR1": 1, "SR3": 3}
"""Length of the settlement reference period, in months."""

_SYMBOL_RE = re.compile(
    rf"^(?P<root>SR1|SR3)(?P<code>[{''.join(MONTH_CODES)}])(?P<year>\d{{1,2}})$"
)


@dataclass(frozen=True)
class Contract:
    """One SOFR futures contract, identified by its named contract month."""

    root: str
    year: int
    month: int

    @property
    def contract_id(self) -> str:
        """Stable identifier, e.g. ``SR3-2025-03``."""
        return f"{self.root}-{self.year:04d}-{self.month:02d}"

    @property
    def contract_month_start(self) -> pd.Timestamp:
        """First calendar day of the named contract month."""
        return pd.Timestamp(year=self.year, month=self.month, day=1)

    @property
    def raw_symbol(self) -> str:
        """The CME raw symbol with a one-digit year, e.g. ``SR3H5``."""
        return f"{self.root}{CODE_FOR_MONTH[self.month]}{self.year % 10}"


def resolve_year(year_digits: str, anchor_year: int) -> int:
    """Expand a truncated CME year code to a full year.

    CME raw symbols carry only the last one or two digits of the year, so
    ``SR3H5`` could be 2005, 2015, 2025, ... We pick whichever candidate sits
    closest to `anchor_year`.

    Args:
        year_digits: The one- or two-digit year from the symbol.
        anchor_year: A year known to be near the contract, normally the year
            the contract expires in or the year it was observed trading.

    Returns:
        The resolved four-digit year.

    >>> resolve_year("5", 2025)
    2025
    >>> resolve_year("2", 2021)
    2022
    >>> resolve_year("9", 2021)
    2019
    >>> resolve_year("26", 2026)
    2026
    """
    modulus = 10 ** len(year_digits)
    target = int(year_digits)
    base = anchor_year - (anchor_year % modulus) + target
    candidates = (base - modulus, base, base + modulus)
    return min(candidates, key=lambda y: (abs(y - anchor_year), y))


def parse_raw_symbol(raw_symbol: str, anchor_year: int) -> Contract | None:
    """Parse a CME SOFR futures raw symbol into a `Contract`.

    Args:
        raw_symbol: A raw symbol such as ``SR1F2`` or ``SR3Z25``.
        anchor_year: Year used to disambiguate the truncated year code; see
            `resolve_year`.

    Returns:
        The parsed `Contract`, or `None` if `raw_symbol` is not an outright
        SR1/SR3 future. Spreads (``SR3H5-SR3M5``) and other products return
        `None` rather than raising, since the raw feed mixes them in.

    >>> parse_raw_symbol("SR3H5", 2025).contract_id
    'SR3-2025-03'
    >>> parse_raw_symbol("SR1F2", 2022).contract_id
    'SR1-2022-01'
    >>> parse_raw_symbol("SR3H5-SR3M5", 2025) is None
    True
    """
    match = _SYMBOL_RE.match(raw_symbol.strip().upper())
    if match is None:
        return None
    root = match.group("root")
    month = MONTH_CODES[match.group("code")]
    year = resolve_year(match.group("year"), anchor_year)
    return Contract(root=root, year=year, month=month)


def parse_from_expiration(raw_symbol: str, expiration: pd.Timestamp) -> Contract | None:
    """Parse a raw symbol, anchoring the year on the exchange expiration date.

    Using the expiration is more reliable than using the trade date, because
    SR3 contracts trade for several years before they expire.

    >>> parse_from_expiration("SR3Z4", pd.Timestamp("2025-03-18")).contract_id
    'SR3-2024-12'
    """
    if pd.isna(expiration):
        return None
    root_match = _SYMBOL_RE.match(raw_symbol.strip().upper())
    if root_match is None:
        return None
    # Step the anchor back from the expiration month to the contract month so
    # that an SR3 expiring in January is anchored on the prior year.
    offset = EXPIRY_MONTH_OFFSET[root_match.group("root")]
    anchor = pd.Timestamp(expiration).to_period("M") - offset
    return parse_raw_symbol(raw_symbol, anchor_year=anchor.year)


def third_wednesday(year: int, month: int) -> pd.Timestamp:
    """Return the third Wednesday of a month.

    >>> third_wednesday(2024, 12).date().isoformat()
    '2024-12-18'
    >>> third_wednesday(2025, 3).date().isoformat()
    '2025-03-19'
    """
    first = pd.Timestamp(year=year, month=month, day=1)
    # Monday=0 ... Wednesday=2.
    days_to_first_wed = (2 - first.dayofweek) % 7
    return first + pd.Timedelta(days=days_to_first_wed + 14)


def reference_period(contract: Contract) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the inclusive SOFR reference period a contract settles against.

    For SR1 this is the whole contract month. For SR3 it runs from the third
    Wednesday of the contract month through the day before the third Wednesday
    three months later.

    >>> c = parse_raw_symbol("SR1H4", 2024)
    >>> [d.date().isoformat() for d in reference_period(c)]
    ['2024-03-01', '2024-03-31']
    >>> c = parse_raw_symbol("SR3Z4", 2024)
    >>> [d.date().isoformat() for d in reference_period(c)]
    ['2024-12-18', '2025-03-18']
    """
    if contract.root == "SR1":
        start = contract.contract_month_start
        end = start + pd.offsets.MonthEnd(0)
        return start, end

    start = third_wednesday(contract.year, contract.month)
    end_month = contract.contract_month_start + pd.DateOffset(months=REFERENCE_MONTHS["SR3"])
    end = third_wednesday(end_month.year, end_month.month) - pd.Timedelta(days=1)
    return start, end


def implied_expiration_month(contract: Contract) -> pd.Period:
    """Month in which trading should terminate, per the documented convention.

    >>> str(implied_expiration_month(parse_raw_symbol("SR3Z4", 2024)))
    '2025-03'
    >>> str(implied_expiration_month(parse_raw_symbol("SR1H4", 2024)))
    '2024-03'
    """
    return contract.contract_month_start.to_period("M") + EXPIRY_MONTH_OFFSET[contract.root]
