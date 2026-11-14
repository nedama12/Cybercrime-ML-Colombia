"""Editable PGC project information shown on the public pages.

Keep this file in sync with the approved PGC proposal (Annex 1 format).
"""

PROJECT = {
    "title": "Cybercrime Analysis and Prediction in Colombia Using Machine Learning",
    "short_title": "Cybercrime Analytics Colombia",
    "university": "Universidad de Cundinamarca - Faculty of Engineering",
    "program": "Systems and Computing Engineering",
    "campus": "[Campus]",
    "project_type": "Technological project (information system with an integrated ML model)",
    "cycle": "[Cycle]",
    "period": "2026-2",
    "research_line": "Learning, knowledge, technologies, communication and digitalization",
    "team": [
        {"name": "[Team member 1]", "role": "Data Engineering", "email": "[institutional email]"},
        {"name": "[Team member 2]", "role": "Model Engineering", "email": "[institutional email]"},
        {"name": "[Team member 3]", "role": "Application Engineering", "email": "[institutional email]"},
    ],
    "problem": (
        "Cybercrime reports in Colombia keep growing: the Attorney General's Office open data "
        "records more than 565,000 cybercrime cases (Law 1273 of 2009) between 2010 and 2026, "
        "and website spoofing to capture personal data (article 269G, phishing) is one of the "
        "fastest-growing offenses. Citizens and institutions receive suspicious links every day "
        "through email, SMS and social media, but reviewing each one manually is slow and depends "
        "on expert knowledge that is not always available."
    ),
    "justification": (
        "A web information system that receives reports of suspicious URLs, classifies them with a "
        "Machine Learning model and lets analysts confirm the outcome turns scattered reports into "
        "a traceable process. It prioritizes the most dangerous links, records every decision and "
        "produces indicators that support prevention, while the Colombian open data gives context "
        "about where and how cybercrime is reported."
    ),
    "general_objective": (
        "Develop a web information system that manages reports of suspicious URLs and integrates a "
        "Machine Learning model to classify them as phishing or legitimate, documenting the whole "
        "process with the CRISP-ML methodology."
    ),
    "specific_objectives": [
        ("Understand and prepare the data",
         "Characterize Colombian cybercrime open data and a labeled phishing URL dataset, and prepare them without data leakage."),
        ("Train and evaluate models",
         "Compare Decision Tree, Random Forest and Logistic Regression classifiers and select the best one on an independent test set."),
        ("Deploy and operate the system",
         "Publish a Flask system with authentication, roles, case management, inference history, reports and monitoring."),
    ],
    "products": ["PGC synthesis document", "Software", "Information system", "Web development"],
}

PHASES = [
    {"number": 1, "slug": "business-data-understanding", "title": "Business and Data Understanding",
     "summary": "Problem, stakeholders, objectives, data sources, quality and success criteria."},
    {"number": 2, "slug": "data-engineering", "title": "Data Engineering",
     "summary": "Cleaning, feature selection, transformations and leakage-free partitions."},
    {"number": 3, "slug": "model-engineering", "title": "Model Engineering",
     "summary": "Algorithms compared, training configuration and hyperparameter tuning."},
    {"number": 4, "slug": "model-evaluation", "title": "Model Evaluation",
     "summary": "Metrics, cross-validation, error analysis and final test-set performance."},
    {"number": 5, "slug": "model-deployment", "title": "Model Deployment",
     "summary": "Saved artifacts, Flask inference, inputs, outputs and integration plan."},
    {"number": 6, "slug": "monitoring-maintenance", "title": "Monitoring and Maintenance",
     "summary": "Indicators, drift detection, review frequency and retraining criteria."},
]
