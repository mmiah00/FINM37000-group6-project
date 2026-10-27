"""
Tests for FOMC data collection, alignment, and daily SOFR validation.
"""

import pandas as pd
import pytest
from fomc_data.fomc_calendar import fetch_fomc_calendar
from fomc_data.clean import validate_fomc_decisions, validate_sofr
from fomc_data.alignment import align_fomc_with_futures


def test_fomc_calendar():
    """
    Check meeting dates are unique and chronologically ordered.
    """
    df = fetch_fomc_calendar()

    assert len(df) == 38
    assert df["meeting_date"].is_unique
    assert df["meeting_date"].is_monotonic_increasing
    assert df["meeting_date"].min() == pd.Timestamp("2022-01-26")
    assert df["meeting_date"].max() == pd.Timestamp("2026-09-16")


def test_valid_decision():
    """
    A correctly calculated 25 bp hike should pass validation.
    """
    df = pd.DataFrame([{"meeting_date": pd.Timestamp("2022-03-16"),
                        "target_lower_before": 0.00,
                        "target_upper_before": 0.25,
                        "target_lower_after": 0.25,
                        "target_upper_after": 0.50,
                        "change_bps": 25.0,
                        "decision": "hike",
                        "effective_date": pd.Timestamp("2022-03-17")}])

    result = validate_fomc_decisions(df)

    assert len(result) == 1
    assert result.iloc[0]["decision"] == "hike"


def test_invalid_rate_change():
    """
    An incorrectly calculated rate change should raise an error.
    """
    df = pd.DataFrame([{"meeting_date": pd.Timestamp("2022-03-16"),
                        "target_lower_before": 0.00,
                        "target_upper_before": 0.25,
                        "target_lower_after": 0.25,
                        "target_upper_after": 0.50,
                        "change_bps": 50.0, #this is incorrect: should be 25 bps
                        "decision": "hike",
                        "effective_date": pd.Timestamp("2022-03-17")}])

    with pytest.raises(ValueError, match = "Incorrect basis-point"):
        validate_fomc_decisions(df)



def test_align_fomc_with_futures():
    """
    Match only future FOMC meetings within a contract's reference period.
    """
    #example futures observations
    futures = pd.DataFrame([{"trade_date": "2024-03-01",
                             "contract_id": "SR1_MAR24",
                             "reference_start": "2024-03-01",
                             "reference_end": "2024-03-31",
                             "settlement_price": 94.70},
                            {"trade_date": "2024-03-01",
                             "contract_id": "SR1_APR24",
                             "reference_start": "2024-04-01",
                             "reference_end": "2024-04-30",
                             "settlement_price": 94.80}])

    #example FOMC meetings
    fomc = pd.DataFrame([{"meeting_date": "2024-03-20",
                          "target_lower_after": 5.25,
                          "target_upper_after": 5.50,
                          "change_bps": 0.0,
                          "decision": "hold"},
                        {"meeting_date": "2024-05-01",
                         "target_lower_after": 5.25,
                         "target_upper_after": 5.50,
                         "change_bps": 0.0,
                         "decision": "hold"}])

    aligned = align_fomc_with_futures(futures, fomc)

    #only March's contract contains the March 20 meeting.
    assert len(aligned) == 1

    row = aligned.iloc[0]

    assert row["contract_id"] == "SR1_MAR24"
    assert row["meeting_date"] == pd.Timestamp("2024-03-20")
    assert row["realized_target_midpoint"] == 5.375
    assert row["realized_change_bps"] == 0.0



def test_align_multiple_fomc_meetings():
    """
    Match multiple upcoming meetings to one futures reference period.
    """
    futures = pd.DataFrame([{"trade_date": "2024-03-01",
                             "contract_id": "SR3_EXAMPLE",
                             "reference_start": "2024-03-01",
                             "reference_end": "2024-06-30",
                             "settlement_price": 94.70}])

    fomc = pd.DataFrame([{"meeting_date": "2024-03-20",
                          "target_lower_after": 5.25,
                          "target_upper_after": 5.50,
                          "change_bps": 0.0,
                          "decision": "hold"},
                         {"meeting_date": "2024-05-01",
                          "target_lower_after": 5.25,
                          "target_upper_after": 5.50,
                          "change_bps": 0.0,
                          "decision": "hold"},
                         {"meeting_date": "2024-06-12",
                          "target_lower_after": 5.25,
                          "target_upper_after": 5.50,
                          "change_bps": 0.0,
                          "decision": "hold"},
                          {"meeting_date": "2024-07-31",
                           "target_lower_after": 5.25,
                           "target_upper_after": 5.50,
                           "change_bps": 0.0,
                           "decision": "hold"}])

    aligned = align_fomc_with_futures(futures, fomc)

    assert len(aligned) == 3

    assert aligned["meeting_date"].tolist() == [pd.Timestamp("2024-03-20"),
                                                pd.Timestamp("2024-05-01"),
                                                pd.Timestamp("2024-06-12")]

    assert (aligned["contract_id"] == "SR3_EXAMPLE").all()


