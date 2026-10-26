import pandas as pd
import pytest

from curve_compare.simple_curve import simple_curve_path
from scripts.prepare_historical_comparison import main


def test_comparison_uses_published_anchor_and_realized_move(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    processed = tmp_path / "data" / "processed"
    output = processed / "visualizations"
    output.mkdir(parents=True)

    obs_date = pd.Timestamp("2025-01-30")
    effective_date = pd.Timestamp("2025-02-20")
    futures = pd.DataFrame({
        "trade_date": [obs_date, obs_date],
        "root": ["SR1", "SR1"],
        "reference_start": ["2025-01-01", "2025-02-01"],
        "reference_end": ["2025-01-31", "2025-02-28"],
        "settlement_price": [95.5, 95.5],
    })
    futures.to_parquet(processed / "sofr_futures_settlements.parquet", index=False)
    pd.DataFrame({
        "meeting_date": ["2025-01-29", "2025-02-19"],
        "effective_date": ["2025-01-30", effective_date],
        "change_bps": [-25.0, 0.0],
    }).to_csv(processed / "fomc_meetings.csv", index=False)
    pd.DataFrame({
        "date": ["2025-01-28", "2025-01-29", obs_date.strftime("%Y-%m-%d")],
        "sofr": [4.5, 4.5, 9.0],
    }).to_csv(processed / "sofr_daily.csv", index=False)
    pd.DataFrame({
        "obs_date": [obs_date],
        "meeting_date": ["2025-02-19"],
        "horizon": [1],
        "error_bps": [0.0],
        "realized_cum_bps": [0.0],
    }).to_csv(output / "forecast_errors.csv", index=False)

    main()

    comparison = pd.read_csv(output / "model_comparison.csv")
    strip = futures.rename(columns={
        "reference_start": "month_start",
        "reference_end": "month_end",
        "settlement_price": "price",
    })
    strip["month_start"] = pd.to_datetime(strip["month_start"])
    strip["month_end"] = pd.to_datetime(strip["month_end"])
    simple_rate = simple_curve_path(strip, obs_date, [effective_date]).iloc[0]
    assert len(comparison) == 1
    assert comparison.loc[0, "simple_implied_change_bps"] == pytest.approx((simple_rate - 4.25) * 100)
