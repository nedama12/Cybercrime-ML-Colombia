import json

import pytest

from cyberapp.extensions import db
from cyberapp.ml.drift import psi
from cyberapp.ml.features import InvalidURL, build_model_input, extract_url_features, normalize_url
from cyberapp.ml.service import risk_level
from cyberapp.models import Prediction, RequestLog, User


def test_features_match_a_known_dataset_row():
    # Row of data/processed/phishing_processed.csv (phishing, test partition)
    values = extract_url_features("https://bancolombia.com1home0892.repl.co/?2")
    assert values["URLLength"] == 43 and values["DomainLength"] == 32
    assert values["NoOfLettersInURL"] == 24 and values["NoOfDegitsInURL"] == 6
    assert values["NoOfOtherSpecialCharsInURL"] == 4 and values["NoOfQMarkInURL"] == 1
    assert values["NoOfSubDomain"] == 2 and values["IsHTTPS"] == 1 and values["TLDLength"] == 2


def test_ip_and_obfuscation_features():
    values = extract_url_features("http://192.168.10.5/%61%64min")
    assert values["IsDomainIP"] == 1 and values["IsHTTPS"] == 0
    assert values["NoOfObfuscatedChar"] == 2 and values["HasObfuscation"] == 1


def test_build_model_input_reports_missing_and_manual_features():
    values, sources, missing = build_model_input("https://x.co/a", ["URLLength", "HasTitle", "NoOfJS"],
                                                 {"HasTitle": "1"})
    assert values == {"URLLength": 14, "HasTitle": 1.0}
    assert sources == {"URLLength": "computed", "HasTitle": "manual"} and missing == ["NoOfJS"]


@pytest.mark.parametrize("url", ["", "ftp://x.com", "x.com", "https://nodot"])
def test_invalid_urls(url):
    with pytest.raises(InvalidURL):
        normalize_url(url)


def test_risk_levels():
    assert risk_level(0.95, 0.5) == "high"
    assert risk_level(0.6, 0.5) == "medium"
    assert risk_level(0.2, 0.5) == "low"


def test_prediction_is_stored_with_user_date_result_and_version(reported_case, login):
    case_id, _ = reported_case
    login("analyst").post(f"/cases/{case_id}/classify")
    prediction = Prediction.query.one()
    analyst = User.query.filter_by(username="analyst").one()
    assert prediction.case_id == case_id and prediction.user_id == analyst.id
    assert prediction.model_version == "9.9.9" and prediction.created_at is not None
    assert prediction.label in ("phishing", "legitimate") and 0 <= prediction.probability <= 1
    assert set(json.loads(prediction.features_json)) >= {"URLLength", "IsHTTPS"}


def test_reporter_cannot_run_the_model(reported_case):
    case_id, reporter = reported_case
    assert reporter.post(f"/cases/{case_id}/classify").status_code == 403
    assert Prediction.query.count() == 0


def test_quick_check_and_open_case(login):
    analyst = login("analyst")
    response = analyst.post("/predictions/check", data={"url": "https://www.example.com/"})
    assert b"phishing probability" in response.data
    prediction = Prediction.query.one()
    response = analyst.post(f"/predictions/{prediction.id}/open-case", data={"channel": "sms"})
    assert response.status_code == 302 and db.session.get(Prediction, prediction.id).case_id is not None


def test_system_works_without_a_model(app_without_model):
    client = app_without_model.test_client()
    client.post("/auth/login", data={"username": "analyst", "password": "Secret123"})
    assert b"No model deployed" in client.get("/model").data
    assert client.get("/healthz").get_json()["model_ready"] is False


def test_requests_are_logged_with_response_time(login):
    login("reporter").get("/cases/")
    log = RequestLog.query.filter_by(endpoint="cases.index").first()
    assert log is not None and log.status_code == 200 and log.latency_ms >= 0


def test_psi_detects_a_shifted_distribution():
    edges, props = [None, 10.0, 20.0, None], [1 / 3, 1 / 3, 1 / 3]
    assert psi(props, edges, [5, 15, 25] * 20) < 0.01
    assert psi(props, edges, [25] * 60) > 0.25


def test_csv_export_neutralizes_formulas(app, login):
    from cyberapp.blueprints.reports import _safe
    assert _safe("=cmd|calc") == "'=cmd|calc" and _safe("https://x.co") == "https://x.co"
    assert login("analyst").get("/reports/export/predictions.csv").mimetype == "text/csv"
