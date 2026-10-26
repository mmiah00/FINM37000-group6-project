
"""
Final full-vs-simplified model comparison for Issue #7.

Consumes the comparison results produced by Issue #6.
Forecast errors are expressed in basis points.
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from final_visualizations.style import COLORS


def summarize_model_comparison(results):
    """
    Summarize forecast accuracy for both methodologies.

    Args:
    - results (pd.DataFrame): Output of curve_compare.compare.run_comparison().

    Returns (pd.DataFrame): Bias, MAE, RMSE, and observation counts.
    """
    rows = []

    for method, column in [("Full model", "full_model_error_bps"), ("Simplified curve", "simple_curve_error_bps")]:
        errors = results[column].dropna()

        rows.append({"method": method,
                     "n_obs": len(errors),
                     "bias_bps": errors.mean(),
                     "mae_bps": errors.abs().mean(),
                     "rmse_bps": np.sqrt((errors**2).mean())})

    return pd.DataFrame(rows).set_index("method")


def plot_model_comparison(results):
    """
    Plot overall accuracy and performance by FOMC regime.

    Args:
    - results (pd.DataFrame): Output of Issue #6's run_comparison().

    Returns (matplotlib.figure.Figure): Two-panel comparison figure.
    """
    summary = summarize_model_comparison(results)

    fig, (ax_overall, ax_regime) = plt.subplots(1, 2, figsize = (12, 4.5))

    #panel A: Overall forecast accuracy.
    methods = summary.index.tolist()
    x = np.arange(len(methods))
    width = 0.35

    bars_mae = ax_overall.bar(x - width / 2, summary["mae_bps"], width, color ="#AEB5BD", label = "MAE")
    bars_rmse = ax_overall.bar(x + width / 2, summary["rmse_bps"], width, color = COLORS["gray"], label = "RMSE")

    for bars in (bars_mae, bars_rmse):
        ax_overall.bar_label(bars, fmt = "%.2f", padding = 3, fontsize = 9)

    ax_overall.set_xticks(x)
    ax_overall.set_xticklabels(methods)
    ax_overall.set_ylabel("Forecast error (bp)")
    ax_overall.set_title("Overall forecast accuracy")
    ax_overall.legend()
    ax_overall.grid(axis = "y", alpha = 0.3)

    #panel B: Accuracy by realized FOMC regime (dumbell plot).
    regimes = results.copy()
    regimes["regime"] = np.where(regimes["rate_change_at_meeting"], "Change", "Hold")

    regime_summary = (regimes.groupby("regime")[["full_model_error_bps", "simple_curve_error_bps"]]
                             .agg(lambda x: x.abs().mean())
                             .reindex(["Change", "Hold"]))

    for i, (regime, row) in enumerate(regime_summary.iterrows()):
        full = row["full_model_error_bps"]
        simple = row["simple_curve_error_bps"]

        ax_regime.plot([full, simple], [i, i], color ="#AEB5BD", linewidth = 2, zorder = 1)
        ax_regime.scatter(full, i, color = COLORS["navy"], s = 75, label = "Full model" if i == 0 else None, zorder = 3)
        ax_regime.scatter(simple, i, color = COLORS["orange"], s = 75, label = "Simplified curve" if i == 0 else None, zorder = 3)

    ax_regime.set_yticks(range(len(regime_summary)))
    ax_regime.set_yticklabels(regime_summary.index)
    ax_regime.invert_yaxis()

    ax_regime.set_xlabel("Mean absolute error (bp)")
    ax_regime.set_title("Accuracy by FOMC Decision")
    ax_regime.legend()
    ax_regime.grid(axis = "x", alpha = 0.3)

    fig.suptitle("Forecast Accuracy: Full vs. Simplified SOFR Model", fontsize = 14, fontweight = "semibold")

    fig.tight_layout()

    return fig

