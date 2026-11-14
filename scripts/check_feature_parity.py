"""Check that the application computes the same features as the training dataset.

Recomputes every URL feature with cyberapp.ml.features for a sample of the TEST partition and
reports, per feature, the share of rows where the value matches the dataset exactly and
within a tolerance of one character (counts) or 0.01 (ratios).

Run from the project root:  python scripts/check_feature_parity.py --sample 20000
"""
import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cyberapp.ml.features import URL_FEATURES, extract_url_features, load_json  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=ROOT / "data" / "processed" / "phishing_processed.csv")
    parser.add_argument("--sample", type=int, default=20000)
    args = parser.parse_args()

    df = pd.read_csv(args.data, low_memory=False)
    df = df[pd.to_numeric(df["URLLength"], errors="coerce").notna()]
    test = df[df["split"] == "test"]
    test = test.sample(min(args.sample, len(test)), random_state=42)
    tld = load_json(ROOT / "models" / "tld_legitimate_prob.json") or {}

    computed = pd.DataFrame([extract_url_features(u, tld) for u in test["URL"]], index=test.index)
    cols = URL_FEATURES + (["TLDLegitimateProb"] if tld else [])
    rows = []
    for col in cols:
        expected = pd.to_numeric(test[col]).astype(float)
        got = computed[col].astype(float)
        tolerance = 0.01 if ("Ratio" in col or "Prob" in col) else 1
        exact = got.round(3) == expected.round(3)
        close = (got - expected).abs() <= tolerance + 1e-9
        legit = test["is_phishing"].astype(float) == 0
        rows.append({
            "feature": col,
            "exact": exact.mean(),
            "within_tolerance": close.mean(),
            "exact_legitimate": exact[legit].mean(),
            "exact_phishing": exact[~legit].mean(),
        })
    report = pd.DataFrame(rows).set_index("feature").round(4)
    print(f"Feature parity on {len(test):,} test URLs\n")
    print(report.to_string())
    print("\nNote: in PhiUSIIL the length-based features were computed on a URL one character "
          "shorter than the stored one for every legitimate row and about half of the phishing "
          "rows, so they can differ by one character. See the CRISP-ML phase 2 page.")


if __name__ == "__main__":
    main()
