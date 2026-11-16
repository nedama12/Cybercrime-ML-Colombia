# Model Engineering Report

## 1. Goal

Classify a citizen's short incident report into the legal category of cybercrime defined by
Law 1273 of 2009, so the platform can give the right first steps, route the report to an analyst
and build regional evidence of new fraud patterns. Decision Tree, Random Forest and Logistic
Regression were compared with the same protocol on two problems:

| Problem | Question | Role in the platform |
|---|---|---|
| Report classifier | Which category does the citizen's report describe? | In production |
| Location benchmark | Can the category be predicted from where and when a case was registered? | Exploratory |

## 2. Data

- **Official records**: `data/processed/crimes_processed.csv`, 66,400 aggregated rows from the
  Attorney General's Office (2010-2026, 565,050 cases) after cleaning 66,422 raw rows
  (`analysis/03_cleaning.py`, evidence in `reports/data_quality.json`).
- **Seed corpus**: `data/reports/seed_reports.csv`, 2,080 victim-style reports (260 per category,
  English and Spanish) generated from 93 base phrases written by the team from the legal
  definitions (`src/build_seed_corpus.py`, seed 42). Each row keeps its `template_id`.
- **Realistic holdout**: `data/reports/realistic_holdout.csv`, 46 reports written separately with
  different wording. Final evaluation only.

## 3. Features and leakage control

Report classifier inputs: `description` (word TF-IDF 1-2 grams + character TF-IDF 3-5 grams),
`channel` (one-hot) and five yes/no `affected_*` columns, i.e. only what the citizen knows.
`src/report_features.py` builds the same input for training and inference. All transformations
live inside a scikit-learn `Pipeline`, so they are fitted only on training data.

The benchmark uses `criminality`, `department`, `municipality`, `regional_office`, `offense_year`,
`entry_year`, `report_year` and `partial_year`; the columns the category is derived from and the
procedural stage columns are excluded.

## 4. Protocol

1. 80/20 split with `StratifiedGroupKFold` grouped by `template_id`: 1,658 training reports
   (74 base phrases) and 422 test reports whose 19 base phrases never appear in training.
2. `GridSearchCV` with 5-fold `StratifiedGroupKFold` on the training split only, metric macro F1.
   Grids: Decision Tree `max_depth` {None, 30} × `min_samples_leaf` {1, 3, 5}; Random Forest
   `max_depth` {None, 40} × `min_samples_leaf` {1, 2}; Logistic Regression `C` {0.5, 2, 8, 32}.
   All 14 configurations are logged in `reports/report_classifier/experiments.csv`.
3. Selection: highest mean cross-validated macro F1.
4. Final evaluation on the test split and on the realistic holdout, never used for tuning or
   selection.

## 5. Results

| Model | Best parameters | CV macro F1 | Training F1 | Test accuracy | Test macro F1 | Holdout accuracy | Mean confidence (test) |
|---|---|---:|---:|---:|---:|---:|---:|
| Decision Tree | max_depth None, min_samples_leaf 1 | 0.743 ± 0.087 | 1.000 | 0.737 | 0.705 | 0.761 | 1.000 |
| Random Forest | max_depth None, min_samples_leaf 1 | 0.828 ± 0.070 | 1.000 | 0.884 | 0.878 | 0.739 | 0.594 |
| **Logistic Regression** | **C = 8** | **0.956 ± 0.010** | 1.000 | **0.967** | **0.965** | **0.978** | 0.860 |

**Logistic Regression (C = 8) is in production.** It is also the most stable model across folds.
The trees reach F1 = 1.0 on training but lose 0.17-0.26 in cross-validation (overfitting to the
training phrases); the Decision Tree is over-confident and the Random Forest under-confident.
Stronger regularisation (C = 0.5) lowered the CV F1 to 0.931 (underfitting).

On the realistic holdout the selected model reaches accuracy 0.978, macro F1 0.979 and top-2
accuracy 1.000; 97.8 % of the reports are answered above the 45 % confidence threshold. Reports
below the threshold are sent to an analyst instead of showing an uncertain answer.

**Location benchmark** (66,400 official rows, stratified 80/20): accuracy 0.145-0.160 and
macro F1 0.112-0.128 for the three algorithms. Location and time do not identify the offense,
which is why the platform asks the citizen what happened.

## 6. Deployment and monitoring

`models/report_classifier.joblib` stores the full pipeline; `models/report_classifier_info.json`
stores version, parameters, metrics and threshold; `models/report_reference_stats.json` stores
the training distributions used for drift detection. `src/report_model.py` is the single entry
point used by `app.py`. Every report stores the prediction, confidence, model version, inference
time and the time the citizen needed to complete it.

`python -m src.monitoring` runs the model on 600 **simulated** operational reports over four
weeks. Weeks 1-2 stay within thresholds; weeks 3-4 introduce new fraud wording and more
social-media reports and raise drift alerts (PSI of the channel 0.38-0.39 > 0.25) while the
agreement stays above 98 %.

## 7. Limitations

- The training text is written by the team, not real victim reports, and the realistic holdout
  is small (46 reports). Real performance must be tracked with the analyst agreement rate.
- The official data is aggregated and its categories come from an approximate mapping of legal
  articles.
- The platform does not replace a criminal complaint.

## 8. Reproduce

```
python -m src.data_quality
python -m src.build_seed_corpus
python -m src.train_report_model
python -m src.train
python -m src.monitoring
python -m src.verify_models
python -m unittest discover -s tests
```
