"""
Run the FOMC and realized interest rate data pipeline.
"""

from fomc_data.config import EFFR_CSV, SOFR_CSV, FOMC_CSV, SOFR_FETCH_START, ensure_dirs
from fomc_data.nyfed_io import fetch_effr, fetch_sofr
from fomc_data.dataset import build_fomc_decisions
from fomc_data.clean import validate_fomc_decisions, validate_sofr


def main():
    """
    Fetch daily EFFR and SOFR, build and validate FOMC decisions, and save the processed datasets.

    Returns: None. Writes EFFR and FOMC CSVs to the processed data directory.
    """
    ensure_dirs()

    #1. Download daily EFFR and SOFR observations.
    print("Fetching EFFR data...")
    effr = fetch_effr()

    print("Fetching SOFR data...")
    #start before the sample so contracts already running on its first day can be priced.
    sofr = validate_sofr(fetch_sofr(start = SOFR_FETCH_START))

    #2. Construct and validate FOMC decisions.
    print("Building FOMC decisions...")
    fomc = build_fomc_decisions()
    fomc = validate_fomc_decisions(fomc)

    #3. Save processed datasets. Keep the three datasets separate for downstream modeling.
    effr.to_csv(EFFR_CSV, index = False)
    sofr.to_csv(SOFR_CSV, index = False)
    fomc.to_csv(FOMC_CSV, index = False)

    print(f"Saved {len(effr)} EFFR observations to {EFFR_CSV}")
    print(f"Saved {len(sofr)} SOFR observations to {SOFR_CSV}")
    print(f"Saved {len(fomc)} FOMC meetings to {FOMC_CSV}")


if __name__ == "__main__":
    main()
