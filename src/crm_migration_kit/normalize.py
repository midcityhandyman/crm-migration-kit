"""Field level normalisation for phones, emails and names.

Every function is pure and returns the cleaned value together with an
optional issue code, so the pipeline can report what it changed and why.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

_EXT_RE = re.compile(r"(?:ext\.?|extension|x|#)\s*(\d{1,6})\s*$", re.IGNORECASE)
_EMAIL_RE = re.compile(r"^[a-z0-9._%+'\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)+$")
_ANGLE_RE = re.compile(r"<([^<>]+)>")
_WORD_START_RE = re.compile(r"(^|[\s\-'])([a-z])")


@dataclass(frozen=True)
class PhoneResult:
    value: str  # E.164 style, for example +15555550101, or "" when unusable
    extension: str
    issue: str | None  # None or "invalid_phone"


@dataclass(frozen=True)
class EmailResult:
    value: str  # lower case address, or "" when unusable
    issue: str | None  # None, "email_repaired" or "invalid_email"


def normalize_phone(raw: str | None, default_country_code: str = "1") -> PhoneResult:
    """Normalise a phone number to +<country><number>.

    Ten digit numbers get the default country code. Numbers that already
    carry the country code, or start with a plus sign, are kept as they are.
    A trailing extension (x12, ext. 12, #12) is split off.
    """
    text = (raw or "").strip()
    if not text:
        return PhoneResult("", "", None)

    extension = ""
    match = _EXT_RE.search(text)
    if match:
        extension = match.group(1)
        text = text[: match.start()]

    has_plus = text.lstrip().startswith("+")
    digits = re.sub(r"\D", "", text)
    cc = default_country_code

    if has_plus and 8 <= len(digits) <= 15:
        return PhoneResult("+" + digits, extension, None)
    if not has_plus and len(digits) == 10:
        return PhoneResult("+" + cc + digits, extension, None)
    if not has_plus and len(digits) == 10 + len(cc) and digits.startswith(cc):
        return PhoneResult("+" + digits, extension, None)
    return PhoneResult("", "", "invalid_phone")


def normalize_email(raw: str | None) -> EmailResult:
    """Lower case and validate an email address.

    Handles "mailto:" prefixes, "Name <address>" wrappers, stray spaces and
    trailing punctuation. A comma in the domain is repaired to a dot and
    reported as "email_repaired" so a human can confirm the guess.
    """
    text = (raw or "").strip()
    if not text:
        return EmailResult("", None)

    angle = _ANGLE_RE.search(text)
    if angle:
        text = angle.group(1)
    text = text.lower().strip()
    if text.startswith("mailto:"):
        text = text[len("mailto:"):]
    text = re.sub(r"\s+", "", text).rstrip(".,;")

    if _EMAIL_RE.match(text):
        return EmailResult(text, None)

    if text.count("@") == 1:
        local, domain = text.split("@")
        repaired = local + "@" + domain.replace(",", ".")
        if repaired != text and _EMAIL_RE.match(repaired):
            return EmailResult(repaired, "email_repaired")
    return EmailResult("", "invalid_email")


def email_match_key(email: str, ignore_plus_tags: bool = True) -> str:
    """Key used to compare emails: sam+crm@example.com equals sam@example.com."""
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    if ignore_plus_tags:
        local = local.split("+", 1)[0]
    return local + "@" + domain


def clean_name(raw: str | None) -> str:
    """Collapse whitespace and fix names typed in ALL CAPS or all lower case."""
    text = re.sub(r"\s+", " ", (raw or "")).strip(" ,")
    if text and (text.isupper() or text.islower()):
        text = _WORD_START_RE.sub(lambda m: m.group(1) + m.group(2).upper(), text.lower())
    return text


def split_full_name(full_name: str | None) -> tuple[str, str]:
    """Split "Last, First" or "First Middle Last" into (first, last)."""
    text = re.sub(r"\s+", " ", (full_name or "")).strip()
    if not text:
        return "", ""
    if "," in text:
        last, first = text.split(",", 1)
        return clean_name(first), clean_name(last)
    parts = text.split(" ")
    if len(parts) == 1:
        return clean_name(parts[0]), ""
    return clean_name(" ".join(parts[:-1])), clean_name(parts[-1])


def name_key(*parts: str) -> str:
    """Letters only, lower case. Used to compare names loosely."""
    return re.sub(r"[^a-z]", "", "".join(parts).lower())


def name_similarity(first_a: str, last_a: str, first_b: str, last_b: str) -> float | None:
    """Similarity between two names from 0.0 to 1.0, or None if one is blank.

    An initial matches a full first name when the last names are equal
    ("J. Testerson" and "Jordan Testerson" score 0.9).
    """
    key_a, key_b = name_key(first_a, last_a), name_key(first_b, last_b)
    if not key_a or not key_b:
        return None
    if key_a == key_b:
        return 1.0
    fa, fb = name_key(first_a), name_key(first_b)
    la, lb = name_key(last_a), name_key(last_b)
    if la and la == lb and fa and fb and 1 in (len(fa), len(fb)) and fa[0] == fb[0]:
        return 0.9
    return round(SequenceMatcher(None, key_a, key_b).ratio(), 2)
