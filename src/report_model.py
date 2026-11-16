"""Inference for the incident report classifier plus the plain-language
information shown to the citizen after each report."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import joblib

from src.report_features import to_frame

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models/report_classifier.joblib"
INFO_PATH = ROOT / "models/report_classifier_info.json"

CATEGORY_INFO: dict[str, dict] = {
    "ELECTRONIC_THEFT": {
        "label": "Electronic theft",
        "summary": "Money was taken from your account or card without your authorization.",
        "law": "Law 1273 of 2009, article 269I",
        "steps": ["Call your bank now and block the card or account.",
                  "Ask the bank for a written record of the unrecognised transactions.",
                  "Change your online banking password and turn on alerts."],
    },
    "TRANSFER_FRAUD": {
        "label": "Transfer fraud",
        "summary": "You were deceived into sending money or assets to someone else.",
        "law": "Law 1273 of 2009, article 269J",
        "steps": ["Contact your bank immediately and ask to stop or reverse the transfer.",
                  "Save chats, receipts, phone numbers and account numbers you paid to.",
                  "Do not send more money, even if they promise to refund you."],
    },
    "PHISHING_SPOOFING": {
        "label": "Phishing or spoofed website",
        "summary": "A fake message or website tried to capture your personal or bank details.",
        "law": "Law 1273 of 2009, article 269G",
        "steps": ["Change the passwords you typed, starting with email and banking.",
                  "Turn on two-step verification on your important accounts.",
                  "Keep the message or a screenshot of the fake page as evidence."],
    },
    "ABUSIVE_ACCESS": {
        "label": "Unauthorized account access",
        "summary": "Someone entered one of your accounts or systems without permission.",
        "law": "Law 1273 of 2009, article 269A",
        "steps": ["Use the platform's account recovery option right away.",
                  "Change the password and close all other active sessions.",
                  "Warn your contacts not to answer requests for money from that account."],
    },
    "PERSONAL_DATA": {
        "label": "Personal data violation",
        "summary": "Your personal information was obtained, published or used without consent.",
        "law": "Law 1273 of 2009, article 269F",
        "steps": ["Write down where your data appeared and take screenshots.",
                  "Ask the company or platform to remove it (right to deletion, Law 1581 of 2012).",
                  "Check your credit report for products you did not request."],
    },
    "MALWARE": {
        "label": "Malicious software",
        "summary": "A virus, ransomware or harmful app affected your device.",
        "law": "Law 1273 of 2009, article 269E",
        "steps": ["Disconnect the device from the internet and do not pay any ransom.",
                  "Run a trusted antivirus or ask a technician to clean the device.",
                  "Change your passwords from a different, clean device."],
    },
    "SYSTEM_ATTACK": {
        "label": "Attack on a computer system",
        "summary": "A website, server or information system was blocked, damaged or intercepted.",
        "law": "Law 1273 of 2009, articles 269B to 269D",
        "steps": ["Preserve logs and do not erase evidence on affected servers.",
                  "Isolate the affected systems and restore from clean backups.",
                  "Organisations should also notify ColCERT, Colombia's national CERT."],
    },
    "MOBILE_DEVICES": {
        "label": "Tampered mobile device",
        "summary": "The identity (IMEI) of a phone was altered, usually after a theft.",
        "law": "Law 1453 of 2011, article 105",
        "steps": ["Ask your mobile operator to block the IMEI of the stolen phone.",
                  "Keep the purchase invoice and the box with the original IMEI.",
                  "Do not buy phones without an invoice or with a changed IMEI."],
    },
}
UNSURE = {
    "label": "Needs analyst review",
    "summary": "The description could match more than one type of incident. An analyst will classify it.",
    "law": "To be defined by the analyst",
    "steps": ["Keep every piece of evidence: screenshots, receipts, numbers and links.",
              "If money is involved, call your bank right away.",
              "Change the passwords of any account that may be affected."],
}


@lru_cache(maxsize=1)
def load_model():
    return joblib.load(MODEL_PATH)


@lru_cache(maxsize=1)
def model_info() -> dict:
    try:
        return json.loads(INFO_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def model_available() -> bool:
    return MODEL_PATH.exists() and INFO_PATH.exists()


def classify_report(description: str, channel: str, affected: list[str]) -> dict:
    """Return the predicted category, its confidence and the top alternatives."""
    model = load_model()
    frame = to_frame([{"description": description, "channel": channel, "affected": affected}])
    probabilities = model.predict_proba(frame)[0]
    ranked = sorted(zip(model.classes_, probabilities), key=lambda pair: pair[1], reverse=True)
    category, confidence = ranked[0]
    threshold = float(model_info().get("low_confidence_threshold", 0.45))
    return {
        "category": str(category),
        "confidence": float(confidence),
        "needs_review": float(confidence) < threshold,
        "alternatives": [{"category": str(c), "probability": float(p)} for c, p in ranked[1:3]],
        "model_version": f"{model_info().get('algorithm', 'unknown')}@{model_info().get('version', '-')}",
    }


def category_info(category: str | None) -> dict:
    return CATEGORY_INFO.get(category or "", UNSURE)
