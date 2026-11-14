"""Simulated operational data for demonstrations and the initial monitoring test.

Every record created here has is_simulated = True and is shown with a SIMULATED badge.
The URLs are fictitious examples; do not open them.
"""
import random
from datetime import timedelta

from .extensions import db
from .ml.inference import MissingFeatures, classify
from .ml.service import get_model_service
from .models import CHANNELS, CaseStatus, Role, UrlCase, User, utcnow

DEMO_URLS = [
    # Phishing-like (fictitious)
    "http://bancolombia-verificacion-cuenta.weebly.com/login.php",
    "https://davivienda-seguridad.web.app/actualizar-datos",
    "http://192.168.45.10/nequi/validar?usuario=3001234567",
    "https://dian-devolucion-saldo.xyz/formulario?id=88231",
    "https://secure-paypal-account-update.top/signin?session=91x2",
    "http://netflix-pago-rechazado.repl.co/billing",
    "https://login-microsoftonline-verify.workers.dev/oauth2/authorize",
    "http://interrapidisimo-entrega-pendiente.click/pago",
    "https://whatsapp-verificacion-codigo.firebaseapp.com/",
    "http://amazon-co-premio-ganador.info/reclamar?ref=556",
    "https://banco-bogota-token.weeblysite.com/clave",
    "http://simit-multas-pendientes.online/consulta?placa=ABC123",
    # Legitimate
    "https://www.unal.edu.co",
    "https://www.gov.co",
    "https://www.dian.gov.co",
    "https://www.ucundinamarca.edu.co",
    "https://www.bancolombia.com",
    "https://www.colombiacompra.gov.co",
    "https://github.com/pallets/flask",
    "https://www.datos.gov.co",
]


def _demo_user(username, role, password):
    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, email=f"{username}@demo.local", role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
    return user


def seed(password, cases=40, days=14, seed_value=7):
    """Create demo users, cases and predictions spread over the last `days` days."""
    rng = random.Random(seed_value)
    reporter = _demo_user("demo_reporter", Role.REPORTER, password)
    analyst = _demo_user("demo_analyst", Role.ANALYST, password)
    model_ready = get_model_service().ready
    created = classified = closed = 0

    for _ in range(cases):
        url = rng.choice(DEMO_URLS)
        when = utcnow() - timedelta(days=rng.uniform(0, days))
        case = UrlCase(url=url, domain=url.split("//", 1)[1].split("/", 1)[0].lower(),
                       channel=rng.choice(CHANNELS)[0], description="Simulated report for demonstration.",
                       reporter_id=reporter.id, created_at=when, updated_at=when, is_simulated=True)
        db.session.add(case)
        db.session.commit()
        created += 1
        if not model_ready or rng.random() < 0.15:  # some cases stay new
            continue
        try:
            prediction = classify(url, analyst, case=case, simulated=True)
        except MissingFeatures:
            continue
        prediction.created_at = when + timedelta(minutes=rng.randint(5, 240))
        classified += 1
        if rng.random() < 0.6:
            # Simulated analyst verdict: agrees with the model most of the time.
            truth = prediction.label if rng.random() < 0.85 else (
                "legitimate" if prediction.label == "phishing" else "phishing")
            case.move_to(CaseStatus.CLOSED)
            case.actual_label = truth
            case.action_taken = "blocked" if truth == "phishing" else "dismissed"
            case.assignee_id = analyst.id
            case.closed_at = prediction.created_at + timedelta(hours=rng.uniform(0.5, 30))
            case.resolution_notes = "Simulated resolution."
            closed += 1
        db.session.commit()
    return {"cases": created, "classified": classified, "closed": closed, "model_ready": model_ready}


def clear():
    """Remove every simulated record (cases cascade their predictions' case link)."""
    from .models import Prediction
    n_pred = Prediction.query.filter_by(is_simulated=True).delete()
    n_case = UrlCase.query.filter_by(is_simulated=True).delete()
    db.session.commit()
    return n_case, n_pred
