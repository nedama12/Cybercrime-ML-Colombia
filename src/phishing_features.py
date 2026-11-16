"""URL-only features shared by phishing training and inference."""
from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

import pandas as pd


URL_FEATURE_COLUMNS = [
    "url_length", "host_length", "host_label_count", "subdomain_label_count",
    "is_ip_address", "is_https", "path_length", "query_length",
    "has_fragment", "letter_count", "digit_count", "special_char_count",
    "letter_ratio", "digit_ratio", "special_char_ratio", "dot_count",
    "hyphen_count", "underscore_count", "at_count", "encoded_char_count",
    "equals_count", "question_mark_count", "ampersand_count", "slash_count",
]
_ENCODED_CHAR = re.compile(r"%[0-9a-fA-F]{2}")


def normalize_url_text(value: str) -> str:
    """Validate a URL string and add HTTPS when the user omitted a scheme.

    This function only parses text. It never resolves a hostname or makes a request.
    """
    if not isinstance(value, str):
        raise ValueError("Enter a URL as text.")
    url = value.strip()
    if not url or len(url) > 2048:
        raise ValueError("Enter a URL between 1 and 2048 characters long.")
    if any(character.isspace() or ord(character) < 32 for character in url):
        raise ValueError("The URL cannot contain whitespace or control characters.")
    if "://" not in url:
        url = "https://" + url
    try:
        parsed = urlsplit(url)
        # Accessing .port also validates malformed port values.
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Enter a valid HTTP or HTTPS URL.") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Enter a valid HTTP or HTTPS URL with a hostname.")
    return url


def parse_url_host(value: str) -> str:
    """Return a normalized host for validation and domain-grouped splitting."""
    try:
        parsed = urlsplit(value if "://" in value else "//" + value)
        host = parsed.hostname or ""
        return host.encode("idna").decode("ascii").lower().rstrip(".")
    except (UnicodeError, ValueError, AttributeError):
        return ""


def extract_url_features(value: str) -> dict[str, float]:
    """Extract numeric indicators from the URL string alone; no page is fetched."""
    url = normalize_url_text(value)
    parsed = urlsplit(url)
    host = parse_url_host(url)
    if not host:
        raise ValueError("The URL hostname could not be parsed.")
    try:
        ipaddress.ip_address(host.strip("[]"))
        is_ip = 1
    except ValueError:
        is_ip = 0

    length = max(len(url), 1)
    letters = sum(character.isalpha() for character in url)
    digits = sum(character.isdigit() for character in url)
    specials = sum(not character.isalnum() for character in url)
    labels = [part for part in host.split(".") if part]
    return {
        "url_length": len(url),
        "host_length": len(host),
        "host_label_count": len(labels),
        "subdomain_label_count": max(0, len(labels) - 2),
        "is_ip_address": is_ip,
        "is_https": int(parsed.scheme.lower() == "https"),
        "path_length": len(parsed.path),
        "query_length": len(parsed.query),
        "has_fragment": int(bool(parsed.fragment)),
        "letter_count": letters,
        "digit_count": digits,
        "special_char_count": specials,
        "letter_ratio": letters / length,
        "digit_ratio": digits / length,
        "special_char_ratio": specials / length,
        "dot_count": url.count("."),
        "hyphen_count": url.count("-"),
        "underscore_count": url.count("_"),
        "at_count": url.count("@"),
        "encoded_char_count": len(_ENCODED_CHAR.findall(url)),
        "equals_count": url.count("="),
        "question_mark_count": url.count("?"),
        "ampersand_count": url.count("&"),
        "slash_count": url.count("/"),
    }


def make_url_feature_frame(urls: list[str] | pd.Series) -> pd.DataFrame:
    """Build the fixed-order numeric feature matrix for a collection of URLs."""
    rows = [extract_url_features(url) for url in urls]
    return pd.DataFrame(rows, columns=URL_FEATURE_COLUMNS, dtype="float64")
