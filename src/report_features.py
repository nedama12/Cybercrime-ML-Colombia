"""Shared feature definition for the incident report classifier.

Training (src/train_report_model.py) and inference (src/report_model.py) both
build the model input with `to_frame`, so the platform always sends the model
exactly the columns it was trained with.
"""
from __future__ import annotations

import pandas as pd

CHANNELS = {
    "phone_call": "Phone call",
    "sms_whatsapp": "Text message or WhatsApp",
    "email": "Email",
    "social_media": "Social media",
    "website_app": "Website or app",
    "device": "My phone or computer",
    "unknown": "I am not sure",
}
AFFECTED = {
    "money": "Money",
    "account": "An online account",
    "personal_data": "Personal data",
    "device": "A phone or computer",
    "business_system": "A company system or website",
}
AFFECTED_COLUMNS = [f"affected_{key}" for key in AFFECTED]
TEXT_COLUMN = "description"
FEATURES = [TEXT_COLUMN, "channel", *AFFECTED_COLUMNS]


def to_frame(records: list[dict]) -> pd.DataFrame:
    """Turn report dicts into the model input.

    Each record has `description` (str), `channel` (str) and `affected`
    (list of keys or a ';'-separated string).
    """
    rows = []
    for record in records:
        affected = record.get("affected") or []
        if isinstance(affected, str):
            affected = [item for item in affected.split(";") if item]
        row = {TEXT_COLUMN: str(record.get("description", "")).strip(),
               "channel": record.get("channel") if record.get("channel") in CHANNELS else "unknown"}
        for key in AFFECTED:
            row[f"affected_{key}"] = int(key in affected)
        rows.append(row)
    return pd.DataFrame(rows, columns=FEATURES)
