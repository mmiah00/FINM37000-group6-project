
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
    # The bars mix mean absolute error and signed bias.
    assert fig.axes[0].get_xlabel() == "Meeting-level statistic (bp)"


def test_insufficient_observations(sample_errors):
    """
    Meetings without enough forecasts should be rejected.
    """
    with pytest.raises(ValueError, match = "No meetings have enough forecasts"):
        identify_notable_meetings(sample_errors, min_observations = 10)


def _single_forecast_errors():
    """Each meeting has one forecast, so its mean absolute error equals the size of its bias."""
    return pd.DataFrame({"horizon": 1,
                         "meeting_date": ["2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18"],
                         "error_bps": [4.0, 30.0, -24.0, 1.0]})


def test_notable_meetings_with_one_forecast_are_drawn_once():
    """MAE and |bias| coincide for a single forecast, so one bar carries both names."""
    notable = identify_notable_meetings(_single_forecast_errors())
    fig = plot_notable_meetings(notable)

    ax = fig.axes[0]
    labels = [tick.get_text() for tick in ax.get_yticklabels()]
    # Largest absolute error and largest positive bias are the same meeting and the same size.
    assert len(ax.patches) == 3
    assert any("Largest average absolute error" in label and "also: largest positive bias" in label for label in labels)
    # The negative bias is a different meeting, and keeps its sign.
    assert sorted(round(patch.get_width(), 2) for patch in ax.patches) == [-24.0, 1.0, 30.0]


def test_value_labels_stay_inside_the_axes_so_they_cannot_cover_tick_labels():
    """A label on a long negative bar used to run left over the y tick labels."""
    notable = identify_notable_meetings(_single_forecast_errors())
    fig = plot_notable_meetings(notable)
    fig.canvas.draw()

    ax = fig.axes[0]
    axes_box = ax.get_window_extent()
    annotations = [text for text in ax.texts if text.get_text().endswith(" bp")]
    assert annotations
    for annotation in annotations:
        box = annotation.get_window_extent()
        assert box.x0 >= axes_box.x0 - 1 and box.x1 <= axes_box.x1 + 1, annotation.get_text()
