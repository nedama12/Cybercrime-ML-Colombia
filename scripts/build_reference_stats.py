"""Build the reference statistics used by the application for explanations and drift checks.

Uses ONLY the training partition (split == "train") of data/processed/phishing_processed.csv,
so no validation or test information reaches production.

Outputs:
  models/reference_stats.json     distribution of each computable feature (bins for PSI,
                                  medians per class for explanations)
  models/tld_legitimate_prob.json TLD -> TLDLegitimateProb lookup table

Run from the project root:  python scripts/build_reference_stats.py
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cyberapp.ml.features import COMPUTABLE_FEATURES  # noqa: E402

N_BINS = 10


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=ROOT / "data" / "processed" / "phishing_processed.csv")
    parser.add_argument("--out", default=ROOT / "models")
    args = parser.parse_args()

    df = pd.read_csv(args.data, low_memory=False)
    # Keep only well-formed rows (numeric URLLength) of the training partition.
    df = df[pd.to_numeric(df["URLLength"], errors="coerce").notna()]
    train = df[df["split"] == "train"].copy()
    for col in COMPUTABLE_FEATURES + ["is_phishing"]:
        train[col] = pd.to_numeric(train[col])
    print(f"Training rows used: {len(train):,}")

    features = {}
    for col in COMPUTABLE_FEATURES:
        s = train[col]
        inner = list(np.unique(np.quantile(s, np.linspace(0, 1, N_BINS + 1)))[1:-1])
        if not inner:
            # Sparse or almost constant features (e.g. NoOfEqualsInURL, IsHTTPS) give identical
            # quantiles. Split the dominant value from the rest so that a change in the share of
            # the minority value is still detected.
            median = float(s.median())
            inner = [(float(s.min()) + median) / 2 if median == float(s.max()) else median + 1e-9]
        # Open-ended outer bins so production values outside the training range still count.
        edges = [-np.inf] + inner + [np.inf]
        counts, _ = np.histogram(s, bins=edges)
        features[col] = {
            "mean": round(float(s.mean()), 4),
            "std": round(float(s.std()), 4),
            "median": float(s.median()),
            "median_legitimate": float(s[train["is_phishing"] == 0].median()),
            "median_phishing": float(s[train["is_phishing"] == 1].median()),
            "p01": float(s.quantile(0.01)),
            "p99": float(s.quantile(0.99)),
            "bin_edges": [None if np.isinf(e) else float(e) for e in edges],
            "bin_proportions": [round(c / len(s), 6) for c in counts],
        }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stats = {
        "source": "PhiUSIIL - data/processed/phishing_processed.csv (split == train)",
        "created": date.today().isoformat(),
        "rows": int(len(train)),
        "phishing_rate": round(float(train["is_phishing"].mean()), 4),
        "features": features,
    }
    (out / "reference_stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")

    tld = (train.groupby("TLD")["TLDLegitimateProb"].first().round(7).sort_index())
    (out / "tld_legitimate_prob.json").write_text(json.dumps(tld.to_dict(), indent=0), encoding="utf-8")
    print(f"Saved reference_stats.json ({len(features)} features) and "
          f"tld_legitimate_prob.json ({len(tld)} TLDs) to {out}")


if __name__ == "__main__":
    main()
