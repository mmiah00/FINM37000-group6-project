"""
Validate FOMC alignment against actual SOFR futures settlement data.
"""

from pathlib import Path

import pandas as pd
import pytest

from fomc_data.alignment import align_fomc_with_futures


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"


def validate_alignment(aligned, fomc, expected_meetings = None):
    """
    Validate FOMC/futures alignment invariants for real or synthetic data.
    """
    assert not aligned.empty

    aligned = aligned.copy()
    fomc = fomc.copy()

    date_cols = ["trade_date", "meeting_date", "effective_date", "reference_start", "reference_end"]

    for col in date_cols:
        aligned[col] = pd.to_datetime(aligned[col])

    fomc["meeting_date"] = pd.to_datetime(fomc["meeting_date"])

    #all expected meetings must be represented.
    expected_dates = set(fomc["meeting_date"])

    if expected_meetings is not None:
        assert len(expected_dates) == expected_meetings

    #every expected FOMC meeting must be represented.
    assert set(aligned["meeting_date"]) == expected_dates

    #futures observations must precede FOMC announcements.
    assert (aligned["trade_date"] < aligned["meeting_date"]).all()

    #effective dates must lie within contract reference periods.
    assert ((aligned["effective_date"] >= aligned["reference_start"]) 
            & (aligned["effective_date"] <= aligned["reference_end"])).all()

    #no duplicate trade/contract/meeting combinations.
    assert not aligned.duplicated(["trade_date", "contract_id", "meeting_date"]).any()

    #effective dates must be populated.
    assert aligned["effective_date"].notna().all()

    #realized changes must match the source decisions.
    expected_changes = fomc.set_index("meeting_date")["change_bps"]
    actual_changes = aligned["meeting_date"].map(expected_changes)

    assert actual_changes.notna().all()
    assert (aligned["realized_change_bps"].to_numpy() == actual_changes.to_numpy()).all()

    #both futures products must appear.
    assert {"SR1", "SR3"}.issubset(set(aligned["root"]))


@pytest.fixture
def synthetic_fomc():
    """
    Synthetic hike, hold, and cut meetings, including a month-end boundary.
    """
    return pd.DataFrame([{"meeting_date": "2024-01-31",
                          "effective_date": "2024-02-01",
                          "target_lower_after": 5.25,
                          "target_upper_after": 5.50,
                          "change_bps": 25,
                          "decision": "hike"},
                         {"meeting_date": "2024-03-20",
                          "effective_date": None,
                          "target_lower_after": 5.25,
                          "target_upper_after": 5.50,
                          "change_bps": 0,
                          "decision": "hold"},
                         {"meeting_date": "2024-05-01",
                          "effective_date": "2024-05-02",
                          "target_lower_after": 5.00,
                          "target_upper_after": 5.25,
                          "change_bps": -25,
                          "decision": "cut"}])

@pytest.fixture
def synthetic_futures():
    """
    Synthetic SR1/SR3 contracts with multiple trade dates and reference periods.
    """
    rows = []

    contracts = [("SR1G4", "SR1", "2024-02-01", "2024-02-29"),
                 ("SR1H4", "SR1", "2024-03-01", "2024-03-31"),
                 ("SR1K4", "SR1", "2024-05-01", "2024-05-31"),
                 ("SR3H4", "SR3", "2024-03-20", "2024-06-19"),
                 ("SR3M4", "SR3", "2024-06-19", "2024-09-17")]

    trade_dates = ["2024-01-29", "2024-01-30", "2024-03-18", "2024-03-19", "2024-04-29", "2024-04-30", "2024-05-02",]

    for trade_date in trade_dates:
        for contract_id, root, start, end in contracts:
            rows.append({"trade_date": trade_date,
                         "contract_id": contract_id,
                         "root": root,
                         "reference_start": start,
                         "reference_end": end,
                         "settlement_price": 94.75})

    return pd.DataFrame(rows)


def test_fomc_sofr_integration():
    """
    Check that real futures settlements align with realized FOMC decisions.
    """
    futures_path = PROCESSED_DIR / "sofr_futures_settlements.parquet"
    fomc_path = PROCESSED_DIR / "fomc_meetings.csv"

    if not Path(futures_path).exists() or not Path(fomc_path).exists():
        pytest.skip("Processed futures or FOMC data not available")

    futures = pd.read_parquet(futures_path)
    fomc = pd.read_csv(fomc_path)

    aligned = align_fomc_with_futures(futures, fomc)

    validate_alignment(aligned, fomc, expected_meetings = 38)


def test_synthetic_alignment_multiple_meetings(synthetic_futures, synthetic_fomc):
    """
    Validate hike, hold, and cut alignment across SR1/SR3 contracts.
    """
    aligned = align_fomc_with_futures(synthetic_futures, synthetic_fomc)

    validate_alignment(aligned, synthetic_fomc, expected_meetings = 3)

    assert set(aligned["decision"]) == {"hike", "hold", "cut"}
    assert set(aligned["realized_change_bps"]) == {25, 0, -25}

    #the hold has no explicit effective date, so it uses the next business day.
    hold_rows = aligned[aligned["meeting_date"] == pd.Timestamp("2024-03-20")]

    assert not hold_rows.empty
    assert (hold_rows["effective_date"] == pd.Timestamp("2024-03-21")).all()


def test_synthetic_alignment_date_boundaries(synthetic_futures, synthetic_fomc):
    """
    Verify reference-window matching and exclusion of post-meeting trades.
    """
    aligned = align_fomc_with_futures(synthetic_futures, synthetic_fomc)

    #the January 31 hike takes effect February 1.
    january_rows = aligned[aligned["meeting_date"] == pd.Timestamp("2024-01-31")]

    assert not january_rows.empty
    assert "SR1G4" in set(january_rows["contract_id"])

    #the March hold uses March 21, inside the March SR1 contract.
    march_rows = aligned[aligned["meeting_date"] == pd.Timestamp("2024-03-20")]
    assert "SR1H4" in set(march_rows["contract_id"])

    #the May 2 observation must not forecast the May 1 meeting.
    may_rows = aligned[aligned["meeting_date"] == pd.Timestamp("2024-05-01")]
    assert (may_rows["trade_date"] < pd.Timestamp("2024-05-01")).all()

    #june SR3 contract does not cover the May 2 effective date.
    assert "SR3M4" not in set(may_rows["contract_id"])


def test_synthetic_alignment_expected_rows(synthetic_futures, synthetic_fomc):
    """
    Verify the exact expected trade/contract/meeting matches.
    """
    aligned = align_fomc_with_futures(synthetic_futures, synthetic_fomc)

    actual = set(zip(aligned["trade_date"], aligned["contract_id"], aligned["meeting_date"]))

    expected = {(pd.Timestamp("2024-01-29"), "SR1G4", pd.Timestamp("2024-01-31")),
                (pd.Timestamp("2024-01-30"), "SR1G4", pd.Timestamp("2024-01-31"))}

    #the expected January matches must appear.
    assert expected.issubset(actual)

    #no January meeting should match the March-only SR1 contract.
    assert not any(contract == "SR1H4" and meeting == pd.Timestamp("2024-01-31") for _, contract, meeting in actual)


def test_synthetic_duplicate_fomc_meetings(synthetic_futures, synthetic_fomc):
    """
    Duplicate meeting dates must raise an explicit validation error.
    """
    duplicate_fomc = pd.concat([synthetic_fomc, synthetic_fomc.iloc[[0]]], ignore_index = True)

    with pytest.raises(ValueError, match = "Duplicate FOMC meeting dates"):
        align_fomc_with_futures(synthetic_futures, duplicate_fomc)
