"""Feature extraction from a URL, following the definitions of the PhiUSIIL dataset.

Rules found by comparing with the dataset (scripts/check_feature_parity.py):
  * lengths and ratios use the full URL length;
  * character counts are taken from the URL without the scheme (http/https://) and without
    a leading "www.";
  * the domain is the host name and the TLD is its last label.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

URL_FEATURES = [
    "URLLength", "DomainLength", "IsDomainIP", "TLDLength", "NoOfSubDomain",
    "HasObfuscation", "NoOfObfuscatedChar", "ObfuscationRatio", "NoOfLettersInURL",
    "LetterRatioInURL", "NoOfDegitsInURL", "DegitRatioInURL", "NoOfEqualsInURL",
    "NoOfQMarkInURL", "NoOfAmpersandInURL", "NoOfOtherSpecialCharsInURL",
    "SpacialCharRatioInURL", "IsHTTPS",
]
LOOKUP_FEATURES = ["TLDLegitimateProb"]
COMPUTABLE_FEATURES = URL_FEATURES + LOOKUP_FEATURES

MAX_URL_LENGTH = 2048
_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_OBFUSCATED = re.compile(r"%[0-9a-fA-F]{2}")


class InvalidURL(ValueError):
    pass


def normalize_url(raw):
    """Validate a URL typed by a user and return it trimmed. Raises InvalidURL."""
    url = (raw or "").strip()
    if not url:
        raise InvalidURL("Enter a URL.")
    if len(url) > MAX_URL_LENGTH:
        raise InvalidURL(f"The URL is longer than {MAX_URL_LENGTH} characters.")
    if any(c.isspace() for c in url):
        raise InvalidURL("The URL cannot contain spaces.")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        raise InvalidURL("Include the scheme, for example https://example.com")
    try:
        host = urlsplit(url).hostname
    except ValueError as exc:
        raise InvalidURL("The URL is not valid.") from exc
    if not host or "." not in host:
        raise InvalidURL("The URL must include a domain such as example.com")
    return url


def domain_of(url):
    return (urlsplit(url).hostname or "").lower()


def _body(url):
    without_scheme = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    return re.sub(r"^www\.", "", without_scheme, flags=re.IGNORECASE)


def extract_url_features(url, tld_probs=None):
    """Return the computable features for a (validated) URL."""
    domain = domain_of(url)
    tld = domain.rsplit(".", 1)[-1]
    body = _body(url)
    length = len(url)

    letters = sum(c.isalpha() for c in body)
    digits = sum(c.isdigit() for c in body)
    equals, qmarks, amps = body.count("="), body.count("?"), body.count("&")
    other_special = sum((not c.isalnum()) and c not in "=?&" for c in body)
    obfuscated = len(_OBFUSCATED.findall(body))

    def ratio(n):
        return round(n / length, 3) if length else 0.0

    values = {
        "URLLength": length,
        "DomainLength": len(domain),
        "IsDomainIP": int(bool(_IPV4.match(domain))),
        "TLDLength": len(tld),
        "NoOfSubDomain": max(domain.count(".") - 1, 0),
        "HasObfuscation": int(obfuscated > 0),
        "NoOfObfuscatedChar": obfuscated,
        "ObfuscationRatio": ratio(obfuscated),
        "NoOfLettersInURL": letters,
        "LetterRatioInURL": ratio(letters),
        "NoOfDegitsInURL": digits,
        "DegitRatioInURL": ratio(digits),
        "NoOfEqualsInURL": equals,
        "NoOfQMarkInURL": qmarks,
        "NoOfAmpersandInURL": amps,
        "NoOfOtherSpecialCharsInURL": other_special,
        "SpacialCharRatioInURL": ratio(other_special),
        "IsHTTPS": int(url.lower().startswith("https://")),
    }
    if tld_probs is not None:
        # Unknown TLDs get 0: a TLD never seen among legitimate sites is treated as suspicious.
        values["TLDLegitimateProb"] = float(tld_probs.get(tld, 0.0))
    return values


def build_model_input(url, features, manual=None, tld_probs=None):
    """Assemble the model input for `features`.

    Returns (values, sources, missing):
      values  - feature -> number
      sources - feature -> "computed" | "manual"
      missing - features the model needs that were neither computed nor typed
    """
    manual = manual or {}
    computed = extract_url_features(url, tld_probs) if url else {}
    values, sources, missing = {}, {}, []
    for name in features:
        if name in computed:
            values[name], sources[name] = computed[name], "computed"
        elif manual.get(name) not in (None, ""):
            values[name], sources[name] = float(manual[name]), "manual"
        else:
            missing.append(name)
    return values, sources, missing


def load_json(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
