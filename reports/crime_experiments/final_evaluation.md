# Final Evaluation — Cybercrime Category Classifier

## Decision

The active production model remains Logistic Regression. No candidate met the predeclared promotion checks, and no model approached the requested macro F1 of 0.80. The strongest single observed temporal result was Random Forest with balanced class weights (macro F1 0.1492, weighted F1 0.2219); the primary grouped cross-validation winner was HistGradientBoosting (mean macro F1 0.0770), but its geographic holdout macro F1 was 0.0722 and its minority-class recall was almost zero. The split results disagree, so neither candidate is promoted.

This predicts the approximate legal category assigned to an **aggregated process record**. It is not a detector for individual cybercrime incidents.

## Data and target audit

The processed dataset contains 66,400 rows and nine categories. There are 0 exact duplicate rows, 34,646 repeated partial keys on crime, department, municipality, and event year, 985 missing cells (656 in `seccional`, 329 in `articulo`), and 0 mismatches between the recognized article mapping and the existing category. The repeated partial keys are not exact duplicates and were kept. The 329 records without an article are retained as `NO_ESPECIFICADO`; that class is small and semantically heterogeneous.

| Category | Rows | Share |
|---|---:|---:|
| HURTO_ELECTRONICO | 20,473 | 30.83% |
| ACCESO_ABUSIVO | 15,990 | 24.08% |
| DATOS_PERSONALES | 12,911 | 19.44% |
| PHISHING_SUPLANTACION | 5,694 | 8.58% |
| FRAUDE_TRANSFERENCIA | 4,921 | 7.41% |
| ATAQUE_A_SISTEMAS | 4,725 | 7.12% |
| MALWARE | 982 | 1.48% |
| EQUIPOS_MOVILES | 375 | 0.56% |
| NO_ESPECIFICADO | 329 | 0.50% |

The target is derived from `DELITO` and its extracted legal article. These source fields, `articulo`, `es_agravado`, legal/case outcomes, and aggregate process counts are excluded from model predictors. The model uses only the current eight-field input contract (criminality indicator, territory, office, and dates); the engineered pipelines add date delays and geographic/period features. All imputers, encoders, scaling, and feature selection are fitted inside each training fold.

The low ceiling is primarily an information problem: the label is a legal classification, while the predictors contain no description of the conduct or technical evidence. Territory, years, and the `criminalidad` indicator cannot reliably distinguish different legal articles. The large classes dominate weighted metrics, while macro F1 gives each small class equal weight. The old 80/20 result (accuracy 0.1398, macro F1 0.1176) was selected using the same test results and is a legacy reference, not an independent estimate.

## Split design

- **Grouped validation:** three-fold `StratifiedGroupKFold` on offense × department × municipality groups, within the development data through 2023. Preprocessing is refit per fold.
- **Geographic test:** held-out departments, with no department overlap with development. The test contains 13,008 rows across Antioquia, Archipiélago de San Andrés, Providencia y Santa Catalina, Cesar, and Nariño. The model is selected using grouped validation, not these test metrics.
- **Temporal validation/test:** fit through event year 2022, validate on 2023, refit through 2023, and evaluate on event years 2024–2026. The 2026 records are partial. This holdout permits recurring territory/crime groups across years, so it is not a strict unseen-group test.
- **Strict spatiotemporal check:** future years 2024–2026 within the held-out departments (3,496 rows), with no department overlap with development.

The temporal test includes the partial 2026 period, so the temporal figures below should be read with that limitation. The independent geographic holdout remains the primary check on unseen territories.

## Grouped cross-validation comparison

| Model | Accuracy | Precision macro | Recall macro | F1 macro (mean ± SD) | F1 weighted | Minority recall |
|---|---:|---:|---:|---:|---:|---:|
| HistGradientBoosting | 0.2288 | 0.0982 | 0.0923 | **0.0770 ± 0.0033** | 0.1806 | 0.0028 |
| Engineered Logistic Regression C=1, balanced | 0.0780 | 0.0853 | 0.1340 | 0.0630 ± 0.0032 | 0.0803 | 0.2165 |
| Engineered Logistic Regression C=1, unweighted | 0.2417 | 0.0530 | 0.0891 | 0.0607 ± 0.0030 | 0.1589 | 0.0000 |
| Logistic Regression C=1, balanced, select 75% | 0.0750 | 0.0819 | 0.1316 | 0.0586 ± 0.0082 | 0.0837 | 0.2424 |
| Engineered Logistic Regression C=0.1, balanced | 0.0667 | 0.0838 | 0.1516 | 0.0578 ± 0.0024 | 0.0705 | 0.2925 |
| Random Forest, balanced subsample | 0.0727 | 0.0646 | 0.0830 | 0.0574 ± 0.0023 | 0.0829 | 0.1014 |
| Engineered Logistic Regression C=10, balanced | 0.0699 | 0.0788 | 0.1184 | 0.0521 ± 0.0095 | 0.0734 | 0.2035 |
| Extra Trees, balanced | 0.0527 | 0.0512 | 0.0661 | 0.0438 ± 0.0012 | 0.0612 | 0.0870 |
| Original Logistic Regression | 0.0450 | 0.0470 | 0.0501 | 0.0371 ± 0.0067 | 0.0536 | 0.0543 |

