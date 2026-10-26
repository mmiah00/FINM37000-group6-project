
"""
Shared publication-style formatting for Issue #7 figures.
"""

import matplotlib.pyplot as plt

COLORS = {"navy": "#24476B",
          "blue": "#4A90B8",
          "orange": "#D98A43",
          "gray": "#777F89",
          "grid": "#E6E9ED",}


def apply_style():
    """
    Apply consistent formatting across all final visualizations.
    """
    plt.rcParams.update({"figure.facecolor": "white",
                         "axes.facecolor": "white",
                         "font.family": "DejaVu Sans",
                         "font.size": 10,
                         "axes.titlesize": 12,
                         "axes.titleweight": "semibold",
                         "axes.labelsize": 10,
                         "xtick.labelsize": 9,
                         "ytick.labelsize": 9,
                         "legend.fontsize": 9,
                         "legend.frameon": False,
                         "axes.spines.top": False,
                         "axes.spines.right": False,
                         "axes.edgecolor": "#AEB5BD",
                         "axes.linewidth": 0.8,
                         "grid.color": COLORS["grid"],
                         "grid.linewidth": 0.7,
                         "grid.alpha": 0.8,
                         "savefig.facecolor": "white",
                         "savefig.dpi": 300})


def style_axes(ax, grid_axis = "y"):
    """
    Apply consistent styling to an individual subplot.
    """
    ax.set_axisbelow(True)
    ax.grid(axis = grid_axis)
