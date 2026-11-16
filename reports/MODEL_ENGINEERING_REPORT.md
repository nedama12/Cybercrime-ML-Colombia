# Model Engineering Report

## Purpose

This project trains supervised classifiers to predict the `categoria` label in a processed Colombian cybercrime dataset. The task is multiclass classification over nine target categories. It does not predict whether a report is true, determine legal responsibility, or forecast future crime rates.

## Dataset and target

The application dataset is `data/processed/delitos_procesado.csv`. It contains 66,400 rows and 20 columns. Rows are aggregated by offense, period, and territory; `total_procesos` is an aggregate count. The target `categoria` was created by an approximate mapping from legal offense text. It is therefore an imperfect label, and the rows are not independent incident-level observations.

The target distribution is imbalanced:

| Category | Rows |
| --- | ---: |
| `HURTO_ELECTRONICO` | 20,473 |
| `ACCESO_ABUSIVO` | 15,990 |
| `DATOS_PERSONALES` | 12,911 |
| `PHISHING_SUPLANTACION` | 5,694 |
| `FRAUDE_TRANSFERENCIA` | 4,921 |
| `ATAQUE_A_SISTEMAS` | 4,725 |
| `MALWARE` | 982 |
| `EQUIPOS_MOVILES` | 375 |
| `NO_ESPECIFICADO` | 329 |

## Inputs and preprocessing

The model uses `criminalidad`, `departamento_hecho`, `municipio_hecho`, `seccional`, `ano_hechos`, `ano_entrada`, `ano_denuncia`, and `anio_parcial`. `delito` and `articulo` were excluded because they contribute directly to the target mapping. Legal text derivatives, aggregate counts, and case outcome fields were also excluded.

Each saved scikit-learn pipeline imputes numeric values with the median, scales numeric values, imputes categorical values with the most frequent value, and applies one-hot encoding. Unseen categories are ignored by the encoder. Classifiers use balanced class weights. The web form restricts inputs to observed categorical values and numeric ranges in the training dataset.

## Models and saved evaluation

The artifacts compare Decision Tree, Random Forest, and Logistic Regression using a stratified 80/20 split with `random_state=42` (53,120 training rows and 13,280 test rows).

| Model | Accuracy | Macro precision | Macro recall | Macro F1 | Weighted F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Decision Tree | 0.1422 | 0.1265 | 0.1804 | 0.1123 | 0.1613 |
| Random Forest | 0.1717 | 0.1461 | 0.2322 | 0.1326 | 0.1935 |
| Logistic Regression | 0.1398 | 0.1513 | 0.2481 | 0.1176 | 0.1625 |

The stored artifact selects Logistic Regression using a score that combines macro F1 (40%), macro precision (20%), macro recall (20%), and average recall across classes below 2% prevalence (20%). The selected model favors minority-class recall and macro precision, while Random Forest has the best accuracy and macro F1 in the saved comparison.

## Evaluation limitation

The current training procedure calculates the selection score from the same test results shown above. The test split therefore influenced model selection and is not an untouched final evaluation set. Do not describe these results as an unbiased estimate of future performance. For a final evaluation, select hyperparameters and models on training/validation data, freeze the choice, and evaluate once on a held-out test set. Consider a temporal or group-based split because rows can share territory, period, and other patterns.

The saved macro F1 is 0.1176 and accuracy is 0.1398. These are low scores. Probabilities shown in the application come from `predict_proba`; no probability calibration has been performed, so they should not be interpreted as calibrated confidence.

## Artifacts

- `models/best_model.joblib`: selected preprocessing and classifier pipeline used by the application.
- `models/best_model_info.json`: feature schema, class counts, training split, selection rule, and saved metrics.
- `reports/model_comparison.csv`: model-level metrics.
- `reports/classification_reports/`: per-class metrics.
- `reports/confusion_matrices/`: confusion matrices for each model.

Serialized models were generated with scikit-learn 1.8.0. Load them with that version to avoid compatibility warnings or unsupported behavior.

## Application behavior and scope

`src/predict.py` loads the saved pipeline and returns the predicted class and class probabilities. The Flask application validates form values and stores inputs and results in the signed-in user's history. These predictions demonstrate model inference only. They are not suitable for law enforcement, legal, or resource allocation decisions.

The separate phishing dataset mentioned by the analysis project is not included in the repository and is not used by this classifier.
