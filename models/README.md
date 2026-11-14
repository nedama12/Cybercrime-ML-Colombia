# Model artifacts

This folder holds the model selected in **Model Engineering** (CRISP-ML phase 3) and the
files the application needs to use it. The Flask app loads it at start-up; if the files are
missing, the system still works but classification is disabled and the model card explains why.

## Files

| File | Produced by | Purpose |
|---|---|---|
| `model_metadata.json` | Model Engineering | Version, input features, threshold and evaluation results |
| `phishing_model.joblib` (or the name in `artifact`) | Model Engineering | Fitted scikit-learn `Pipeline` (preprocessing + classifier) |
| `reference_stats.json` | `scripts/build_reference_stats.py` | Training distribution of each URL feature, used for explanations and drift checks |
| `tld_legitimate_prob.json` | `scripts/build_reference_stats.py` | Lookup table for the `TLDLegitimateProb` feature |

## Model contract

The `.joblib` file must be a fitted scikit-learn **Pipeline** whose input is a pandas
DataFrame with the columns listed in `features` (same order) and that implements
`predict_proba`. Any scaler or encoder goes **inside** the Pipeline so that it is fitted only
on the training partition and applied identically in production.

`model_metadata.json`:

```json
{
  "model_name": "phishing-url-classifier",
  "version": "1.0.0",
  "algorithm": "RandomForestClassifier",
  "artifact": "phishing_model.joblib",
  "trained_at": "2026-11-20",
  "sklearn_version": "1.9.1",
  "target": "is_phishing",
  "positive_class": 1,
  "threshold": 0.5,
  "features": ["URLLength", "DomainLength", "..."],
  "metrics": {
    "validation": {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0},
    "test": {"accuracy": 0.0, "precision": 0.0, "recall": 0.0, "f1": 0.0, "roc_auc": 0.0}
  },
  "confusion_matrix": {"test": [[0, 0], [0, 0]]},
  "comparison": [
    {"algorithm": "LogisticRegression", "accuracy": 0.0, "precision": 0.0, "recall": 0.0,
     "f1": 0.0, "cv_f1_mean": 0.0, "cv_f1_std": 0.0, "best_params": {}}
  ],
  "cross_validation": {"strategy": "StratifiedGroupKFold grouped by domain", "folds": 5},
  "feature_importance": [{"feature": "URLLength", "importance": 0.0}],
  "training_data": {"source": "PhiUSIIL", "train_rows": 0, "validation_rows": 0, "test_rows": 0}
}
```

Required keys: `version`, `features`. Recommended: everything else; the CRISP-ML phase 3 and 4
pages and the monitoring module read `metrics`, `confusion_matrix`, `comparison`,
`cross_validation` and `feature_importance` from this file, so the published results always
match the deployed model.

### Features the application can compute

The classification form computes these features from the URL text, with the same rules as
the PhiUSIIL dataset (`cyberapp/ml/features.py`, parity checked with
`scripts/check_feature_parity.py`):

`URLLength, DomainLength, IsDomainIP, TLDLength, NoOfSubDomain, HasObfuscation,
NoOfObfuscatedChar, ObfuscationRatio, NoOfLettersInURL, LetterRatioInURL, NoOfDegitsInURL,
DegitRatioInURL, NoOfEqualsInURL, NoOfQMarkInURL, NoOfAmpersandInURL,
NoOfOtherSpecialCharsInURL, SpacialCharRatioInURL, IsHTTPS, TLDLegitimateProb`

If the model needs other features (for example page features), the analyst must type them in
the form, and the prediction is marked as using manual inputs.

## Updating the model

1. Train and evaluate the new version (Model Engineering).
2. Replace the two files above, increasing `version` (e.g. `1.1.0`).
3. Restart the app (Render redeploys on push). Every new prediction stores the new version,
   so results of different versions can be compared in the monitoring module.