def test_align_uses_effective_date_across_month_boundary():
    """
    A month-end announcement effective next month belongs to next month.
    """
    futures = pd.DataFrame([{"trade_date": "2024-01-30", 
                             "contract_id": "SR1_JAN24", 
                             "reference_start": "2024-01-01", 
                             "reference_end": "2024-01-31"},
                            {"trade_date": "2024-01-30", 
                             "contract_id": "SR1_FEB24",
                             "reference_start": "2024-02-01", 
                             "reference_end": "2024-02-29"}])
    fomc = pd.DataFrame([{"meeting_date": "2024-01-31", 
                          "effective_date": "2024-02-01",
                          "target_lower_after": 5.00, 
                          "target_upper_after": 5.25,
                          "change_bps": -25.0, 
                          "decision": "cut"}])

    aligned = align_fomc_with_futures(futures, fomc)

    assert aligned["contract_id"].tolist() == ["SR1_FEB24"]
    assert aligned.iloc[0]["effective_date"] == pd.Timestamp("2024-02-01")


def test_align_hold_falls_back_to_next_business_day():
    """
    A Friday hold uses Monday as the alignment date.
    """
    futures = pd.DataFrame([{"trade_date": "2024-03-28", 
                             "contract_id": "SR1_APR24", 
                             "reference_start": "2024-04-01", 
                             "reference_end": "2024-04-30"}])
    fomc = pd.DataFrame([{"meeting_date": "2024-03-29", 
                          "effective_date": pd.NaT, 
                          "target_lower_after": 5.25, 
                          "target_upper_after": 5.50,
                          "change_bps": 0.0, "decision": "hold"}])

    aligned = align_fomc_with_futures(futures, fomc)

    assert len(aligned) == 1
    assert aligned.iloc[0]["effective_date"] == pd.Timestamp("2024-04-01")


def test_valid_sofr():
    """
    Valid daily SOFR observations should pass validation and be sorted by date.
    """
    df = pd.DataFrame([{"date": "2024-01-03", "sofr": 5.33},
                       {"date": "2024-01-02", "sofr": 5.31}])

    result = validate_sofr(df)

    assert len(result) == 2
    assert result["date"].is_monotonic_increasing
    assert result["date"].is_unique
    assert result["sofr"].tolist() == [5.31, 5.33]


def test_invalid_sofr_missing_rate():
    """
    A missing daily SOFR fixing should raise an error.
    """
    df = pd.DataFrame([{"date": "2024-01-02", "sofr": 5.31},
                       {"date": "2024-01-03", "sofr": None}])

    with pytest.raises(ValueError, match = "Missing or invalid"):
        validate_sofr(df)


def test_invalid_sofr_duplicate_date():
    """
    Duplicate daily SOFR observation dates should raise an error.
    """
    df = pd.DataFrame([{"date": "2024-01-02", "sofr": 5.31},
                       {"date": "2024-01-02", "sofr": 5.33}])

    with pytest.raises(ValueError, match = "Duplicate SOFR"):
        validate_sofr(df)


def test_sofr_is_fetched_from_before_the_sample_starts():
    """A contract running on the first sample day was priced off earlier fixings.

    The SR3 contract in force on 2022-02-01 began on 2021-12-15, and the pricer
    needs a fixing on or before that day. A SOFR file that starts on the sample
    start therefore cannot price February and March 2022.
    """
    from fomc_data.config import SOFR_FETCH_START, START

    assert SOFR_FETCH_START < START
    assert SOFR_FETCH_START <= pd.Timestamp("2021-12-01")


def test_fetch_rate_data_requests_sofr_from_the_lead_in_start(tmp_path, monkeypatch):
    import scripts.fetch_rate_data as script
    from fomc_data.config import SOFR_FETCH_START

    requested = {}

    def fake_sofr(start):
        requested["start"] = start
        return pd.DataFrame({"date": pd.to_datetime(["2021-10-01", "2021-10-04"]), "sofr": [0.05, 0.05]})

    monkeypatch.setattr(script, "fetch_sofr", fake_sofr)
    monkeypatch.setattr(script, "fetch_effr", lambda: pd.DataFrame({"date": pd.to_datetime(["2022-01-03"]), "effr": [0.08]}))
    monkeypatch.setattr(script, "build_fomc_decisions", lambda: pd.DataFrame({"meeting_date": pd.to_datetime(["2022-01-26"])}))
    monkeypatch.setattr(script, "validate_fomc_decisions", lambda frame: frame)
    monkeypatch.setattr(script, "ensure_dirs", lambda: None)
    for name in ("EFFR_CSV", "SOFR_CSV", "FOMC_CSV"):
        monkeypatch.setattr(script, name, tmp_path / f"{name}.csv")

    script.main()

    assert requested["start"] == SOFR_FETCH_START
    assert pd.read_csv(tmp_path / "SOFR_CSV.csv")["date"].iloc[0] == "2021-10-01"


def test_scheduled_dates_add_announced_meetings_without_touching_the_realized_calendar():
    """Announced future meetings schedule the estimator but never enter the decision table."""
    from fomc_data.fomc_calendar import scheduled_meeting_dates

    realized = list(fetch_fomc_calendar()["meeting_date"])
    scheduled = scheduled_meeting_dates()

    assert scheduled == sorted(set(scheduled))
    assert set(realized) < set(scheduled)
    extra = [day for day in scheduled if day not in set(realized)]
    assert extra == [pd.Timestamp("2026-10-28"), pd.Timestamp("2026-12-09")]
    # They all come after the last realized meeting, so nothing needs an outcome for them.
    assert min(extra) > max(realized)
