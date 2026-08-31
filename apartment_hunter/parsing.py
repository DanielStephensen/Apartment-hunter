"""Parsing of Danish listing text into structured fields.

Every site words its cards differently ("5 vær.", "Værelser: 5", "5-værelses"),
so field extraction lives here as pure functions over text. Keeping it free of
any HTML or browser dependency means it can be unit tested against the snippets
the sites actually produce.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

NBSP = " "

# 12.500 / 12 500 / 12500 — Danish thousands separators are "." or a space.
_NUMBER = r"\d{1,3}(?:[.\s ]\d{3})+|\d+"

# A price is only a price when it is anchored to a currency token; this keeps
# "130 m²" and postal codes from being read as rent.
_PRICE_AFTER = re.compile(
    r"(?P<num>" + _NUMBER + r")(?:,\d{2})?\s*(?:kr\.?|dkk|,-)", re.IGNORECASE
)
_PRICE_BEFORE = re.compile(
    r"(?:kr\.?|dkk)\s*(?P<num>" + _NUMBER + r")(?:,\d{2})?", re.IGNORECASE
)

# Amounts that are explicitly *not* the monthly rent. Both boundaries are
# anchored: the context window is a slice and can end mid-word, so a bare
# ``el\b`` would match the truncated tail of "Værelser" and discard the rent.
_NOT_RENT = re.compile(
    r"\b(?:depositum|forudbetalt|indskud|aconto|a/conto|à\s*conto|forbrug|"
    r"vand|varme|el|antenne|internet|opstart|oprettelse)\b",
    re.IGNORECASE,
)
_IS_RENT = re.compile(
    r"husleje|m[åa]nedlig|pr\.?\s*m[åa]ned|/\s*m[åa]ned|pr\.?\s*md|/\s*md|"
    r"leje\b|pris\b|monthly",
    re.IGNORECASE,
)

_ROOMS = re.compile(
    r"(?:(?P<pre>\d+(?:[,.]\d)?)\s*(?:-\s*)?(?:v[æa]r(?:elser|else)?\.?\b|"
    r"rum\b|rooms?\b|v[æa]relses\b))"
    r"|(?:(?:antal\s+)?v[æa]relser|rooms?)\s*[:\-]?\s*(?P<post>\d+(?:[,.]\d)?)",
    re.IGNORECASE,
)

_AREA = re.compile(
    r"(?:(?P<pre>\d{2,4})\s*(?:m2|m²|kvm\b))"
    r"|(?:(?:bolig)?areal|st[øo]rrelse|size)\s*[:\-]?\s*(?P<post>\d{2,4})",
    re.IGNORECASE,
)

# Danish postal codes for the greater Copenhagen area are 1000-2999.
_POSTAL = re.compile(r"\b(?P<code>[12]\d{3})\b")

_DELEVENLIG_NEG = re.compile(
    r"(?:ikke|ej|ingen|kan\s+ikke)\s+(?:\w+\s+){0,2}dele[\s-]?venlig\w*"
    r"|dele[\s-]?venlig\w*\s*[:\-]?\s*nej"
    r"|ikke\s+egnet\s+til\s+deling"
    r"|deleboliger?\s+(?:er\s+)?ikke",
    re.IGNORECASE,
)
_DELEVENLIG_POS = re.compile(r"dele[\s-]?venlig\w*|delebolig\w*|egnet\s+til\s+deling", re.IGNORECASE)


def normalize_space(text: str) -> str:
    """Collapse whitespace (including non-breaking) into single spaces."""
    if not text:
        return ""
    text = unicodedata.normalize("NFC", text.replace(NBSP, " "))
    return re.sub(r"\s+", " ", text).strip()


# Sites mark up square metres as "m<sup>2</sup>", which flattens to "m 2" once
# the tags are gone. Left alone, that stray 2 is read as the room count in text
# like "Boligareal 160 m 2 Værelser 5".
_SUPERSCRIPT_M2 = re.compile(r"\bm\s?2\b(?!\d)", re.IGNORECASE)


def normalize_units(text: str) -> str:
    """Fold flattened superscript square-metre markup back into ``m²``."""
    return _SUPERSCRIPT_M2.sub("m²", normalize_space(text))


def _to_int(raw: str) -> Optional[int]:
    digits = re.sub(r"[.\s" + NBSP + r"]", "", raw)
    return int(digits) if digits.isdigit() else None


#: A label after the amount is weaker evidence than one before it, because
#: Danish listings are written "Husleje 12.500 kr. Depositum 37.500 kr." —
#: each label belongs to the amount that follows it.
_TRAILING_LABEL_PENALTY = 3


def _nearest_label(text: str, start: int, end: int) -> Optional[bool]:
    """Is the amount at ``start:end`` labelled as rent?

    Returns ``True`` for rent, ``False`` for a deposit or utility charge, and
    ``None`` when nothing nearby says either way. Whichever label sits closest
    decides, so a deposit mentioned *after* the rent no longer discards it.
    """
    before = text[max(0, start - 60) : start]
    after = text[end : end + 30]

    best_distance, verdict = None, None
    for pattern, is_rent in ((_IS_RENT, True), (_NOT_RENT, False)):
        preceding = list(pattern.finditer(before))
        if preceding:
            distance = len(before) - preceding[-1].end()
            if best_distance is None or distance < best_distance:
                best_distance, verdict = distance, is_rent

        following = pattern.search(after)
        if following:
            distance = following.start() * _TRAILING_LABEL_PENALTY + 1
            if best_distance is None or distance < best_distance:
                best_distance, verdict = distance, is_rent

    return verdict


def parse_price(text: str) -> Optional[int]:
    """Return the monthly rent in DKK, ignoring deposits and utilities.

    When several amounts appear, prefer one the text marks as rent, and never
    return one marked as a deposit or a utility charge.
    """
    text = normalize_units(text)
    candidates: list = []  # (score, -position, value)

    for pattern in (_PRICE_AFTER, _PRICE_BEFORE):
        for match in pattern.finditer(text):
            value = _to_int(match.group("num"))
            if value is None or not (1000 <= value <= 200_000):
                continue
            label = _nearest_label(text, match.start(), match.end())
            if label is False:
                continue
            candidates.append((1 if label else 0, -match.start(), value))

    if not candidates:
        return None
    # Best-labelled, then earliest occurrence — cards lead with the rent.
    return max(candidates)[2]


def parse_rooms(text: str) -> Optional[float]:
    text = normalize_units(text)
    for match in _ROOMS.finditer(text):
        raw = match.group("pre") or match.group("post")
        if not raw:
            continue
        try:
            value = float(raw.replace(",", "."))
        except ValueError:
            continue
        if 1 <= value <= 20:
            return value
    return None


def parse_area(text: str) -> Optional[int]:
    text = normalize_units(text)
    for match in _AREA.finditer(text):
        raw = match.group("pre") or match.group("post")
        if raw and raw.isdigit():
            value = int(raw)
            if 10 <= value <= 1000:
                return value
    return None


# Words that mark a nearby four-digit number as a date, not a postal code.
_DATE_CONTEXT = re.compile(
    # "©" is not a word character, so it cannot sit behind a \b.
    r"(?:(?:\b(?:d|den|pr|fra|til|siden|år|copyright)\.?|©)\s*$)"
    r"|(?:\b(?:januar|februar|marts|april|maj|juni|juli|august|september|"
    r"oktober|november|december)\s+\d{0,2}\.?,?\s*$)"
    r"|(?:\d{1,2}[./-]\d{1,2}[./-]\s*$)",
    re.IGNORECASE,
)


def parse_postal_code(text: str, known_codes: Optional[set] = None) -> Optional[str]:
    """Pick the postal code out of an address line.

    Listing pages are full of stray four-digit numbers — years above all, and
    "2026" reads as a perfectly ordinary postal code. So a number only counts
    when a city name follows it or we recognise it as a code we care about;
    anything else yields ``None`` rather than a guess, because a wrong code
    would silently drop a Copenhagen apartment as being out of town.
    """
    text = normalize_units(text)
    matches = list(_POSTAL.finditer(text))
    if not matches:
        return None

    for match in matches:
        if _DATE_CONTEXT.search(text[max(0, match.start() - 20) : match.start()]):
            continue
        tail = text[match.end() : match.end() + 24]
        if re.match(r"\s*[A-ZÆØÅ][a-zæøåA-ZÆØÅ.\- ]{2,}", tail):
            return match.group("code")

    if known_codes:
        for match in matches:
            if match.group("code") in known_codes:
                return match.group("code")
    return None


def parse_delevenlig(text: str) -> str:
    """Classify sharing-friendliness as ``ja`` / ``nej`` / ``ukendt``.

    Returns plain strings so this stays independent of the model layer; the
    caller maps them onto :class:`~apartment_hunter.models.Delevenlig`.
    """
    text = normalize_units(text)
    if _DELEVENLIG_NEG.search(text):
        return "nej"
    if _DELEVENLIG_POS.search(text):
        return "ja"
    return "ukendt"


def prettify_slug(slug: str) -> str:
    """Turn ``strandboulevarden-61-5-th-2100-kobenhavn`` into a readable name."""
    slug = re.sub(r"[-_]+", " ", slug.strip("/").split("/")[-1])
    slug = re.sub(r"\.(html?|aspx)$", "", slug, flags=re.IGNORECASE)
    return normalize_space(slug).title()
