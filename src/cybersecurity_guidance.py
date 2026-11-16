"""Transparent, rule-based first-response guidance for common cyber incidents."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    keywords: tuple[str, ...]
    immediate: tuple[tuple[str, str], ...]
    avoid: tuple[str, ...]
    contain: tuple[str, ...]
    recover: tuple[str, ...]
    protect: tuple[str, ...]
    prevent: tuple[str, ...]
    contact: tuple[str, ...]
    evidence: tuple[str, ...]


SCENARIOS = {
    "phishing": Scenario("phishing", "Phishing or suspicious link",
        ("phishing", "suspicious link", "suspicious email", "correo sospechoso", "enlace sospechoso", "mensaje sospechoso"),
        (("Do not open the link or download its files.", "This prevents the message from installing malware or taking you to a credential theft page."),
         ("Verify the sender through a separate, known channel.", "A familiar display name can be spoofed; an independent check helps confirm the request.")),
        ("Do not enter credentials, payment details, or one-time codes.", "Do not reply or forward the message to other people."),
        ("Use the provider's report-phishing and block controls.", "If you downloaded a file, do not open it and run a scan with trusted security software."),
        ("If you entered a password, change it from a trusted device, revoke active sessions, enable multifactor authentication, and review recovery methods.", "Change any reused password. Contact the provider through its official recovery page if you lost access."),
        ("Review account activity and recovery email/phone for changes you did not make."),
        ("Use a password manager, unique passwords, and multifactor authentication; open services from saved bookmarks."),
        ("Contact the affected service through its official support channel if an account or payment method is involved."),
        ("Keep the original message, sender address, timestamp, and URL as text or a screenshot; redact personal details before sharing.")),
    "account": Scenario("account", "Account theft or unauthorized access",
        ("account stolen", "stolen account", "account hacked", "robo de cuenta", "cuenta robada", "unauthorized access", "acceso no autorizado", "account compromised"),
        (("Start account recovery using the service's official website or app.", "Official recovery avoids handing control to an impersonator."),
         ("From a trusted device, change the account password and revoke unknown sessions/devices.", "This blocks further access using stolen credentials or sessions.")),
        ("Do not share passwords or authentication codes with anyone, including people claiming to be support."),
        ("Secure the linked email account and phone number first if they control account recovery.", "Remove unknown forwarding rules, recovery methods, apps, and devices."),
        ("Enable multifactor authentication and review recent activity and recovery details.", "Change reused passwords on other services."),
        ("Check messages, transactions, and settings for changes made by the intruder."),
        ("Use unique passwords, multifactor authentication, and recovery details you still control."),
        ("Contact the platform's official support if recovery fails; contact your bank immediately if financial access is involved."),
        ("Save security alerts, timestamps, and screenshots of unauthorized activity.")),
    "fraud": Scenario("fraud", "Transfer or payment fraud",
        ("transfer fraud", "fraud by transfer", "fraude por transferencia", "transferencia fraudulenta", "unauthorized transfer", "transferencia no autorizada", "payment fraud", "estafa transferencia"),
        (("Contact your bank immediately using the number on your card or its official app/site.", "Fast reporting lets the bank review the transaction and secure affected access."),
         ("Ask the bank to register a fraud report and review whether the operation or instruments can be blocked.", "The bank can explain the available actions for this specific payment.")),
        ("Do not pay anyone who promises guaranteed recovery, and do not share banking passwords or OTP codes."),
        ("Ask the bank to block compromised cards, tokens, or digital access and secure your account."),
        ("Follow the bank's case instructions and monitor the account for further activity.", "Recovery of funds is not guaranteed."),
        ("Change exposed banking credentials from a trusted device and enable available security alerts."),
        ("Use official banking apps/sites, transaction alerts, and an independent confirmation before transfers."),
        ("In Colombia, consult official Fiscalía/CAI Virtual channels for reporting guidance, in addition to contacting your bank."),
        ("Keep transaction receipts, date/time, amount, recipient details, bank case number, and relevant conversations.")),
    "malware": Scenario("malware", "Possible malware or infected device",
        ("malware", "ransomware", "virus", "infected device", "infected computer", "equipo infectado", "software malicioso"),
        (("If compromise may be active, disconnect the device from Wi-Fi and wired networks.", "Isolation can limit communication with an attacker and spread to other systems."),
         ("Do not enter new passwords on the affected device.", "Malware may capture credentials typed on it.")),
        ("Do not pay a ransom or install cleanup tools from unsolicited links.", "Avoid deleting files or logs if an investigation may be needed."),
        ("Keep the device isolated and tell your IT/security team if it belongs to an organization."),
        ("Use trusted security support to inspect and clean or rebuild the device; restore only known-clean backups.", "Change exposed credentials from a separate clean device."),
        ("Check accounts accessed from the device and enable multifactor authentication."),
        ("Keep software updated, use reputable security tools, and maintain offline or protected backups."),
        ("Seek qualified technical help if files are encrypted, business systems are affected, or the infection returns."),
        ("Record warning messages, times, affected devices, and actions already taken; preserve relevant logs.")),
    "identity": Scenario("identity", "Identity impersonation or personal data exposure",
        ("identity theft", "identity impersonation", "suplantación de identidad", "suplantacion de identidad", "impersonation", "personal data stolen", "robo de identidad", "datos personales expuestos"),
        (("Save evidence of the fake profile, message, or exposed information.", "The original evidence can support platform reports and follow-up."),
         ("Report the account or publication using the platform's official reporting tools.", "This starts the platform's review and removal process.")),
        ("Do not confront the impersonator with more personal information or pay for removal promises."),
        ("Contact affected services, banks, or institutions through their official channels and secure related accounts."),
        ("Review account recovery details and activity; change exposed or reused passwords from a trusted device."),
        ("Warn close contacts through a separate channel if the impersonator is contacting them."),
        ("Limit public personal details and use multifactor authentication and unique passwords."),
        ("Consult official Fiscalía/CAI Virtual guidance in Colombia; seek legal advice for case-specific questions."),
        ("Keep URLs, profile names, dates, message headers, and screenshots; avoid publishing sensitive evidence.")),
}

GENERIC = Scenario("general", "Cybersecurity concern",
    ("fraud", "scam", "fraude", "scam", "attack", "ataque", "information stolen", "información robada", "password exposed", "contraseña expuesta", "data loss", "pérdida de información", "platform fraud", "fraude en plataforma", "system attack", "ataque a sistemas"),
    (("Stop interacting with suspicious messages, files, or callers.", "This avoids giving an attacker more access or information."),
     ("Secure affected accounts from a trusted device and contact the relevant provider through official channels.", "The provider can contain access using account-specific controls.")),
    ("Do not share passwords, OTP codes, full banking details, or remote access with anyone."),
    ("Disconnect a device only if malware may be active; otherwise preserve access while securing the account."),
    ("Change exposed passwords, revoke unknown sessions, enable multifactor authentication, and restore data from a known-clean backup if needed."),
    ("Review affected accounts, devices, and recovery methods for unauthorized changes."),
    ("Keep software updated, maintain protected backups, and use unique passwords with multifactor authentication."),
    ("Contact your bank immediately for an active or completed financial fraud; seek qualified technical support for compromised systems."),
    ("Save dates, messages, URLs, screenshots, and transaction references without sharing secrets."))

SECTION_EXPLANATIONS = {
    "immediate": ("This addresses the most time-sensitive exposure first.", "The immediate risk is reduced so you can continue with the next steps."),
    "contain": ("Containment limits further access, spread, or transactions while you investigate.", "The incident has less room to affect other accounts, devices, or funds."),
    "recover": ("Recovery restores control through the provider's trusted process and removes unauthorized access where possible.", "You can regain control and check that recovery channels are yours."),
    "protect": ("Protecting related information reduces follow-on misuse of exposed data or accounts.", "Other accounts and personal information are less exposed to the same compromise."),
    "prevent": ("Preventive controls make common repeat attempts harder to succeed.", "The same route is less likely to work again."),
    "contact": ("The organization that controls the affected account, funds, or system can apply case-specific controls.", "You receive next steps from the service responsible for the affected resource."),
    "evidence": ("A clear record preserves details that can disappear when messages or accounts change.", "You have useful information for a bank, provider, technician, or reporting channel."),
    "avoid": ("Avoiding these actions prevents additional information or control from reaching an attacker.", "You reduce the chance of worsening the incident while responding."),
}

WHAT_IT_MEANS = {
    "phishing": "A message or website may be impersonating a trusted source to obtain information or prompt an unsafe action. The message and destination have not been independently verified here.",
    "account": "There may be unauthorized access to an account. Only the service provider can confirm access records and restore control.",
    "fraud": "A payment or transfer may be fraudulent. Your bank must verify the transaction and explain available controls; recovery is not guaranteed.",
    "malware": "A device may have run harmful software. Its presence and impact cannot be confirmed from this description.",
    "identity": "Someone may be using personal details or impersonating you. The platform or affected institution must review the specific evidence.",
    "general": "The description indicates a possible security concern, but there is not enough verified information to diagnose its cause or impact.",
}


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _action_sections(scenario: Scenario, immediate: list) -> list[dict]:
    sections = []
    for title, key, steps in (
        ("Do this now", "immediate", immediate), ("Contain the incident", "contain", scenario.contain),
        ("Recover control", "recover", scenario.recover), ("Protect information", "protect", scenario.protect),
        ("Prevent recurrence", "prevent", scenario.prevent), ("Contact support", "contact", scenario.contact),
        ("Preserve evidence", "evidence", scenario.evidence), ("Avoid", "avoid", scenario.avoid),
    ):
        why, outcome = SECTION_EXPLANATIONS[key]
        annotated = []
        for item in steps:
            instruction, item_why = item if isinstance(item, tuple) else (item, why)
            annotated.append({"instruction": instruction, "why": item_why, "outcome": outcome})
        sections.append({"title": title, "steps": annotated})
    return sections


def assess_situation(problem: str, description: str, status: str,
                     exposures: list[str] | None = None) -> dict:
    """Return a cautious rule-based checklist; submitted descriptions are not persisted."""
    problem = problem.strip().lower()
    description = " ".join(description.split())[:2000]
    exposures = set(exposures or [])
    text = f"{problem} {description}".lower()
    if len(description) < 12 and problem in {"", "other"}:
        return {"needs_clarification": True,
                "clarification": "Please describe what happened, which account/device/service is affected, and whether you clicked a link, shared a password, or lost money. Do not include passwords, OTP codes, or full banking details."}
    aliases = {"personal_data": "identity", "unauthorized": "account",
               "suspicious_website": "phishing",
               "attack": "general", "data_loss": "general", "platform_fraud": "fraud"}
    scenario = SCENARIOS.get(aliases.get(problem, problem))
    if scenario is None:
        scenario = next((item for item in SCENARIOS.values() if _contains_any(text, item.keywords)), None)
    if scenario is None:
        scenario = GENERIC if problem in {"other", ""} else GENERIC
        if len(description) < 30:
            return {"needs_clarification": True,
                    "clarification": "What happened, is it happening now, and what account, device, or service is affected? Please omit secrets and full financial details."}

    financial = scenario.key == "fraud" or "sent_money" in exposures or _contains_any(text, ("transferred money", "sent money", "transferí", "transferi", "dinero", "payment made"))
    credentials = bool(exposures & {"entered_password", "shared_code"}) or _contains_any(text, ("entered my password", "shared my password", "typed my password", "entered credentials", "ingresé mi contraseña", "ingrese mi contraseña", "compartí mi contraseña", "shared otp", "shared code"))
    lost_access = "lost_account" in exposures or _contains_any(text, ("lost access", "can't access", "cannot access", "perdí el acceso", "no puedo acceder"))
    opened_file = bool(exposures & {"downloaded_file", "opened_file"})
    clicked_link = "clicked_link" in exposures
    active = status == "active" or _contains_any(text, ("right now", "currently", "happening now", "en este momento", "ahora mismo", "ongoing"))
    post = status == "post" or financial or credentials or lost_access or opened_file or _contains_any(text, ("already clicked", "already paid", "ya hice clic", "ya pagué", "ya pague"))
    state = "ACTIVE INCIDENT" if active else "POST-INCIDENT" if post else "PREVENTION"
    urgency = "Critical" if financial or lost_access or (active and scenario.key in {"account", "malware", "identity"}) else "High" if credentials or opened_file or (active and clicked_link) or post else "Moderate" if state == "ACTIVE INCIDENT" else "Low"
    urgency_reason = ("A transfer/payment was reported, so bank action is time-sensitive." if financial else
                      "Account access is lost or appears controlled by someone else." if lost_access else
                      "A password or authentication code may be exposed." if credentials else
                      "A file was downloaded or opened and may need device containment." if opened_file else
                      "The incident is reported as active and could still affect an account or device." if active else
                      "No immediate compromise indicator was selected; use prevention steps and reassess if anything changes.")
    immediate = list(scenario.immediate)
    if financial:
        immediate.insert(0, ("Contact your bank immediately using its official app or the number on your card.", "The bank can register the case and secure affected instruments; a refund is not guaranteed."))
    if credentials and scenario.key == "phishing":
        immediate.insert(0, ("Change the exposed password now from a trusted device, then revoke active sessions.", "This reduces the chance that the submitted credential remains usable."))
    if lost_access and scenario.key == "account":
        immediate.insert(0, ("Use the provider's official account recovery flow now and secure the linked email account.", "Attackers often keep control through recovery settings or active sessions."))
    if opened_file:
        immediate.insert(0, ("Do not open the file again. If it was executed or the device behaves unexpectedly, disconnect it from networks and use a clean device for account changes.", "This limits possible further execution or credential exposure while the device is assessed."))
    if clicked_link and not credentials and not opened_file:
        immediate.insert(0, ("Close the page. If you did not enter information or download anything, do not interact with it further; check the device and account for unusual activity.", "A click alone does not prove compromise, but continued interaction can increase exposure."))
    if "danger" in text or "physical threat" in text or "infraestructura crítica" in text:
        urgency = "Critical"
        immediate.insert(0, ("Move people to safety and contact the appropriate emergency or organizational response service.", "Personal safety and infrastructure continuity take priority."))
    return {"needs_clarification": False, "scenario": scenario, "state": state, "urgency": urgency,
            "urgency_reason": urgency_reason,
            "what_it_means": WHAT_IT_MEANS.get(scenario.key, WHAT_IT_MEANS["general"]),
            "risk": "Potential account, device, personal-data, or financial harm; the exact impact cannot be verified from this description.",
            "consequences": "Possible unauthorized access, misuse of personal information, further fraudulent messages, or financial loss, depending on what was exposed.",
            "exposure_summary": [label for key, label in (
                ("clicked_link", "Opened a suspicious link"), ("entered_password", "Entered a password"),
                ("shared_code", "Shared an authentication code"), ("downloaded_file", "Downloaded a file"),
                ("opened_file", "Opened a file"), ("sent_money", "Sent money or completed a transfer"),
                ("lost_account", "Lost access to an account"), ("shared_data", "Shared personal information")) if key in exposures],
            "action_sections": _action_sections(scenario, immediate),
            "immediate": immediate, "avoid": scenario.avoid, "contain": scenario.contain,
            "recover": scenario.recover, "protect": scenario.protect, "prevent": scenario.prevent,
            "contact": scenario.contact, "evidence": scenario.evidence,
            "disclaimer": "This rule-based first-response guide is not a validated ML prediction or legal advice. Expected results describe the purpose of each action, not a guarantee. Follow your bank, service provider, or qualified specialist for case-specific support."}
