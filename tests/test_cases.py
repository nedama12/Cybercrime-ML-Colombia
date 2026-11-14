from cyberapp.extensions import db
from cyberapp.models import CaseStatus, UrlCase


def test_report_validates_the_url(login):
    client = login("reporter")
    for bad, message in (("example.com", b"Include the scheme"), ("https://a b.com", b"cannot contain spaces"),
                         ("http://localhost", b"must include a domain")):
        response = client.post("/cases/new", data={"url": bad, "channel": "email"})
        assert message in response.data
    assert UrlCase.query.count() == 0


def test_duplicate_open_report_is_not_created(reported_case):
    case_id, client = reported_case
    response = client.post("/cases/new", data={"url": "https://secure-login.example.xyz/verify?id=12345",
                                               "channel": "sms"})
    assert response.headers["Location"].endswith(f"/cases/{case_id}")
    assert UrlCase.query.count() == 1


def test_reporters_only_see_their_own_cases(reported_case, login):
    case_id, _ = reported_case
    assert login("other").get(f"/cases/{case_id}").status_code == 403
    assert b"secure-login" not in login("other").get("/cases/").data
    assert login("analyst").get(f"/cases/{case_id}").status_code == 200


def test_reporter_edits_and_deletes_only_new_cases(reported_case, login):
    case_id, client = reported_case
    assert client.post(f"/cases/{case_id}/edit", data={"url": "https://secure-login.example.xyz/v2",
                                                       "channel": "sms"}).status_code == 302
    login("analyst").post(f"/cases/{case_id}/classify")
    assert client.get(f"/cases/{case_id}/edit").status_code == 403
    assert client.post(f"/cases/{case_id}/delete").status_code == 403
    assert login("analyst").post(f"/cases/{case_id}/delete").status_code == 403
    assert login("admin").post(f"/cases/{case_id}/delete").status_code == 302
    assert db.session.get(UrlCase, case_id) is None


def test_full_workflow_from_report_to_closure(reported_case, login):
    case_id, _ = reported_case
    analyst = login("analyst")
    analyst.post(f"/cases/{case_id}/classify")
    case = db.session.get(UrlCase, case_id)
    assert case.status == CaseStatus.CLASSIFIED and case.priority in ("low", "medium", "high")

    analyst.post(f"/cases/{case_id}/review")
    assert db.session.get(UrlCase, case_id).status == CaseStatus.UNDER_REVIEW

    model_label = case.latest_prediction.label
    action = "blocked" if model_label == "phishing" else "dismissed"
    analyst.post(f"/cases/{case_id}/resolve", data={"actual_label": model_label, "action_taken": action})
    case = db.session.get(UrlCase, case_id)
    assert case.status == CaseStatus.CLOSED and case.closed_at is not None and case.model_agrees is True


def test_resolution_business_rules(reported_case, login):
    case_id, _ = reported_case
    analyst = login("analyst")
    response = analyst.post(f"/cases/{case_id}/resolve", data={"actual_label": "phishing", "action_taken": "blocked"},
                            follow_redirects=True)
    assert b"Classify the case with the model first" in response.data

    analyst.post(f"/cases/{case_id}/classify")
    incoherent = analyst.post(f"/cases/{case_id}/resolve", data={"actual_label": "legitimate", "action_taken": "blocked"})
    assert b"not coherent" in incoherent.data

    model_label = db.session.get(UrlCase, case_id).latest_prediction.label
    other = "legitimate" if model_label == "phishing" else "phishing"
    action = "dismissed" if other == "legitimate" else "blocked"
    no_notes = analyst.post(f"/cases/{case_id}/resolve", data={"actual_label": other, "action_taken": action})
    assert b"Explain why you disagree" in no_notes.data
    assert db.session.get(UrlCase, case_id).status != CaseStatus.CLOSED
