
"""
Tests for historical FOMC example selection (Issue #7).
"""

import matplotlib
matplotlib.use("Agg")

import pandas as pd
import pytest

from final_visualizations.historical_examples import (identify_notable_meetings, plot_notable_meetings,)


@pytest.fixture
def sample_errors():
    """
    Synthetic forecasts for four FOMC meetings.
    """
    rows = []

    meetings = {"2025-01-29": [5, -5, 0],
                "2025-03-19": [30, 25, 35],
                "2025-05-07": [-20, -25, -30],
                "2025-06-18": [2, -2, 0]}

    for meeting, errors in meetings.items():
        for error in errors:
            rows.append({"horizon": 1,
                         "meeting_date": meeting,
                         "error_bps": error})

    return pd.DataFrame(rows)


def test_identify_notable_meetings(sample_errors):
    """
    Verify the correct meetings are selected.
    """
    notable = identify_notable_meetings(sample_errors)

    assert notable.loc["Largest average absolute error", "meeting_date"] == pd.Timestamp("2025-03-19")

    assert notable.loc["Smallest average absolute error", "meeting_date"] == pd.Timestamp("2025-06-18")

    assert notable.loc["Largest positive bias", "meeting_date"] == pd.Timestamp("2025-03-19")

    assert notable.loc["Largest negative bias", "meeting_date"] == pd.Timestamp("2025-05-07")


def test_plot_notable_meetings(sample_errors):
    """
    Verify that the selected episodes can be plotted.
    """
    notable = identify_notable_meetings(sample_errors)
    fig = plot_notable_meetings(notable)

    assert isinstance(fig, matplotlib.figure.Figure)
    assert len(fig.axes) == 1


def test_insufficient_observations(sample_errors):
    """
    Meetings without enough forecasts should be rejected.
    """
    with pytest.raises(ValueError, match = "No meetings have enough forecasts"):
        identify_notable_meetings(sample_errors, min_observations = 10)
