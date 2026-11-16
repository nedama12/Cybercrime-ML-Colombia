# Cybercrime Classifier Experiment

This experiment predicts the approximate legal category assigned to aggregated rows. It is not an individual incident detector.

## Data audit

- Rows: 66,400; exact duplicate rows: 0.
- Missing values: 985; target/article mapping mismatches: 0.
- CV groups: offense name × department × municipality. Geographic test departments: Antioquia, Archipiélago de San Andrés, Providencia y Santa Catalina, Cesar, Nariño.
- `delito`, `articulo`, `es_agravado`, aggregate counts, legal/case outcomes, and duplicate normalized location fields were excluded from predictors.

## Grouped cross-validation comparison

| Model | Macro F1 mean | Macro F1 std | Macro precision | Macro recall | Weighted F1 | Minority recall |
|---|---:|---:|---:|---:|---:|---:|
| hist_gradient_boosting | 0.0770 | 0.0033 | 0.0982 | 0.0923 | 0.1806 | 0.0028 |
| engineered_logistic_C1_balanced | 0.0630 | 0.0032 | 0.0853 | 0.1340 | 0.0803 | 0.2165 |
| engineered_logistic_C1_unweighted | 0.0607 | 0.0030 | 0.0530 | 0.0891 | 0.1589 | 0.0000 |
| engineered_logistic_C1_balanced_select75 | 0.0586 | 0.0082 | 0.0819 | 0.1316 | 0.0837 | 0.2424 |
| engineered_logistic_C0.1_balanced | 0.0578 | 0.0024 | 0.0838 | 0.1516 | 0.0705 | 0.2925 |
| random_forest_balanced | 0.0574 | 0.0023 | 0.0646 | 0.0830 | 0.0829 | 0.1014 |
| engineered_logistic_C10_balanced | 0.0521 | 0.0095 | 0.0788 | 0.1184 | 0.0734 | 0.2035 |
| extra_trees_balanced | 0.0438 | 0.0012 | 0.0512 | 0.0661 | 0.0612 | 0.0870 |
| original_logistic_regression | 0.0371 | 0.0067 | 0.0470 | 0.0501 | 0.0536 | 0.0543 |

## Held-out geographic test

| Model | Accuracy | Macro precision | Macro recall | Macro F1 | Weighted F1 |
|---|---:|---:|---:|---:|---:|
| original_logistic_regression | 0.2839 | 0.1047 | 0.1124 | 0.0716 | 0.1696 |
| engineered_logistic_C0.1_balanced | 0.1764 | 0.1353 | 0.1944 | 0.0876 | 0.1533 |
| engineered_logistic_C1_balanced | 0.1706 | 0.1390 | 0.1944 | 0.0841 | 0.1437 |
| engineered_logistic_C1_balanced_select75 | 0.1672 | 0.1304 | 0.1891 | 0.0790 | 0.1419 |
| engineered_logistic_C10_balanced | 0.1690 | 0.1466 | 0.1910 | 0.0816 | 0.1434 |
| engineered_logistic_C1_unweighted | 0.2934 | 0.1437 | 0.1112 | 0.0505 | 0.1332 |
| random_forest_balanced | 0.2728 | 0.1343 | 0.1565 | 0.1162 | 0.2052 |
| extra_trees_balanced | 0.2781 | 0.1376 | 0.1412 | 0.1061 | 0.1888 |
| hist_gradient_boosting | 0.2794 | 0.1098 | 0.1105 | 0.0722 | 0.1731 |

## Temporal test

Training years ≤ 2022; validation year 2023; held-out test years ≥ 2024.

| Model | Accuracy | Macro precision | Macro recall | Macro F1 | Weighted F1 |
|---|---:|---:|---:|---:|---:|
| random_forest_balanced | 0.2055 | 0.1610 | 0.2457 | 0.1492 | 0.2219 |
| hist_gradient_boosting | 0.2760 | 0.1338 | 0.1261 | 0.1084 | 0.2371 |
| original_logistic_regression | 0.1420 | 0.1578 | 0.2459 | 0.1158 | 0.1634 |

## Strict spatiotemporal test

Future event years >=2024 within the held-out departments; rows: 3,496.

| Model | Accuracy | Macro precision | Macro recall | Macro F1 | Weighted F1 |
|---|---:|---:|---:|---:|---:|
| hist_gradient_boosting | 0.2200 | 0.0802 | 0.1027 | 0.0705 | 0.1507 |
| original_logistic_regression | 0.2620 | 0.1121 | 0.1134 | 0.0675 | 0.1497 |

## Promotion decision

Candidate: `hist_gradient_boosting`. Eligible for promotion: **False**.

Production model was not replaced. Promotion checks not met: group_bootstrap_95pct_delta_lower_above_zero.

The historical 80/20 random split reported accuracy 0.1398 and macro F1 0.1176. That split selected a model using its own test results, so it is retained only as a legacy reference; comparisons here use independently reserved geography and time.

## Limitations

The class label is an approximate mapping from legal article to category. Input features do not describe an incident's technical behavior, so the model cannot identify an individual cyberattack. The target is strongly tied to crime text, which is deliberately excluded to avoid direct leakage. Small classes remain statistically unstable, especially in the strict future-and-unseen-department test.