No oversampling was used: synthetic or duplicated rows are not meaningful for these aggregated categorical records. Class weights were compared instead. HistGradientBoosting led CV macro F1 but had only 0.28% average recall across classes under 2% prevalence.

## Held-out geographic test — all candidates

| Model | Accuracy | Precision macro | Recall macro | F1 macro | F1 weighted |
|---|---:|---:|---:|---:|---:|
| Original Logistic Regression | 0.2839 | 0.1047 | 0.1124 | 0.0716 | 0.1696 |
| Engineered Logistic Regression C=0.1, balanced | 0.1764 | 0.1353 | 0.1944 | 0.0876 | 0.1533 |
| Engineered Logistic Regression C=1, balanced | 0.1706 | 0.1390 | 0.1944 | 0.0841 | 0.1437 |
| Logistic Regression C=1, balanced, select 75% | 0.1672 | 0.1304 | 0.1891 | 0.0790 | 0.1419 |
| Engineered Logistic Regression C=10, balanced | 0.1690 | 0.1466 | 0.1910 | 0.0816 | 0.1434 |
| Engineered Logistic Regression C=1, unweighted | 0.2934 | 0.1437 | 0.1112 | 0.0505 | 0.1332 |
| Random Forest, balanced subsample | 0.2728 | 0.1343 | 0.1565 | **0.1162** | **0.2052** |
| Extra Trees, balanced | 0.2781 | 0.1376 | 0.1412 | 0.1061 | 0.1888 |
| HistGradientBoosting | 0.2794 | 0.1098 | 0.1105 | 0.0722 | 0.1731 |

HistGradientBoosting was the grouped-CV winner. Its geographic macro F1 gain over the original model was only 0.0006; a paired group bootstrap gave a 95% interval of −0.0058 to +0.0067. The interval includes no improvement. Random Forest's higher geographic test score was not selected from that test; it is reported as a result, not evidence to promote it.

## Temporal validation and test

The model chosen using 2023 validation was Random Forest with balanced class weights.

| Split | Model | Accuracy | Precision macro | Recall macro | F1 macro | F1 weighted |
|---|---|---:|---:|---:|---:|---:|
| Validation (2023) | Random Forest, balanced | 0.1880 | 0.1662 | 0.2622 | **0.1440** | 0.2071 |
| Validation (2023) | HistGradientBoosting | 0.2987 | 0.1706 | 0.1362 | 0.1176 | 0.2476 |
| Validation (2023) | Original Logistic Regression | 0.1380 | 0.1558 | 0.2352 | 0.1140 | 0.1614 |
| Test (2024–2026 partial) | Random Forest, balanced | 0.2055 | 0.1610 | 0.2457 | **0.1492** | 0.2219 |
| Test (2024–2026 partial) | HistGradientBoosting | 0.2760 | 0.1338 | 0.1261 | 0.1084 | 0.2371 |
| Test (2024–2026 partial) | Original Logistic Regression | 0.1420 | 0.1578 | 0.2459 | 0.1158 | 0.1634 |

This temporal result is better for Random Forest than the same model's grouped CV, illustrating that its quality depends strongly on whether a region/crime pattern recurs. The test contains 4,028 crime-geography groups that also appear in the refit period; it measures future years in known groups, not unseen territories.

## Per-category reports and confusion matrices

The geographic test classification report and confusion matrix are saved for every candidate in `reports/crime_experiments/geographic_<model>_class_metrics.csv` and `reports/crime_experiments/geographic_<model>_confusion_matrix.csv` (PNG versions are also provided). The original-versus-selected strict spatiotemporal and temporal test reports are in the same directory. In the geographic holdout, HistGradientBoosting has zero recall for `ATAQUE_A_SISTEMAS`, `EQUIPOS_MOVILES`, `MALWARE`, `NO_ESPECIFICADO`, and `PHISHING_SUPLANTACION`; this minority-class collapse is a material reason not to promote it.

## Deployment decision and limitations

- Historical reference: accuracy 13.98%, macro F1 11.76%, weighted F1 16.25% on a model-selected random split.
- Primary grouped-CV validation: HistGradientBoosting macro F1 7.70% (weighted F1 18.06%).
- Its unseen-department geographic test: macro F1 7.22% (weighted F1 17.31%).
- The highest temporal test result was Random Forest: macro F1 14.92% (weighted F1 22.19%), but geography and grouped CV were materially weaker.
- **F1 macro 80% was not reached.** No replacement was validated across both geography and time; the active Logistic Regression artifact and Flask prediction contract remain unchanged.
- The 2026 partial-year rows are included in the existing classifier temporal evaluation but not in territorial forecast fitting.
- The target is a legal article-to-category mapping, not an independently adjudicated incident label. `NO_ESPECIFICADO` has 329 records and is not semantically homogeneous.
- Available predictors lack incident facts. Adding `DELITO`, article codes, or derivatives would leak the target rather than improve a real prediction task.
- Local verification used scikit-learn 1.9.1, while the serialized crime and phishing artifacts were created with the pinned 1.8.0. Predictions passed but emitted `InconsistentVersionWarning`; run with the pinned dependency before deployment or retraining.

The experiment is reproducible with `python -m src.experiment_crime`. It saves only the separate crime experiment candidate and `reports/crime_experiments/` outputs; it does not overwrite `models/best_model.joblib` or phishing artifacts. The model is not promoted by this report.
