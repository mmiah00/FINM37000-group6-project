"""SOFR futures data collection for the FINM 37000 group project.

Stage 1 of the project roadmap: pull One-Month (SR1) and Three-Month (SR3)
SOFR futures settlement prices from Databento, standardize contract
identifiers and settlement reference periods, check for missing or
inconsistent observations, and write a tidy panel for the pricing model.

Build the data:

    python scripts/fetch_sofr_futures.py --dry-run   # cost estimate only
    python scripts/fetch_sofr_futures.py

Use it:

    from sofr_data import load_settlements, settlement_curve

    panel = load_settlements()
    curve = settlement_curve(panel, "2024-05-30")
"""

from sofr_data.dataset import load_contracts, load_settlements, settlement_curve

__all__ = ["load_contracts", "load_settlements", "settlement_curve"]
