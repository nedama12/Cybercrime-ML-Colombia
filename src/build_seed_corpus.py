"""Build the seed corpus used to train the incident report classifier.

The Attorney General's Office dataset (crimes_processed.csv) tells us how many
cases of each category exist, but it contains no description of what the victim
experienced. A citizen filling the report only knows *what happened to them*,
so the report classifier needs examples written from the victim's point of view.

This script builds a reproducible seed corpus from victim-style descriptions
written by the team for each category defined in Law 1273 of 2009. It is
clearly labelled as seed data (`source = seed`). `template_id` identifies the
base phrase of each report, so cross-validation can keep every phrase in a
single fold and measure how the model handles wording it has never seen. Every report confirmed or
corrected by an analyst in the platform becomes a real labelled example, and
`src/train_report_model.py --include-confirmed` adds them to the next training run.

Usage:  python -m src.build_seed_corpus
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data/reports/seed_reports.csv"
SEED = 42
PER_CATEGORY = 260

CHANNELS = ["phone_call", "sms_whatsapp", "email", "social_media", "website_app", "device", "unknown"]
AFFECTED = ["money", "personal_data", "account", "device", "business_system"]

BANKS = ["my bank", "Bancolombia", "Davivienda", "Nequi", "Daviplata", "BBVA", "Banco de Bogota",
         "my savings account", "my credit card", "my debit card"]
BANKS_ES = ["mi banco", "Bancolombia", "Davivienda", "Nequi", "Daviplata", "BBVA", "Banco de Bogota",
            "mi cuenta de ahorros", "mi tarjeta de credito", "mi tarjeta debito"]
ACCOUNTS = ["Facebook", "Instagram", "WhatsApp", "Gmail", "Outlook", "TikTok", "email", "Netflix",
            "online banking"]
AMOUNTS = ["200,000", "350,000", "500,000", "1,200,000", "2,000,000", "80,000", "4,500,000"]

# Each category: victim-style phrases (English and Spanish), likely channels and
# affected assets. Phrases overlap on purpose (bank, account, message...), as
# real reports do, so the model must combine several signals.
CATEGORIES: dict[str, dict] = {
    "ELECTRONIC_THEFT": {
        "phrases": [
            "money disappeared from {bank} and I did not make those purchases",
            "there are charges on {bank} that I never authorized",
            "someone withdrew {amount} pesos from {bank} without my permission",
            "I found online purchases on {bank} that I did not make",
            "my balance dropped by {amount} pesos overnight, unknown payments",
            "they cloned my card and paid things in another city",
            "unauthorized payments of {amount} appeared in my bank statement",
            "somebody used my card details to buy online",
            "me sacaron {amount} pesos de {bank_es} sin autorizacion",
            "aparecieron compras que yo no hice en {bank_es}",
            "me clonaron la tarjeta y hicieron compras por internet",
            "desaparecio dinero de mi cuenta, cobros que no reconozco",
        ],
        "channels": {"unknown": 4, "website_app": 3, "sms_whatsapp": 1, "device": 1},
        "affected": {"money": 0.97, "account": 0.35, "personal_data": 0.15},
    },
    "TRANSFER_FRAUD": {
        "phrases": [
            "I paid {amount} pesos to an online seller who never delivered",
            "a person pretending to be my relative asked me to send money and I transferred it",
            "they convinced me to transfer {amount} for a job offer that was fake",
            "I sent money for a rental apartment that did not exist",
            "a fake investment platform promised returns and I transferred my savings",
            "they told me I won a prize and had to pay a fee by transfer",
            "I made a transfer to a stranger who said he was from the bank to protect my money",
            "I bought a product on marketplace, transferred the money and the seller disappeared",
            "me enganaron y transferi {amount} pesos a un vendedor falso",
            "un supuesto familiar me pidio plata por whatsapp y le consigne",
            "pague un arriendo que no existia, me estafaron con la transferencia",
            "me ofrecieron una inversion y les transferi mis ahorros",
        ],
        "channels": {"social_media": 3, "sms_whatsapp": 3, "phone_call": 2, "website_app": 2},
        "affected": {"money": 0.98, "personal_data": 0.12},
    },
    "PHISHING_SPOOFING": {
        "phrases": [
            "I received an email that looked like {bank} asking me to update my password on a link",
            "a text message with a link to a fake bank page asked for my card number",
            "I entered my username and password on a website that copied the real login page",
            "a message said my package was retained and asked for my details on a link",
            "the website looked identical to the official one but the address was different",
            "I got an SMS saying my account was blocked and to click a link to unlock it",
            "an email from a supposed government office asked me to log in to check a fine",
            "they sent me a fake page of {account} and I typed my credentials",
            "me llego un correo falso de {bank_es} con un enlace para actualizar datos",
            "recibi un mensaje de texto con un link a una pagina falsa del banco",
            "ingrese mi clave en una pagina que se veia igual a la oficial",
            "un mensaje decia que mi cuenta estaba bloqueada y que entrara al enlace",
        ],
        "channels": {"email": 4, "sms_whatsapp": 4, "website_app": 2, "social_media": 1},
        "affected": {"personal_data": 0.85, "account": 0.5, "money": 0.25},
    },
    "ABUSIVE_ACCESS": {
        "phrases": [
            "someone logged into my {account} account without permission",
            "I received an alert of a login from another country on my {account}",
            "my {account} password was changed and I can no longer access it",
            "a person entered my {account} and is sending messages to my contacts",
            "they hacked my {account} account and changed the recovery email",
            "someone accessed the company server with an old employee password",
            "my ex partner keeps entering my {account} account without my authorization",
            "they stole my {account} and are asking my friends for money",
            "alguien entro a mi cuenta de {account} sin permiso",
            "me hackearon el {account} y cambiaron la contrasena",
            "me llego una alerta de inicio de sesion desde otro pais",
            "un tercero accedio a mi correo y lo esta usando",
        ],
        "channels": {"unknown": 3, "social_media": 3, "email": 2, "website_app": 2},
        "affected": {"account": 0.97, "personal_data": 0.35, "business_system": 0.1},
    },
    "PERSONAL_DATA": {
        "phrases": [
            "my personal information was published online without my consent",
            "a company shared my data and now strangers call me with my full name and ID",
            "someone used my ID number to open a credit line in my name",
            "my photos and private documents were leaked on social media",
            "a database with my address and phone number is being sold",
            "they took a loan using my identity card copy",
            "a store sold my contact data to third parties",
            "someone created a profile with my photos and my name",
            "publicaron mis datos personales en internet sin autorizacion",
            "usaron mi cedula para sacar un credito a mi nombre",
            "filtraron mis fotos y documentos privados",
            "una empresa vendio mi informacion personal",
        ],
        "channels": {"social_media": 3, "unknown": 3, "phone_call": 2, "website_app": 2},
        "affected": {"personal_data": 0.98, "account": 0.15, "money": 0.15},
    },
    "MALWARE": {
        "phrases": [
            "after opening an attachment my computer files were encrypted and they ask for a ransom",
            "I installed an app and now my phone shows ads and sends messages by itself",
            "an antivirus detected a virus that steals passwords on my computer",
            "a program I downloaded took control of my computer",
            "my files now have a strange extension and there is a ransom note",
            "a fake update installed something that records what I type",
            "the company computers were infected with ransomware",
            "my phone got a virus after downloading an apk from a link",
            "abri un archivo adjunto y me encriptaron los archivos, piden rescate",
            "instale una aplicacion y el celular quedo con un virus",
            "un programa malicioso tomo el control de mi computador",
            "los equipos de la empresa se infectaron con ransomware",
        ],
        "channels": {"email": 3, "device": 3, "website_app": 2, "sms_whatsapp": 1},
        "affected": {"device": 0.95, "personal_data": 0.3, "business_system": 0.3},
    },
    "SYSTEM_ATTACK": {
        "phrases": [
            "our company website went down after a flood of traffic",
            "someone deleted the information in our database",
            "the online store was defaced and shows a hacker message",
            "our servers stopped working because of a denial of service attack",
            "an attacker intercepted the data sent between our offices",
            "the system we use to bill clients was sabotaged and data was destroyed",
            "they blocked access to our platform and customers cannot use it",
            "someone modified the records in the school information system",
            "la pagina web de la empresa se cayo por un ataque",
            "borraron la informacion de nuestra base de datos",
            "atacaron los servidores y el servicio dejo de funcionar",
            "interceptaron las comunicaciones de la red de la empresa",
        ],
        "channels": {"website_app": 4, "unknown": 3, "device": 1},
        "affected": {"business_system": 0.97, "device": 0.2, "personal_data": 0.15},
    },
    "MOBILE_DEVICES": {
        "phrases": [
            "my stolen phone was reported but it is working again with another IMEI",
            "the phone I bought had its IMEI altered",
            "a shop reprogrammed my stolen cellphone to sell it",
            "my phone was stolen and they changed the IMEI to unlock it",
            "I bought a used phone and the operator says the IMEI is cloned",
            "they tampered with my mobile device identification number",
            "me robaron el celular y le cambiaron el IMEI",
            "el telefono que compre tenia el IMEI adulterado",
            "reprogramaron mi celular robado para venderlo",
        ],
        "channels": {"device": 6, "unknown": 2},
        "affected": {"device": 0.98, "money": 0.2},
    },
}

OPENERS = ["", "", "", "Yesterday ", "Last week ", "This morning ", "Two days ago ", "Hello, ",
           "Ayer ", "Hace una semana ", "Buenas, "]
CLOSERS = ["", "", "", ". I need help", ". What should I do?", ". I already called the bank",
           ". I have screenshots", ". necesito ayuda", ". tengo capturas de pantalla"]


def weighted_choice(rng: random.Random, weights: dict[str, int]) -> str:
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def fill(rng: random.Random, phrase: str) -> str:
    return phrase.format(bank=rng.choice(BANKS), bank_es=rng.choice(BANKS_ES),
                         account=rng.choice(ACCOUNTS), amount=rng.choice(AMOUNTS))


def build_rows(rng: random.Random) -> list[dict]:
    rows = []
    for category, spec in CATEGORIES.items():
        for _ in range(PER_CATEGORY):
            index = rng.randrange(len(spec["phrases"]))
            parts = [fill(rng, spec["phrases"][index])]
            if rng.random() < 0.25:  # some reports mix two sentences
                parts.append(fill(rng, rng.choice(spec["phrases"])))
            text = rng.choice(OPENERS) + " and ".join(parts) + rng.choice(CLOSERS)
            affected = [a for a, p in spec["affected"].items() if rng.random() < p]
            if rng.random() < 0.08:  # victims sometimes tick an extra box
                affected.append(rng.choice(AFFECTED))
            channel = weighted_choice(rng, spec["channels"])
            if rng.random() < 0.10:
                channel = rng.choice(CHANNELS)
            rows.append({"description": text.strip(), "channel": channel,
                         "affected": ";".join(sorted(set(affected))),
                         "category": category, "template_id": f"{category}:{index:02d}",
                         "source": "seed"})
    rng.shuffle(rows)
    return rows


def main() -> None:
    rows = build_rows(random.Random(SEED))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} seed reports to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
