"""Turn a rendered listing-overview page into :class:`Listing` objects.

The sites in this project are built on wildly different stacks (WordPress,
Next.js, Umbraco, custom SPAs) and none of them expose a documented API, so
hand-written CSS selectors for eleven sites would rot within weeks.

Instead this module exploits the one thing every listing overview has in
common: **each apartment is a link to its own detail page**. We anchor on those
links, climb to the smallest DOM container that holds exactly one of them, and
read the fields out of that container's text. A site config can override any
part of it when the heuristic is not good enough.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from .models import Delevenlig, Listing, canonical_url
from .parsing import (
    normalize_space,
    parse_area,
    parse_delevenlig,
    parse_postal_code,
    parse_price,
    parse_rooms,
    prettify_slug,
)

#: How far to climb from the anchor before giving up on finding a card.
MAX_CLIMB = 8

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "strong", "b")


@dataclass
class FieldSelectors:
    """Optional per-site CSS selectors, relative to the card container.

    Anything left as ``None`` falls back to parsing the card's text.
    """

    name: Optional[str] = None
    price: Optional[str] = None
    rooms: Optional[str] = None
    area: Optional[str] = None
    address: Optional[str] = None


def _text(node: Optional[Tag]) -> str:
    return normalize_space(node.get_text(" ", strip=True)) if node else ""


def _select_text(card: Tag, selector: Optional[str]) -> str:
    if not selector:
        return ""
    return _text(card.select_one(selector))


def _is_listing_link(href: str, base_url: str, pattern: re.Pattern, page_url: str) -> Optional[str]:
    """Return the absolute URL if ``href`` points at a listing detail page."""
    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    absolute = urljoin(base_url, href)
    if urlsplit(absolute).scheme not in ("http", "https"):
        return None
    if not pattern.search(absolute):
        return None
    # The overview page itself usually matches the pattern too.
    if canonical_url(absolute) == canonical_url(page_url):
        return None
    return absolute


def _count_listing_links(node: Tag, base_url: str, pattern: re.Pattern, page_url: str) -> int:
    """Count distinct listings linked from ``node``."""
    seen = set()
    for anchor in node.find_all("a", href=True):
        absolute = _is_listing_link(anchor["href"], base_url, pattern, page_url)
        if absolute:
            seen.add(canonical_url(absolute))
    return len(seen)


def find_card(anchor: Tag, base_url: str, pattern: re.Pattern, page_url: str) -> Tag:
    """Climb from a listing link to the smallest container holding just it.

    Stopping as soon as a second listing appears is what keeps us from
    swallowing the whole results grid and mixing two apartments' fields.
    """
    card = anchor
    for _ in range(MAX_CLIMB):
        parent = card.parent
        if parent is None or not isinstance(parent, Tag) or parent.name in ("body", "html"):
            break
        if _count_listing_links(parent, base_url, pattern, page_url) > 1:
            break
        card = parent
        # Enough context to fill the table: stop climbing early.
        text = _text(card)
        if parse_price(text) is not None and parse_rooms(text) is not None:
            break
    return card


# "Roskildevej 47, st., 2000 Frederiksberg" — street, number, optional floor,
# postal code, city. Cards run their fields together into one text blob, so
# matching the address shape directly beats splitting on punctuation.
_ADDRESS = re.compile(
    r"([A-ZÆØÅ][\wÆØÅæøå.'’\-]*(?:\s+[A-ZÆØÅa-zæøå][\wÆØÅæøå.'’\-]*){0,3}"  # street
    r"\s+\d+[A-Za-z]?"  # house number
    r"(?:\s*,\s*[^,]{1,14}?)?"  # floor / side
    r"\s*,?\s*(?:[12]\d{3})\s+"  # postal code
    r"[A-ZÆØÅ][\wÆØÅæøå.]*(?:\s+[A-ZÆØÅ][\wÆØÅæøå.]*)?)"  # city
)

_BADGE_PREFIX = re.compile(
    r"^(?:ny\b|nyhed\b|udlejet\b|ledig\b|delevenlig\w*|altan\b|elevator\b|"
    r"penthouse\b|tagterrasse\b|hus\b|lejlighed\b|premium\b|top\b|[\s\-–|•·:]+)+",
    re.IGNORECASE,
)

MAX_NAME_LENGTH = 90


def _clean_name(text: str) -> str:
    """Strip card badges ('Ny', 'Altan', 'Delevenlig') and clip runaway text."""
    cleaned = _BADGE_PREFIX.sub("", normalize_space(text)).strip(" -–|•·:,")
    if len(cleaned) > MAX_NAME_LENGTH:
        cleaned = cleaned[:MAX_NAME_LENGTH].rsplit(" ", 1)[0] + "…"
    return cleaned


def _pick_name(card: Tag, anchor: Tag, url: str, address: str) -> str:
    """The address is the most useful name; fall back through the DOM."""
    if address:
        return _clean_name(address)

    candidates = [_text(card.find(tag)) for tag in _HEADING_TAGS]
    candidates.append(_text(anchor))
    for candidate in candidates:
        cleaned = _clean_name(candidate)
        if len(cleaned) >= 4 and not re.fullmatch(
            r"(?i)(l[æa]s mere|se (?:mere|bolig)|detaljer|more|vis bolig)", cleaned
        ):
            return cleaned

    img = card.find("img")
    if img and normalize_space(img.get("alt", "")):
        return _clean_name(img["alt"])

    return prettify_slug(urlsplit(url).path)


def _pick_address(card: Tag, selectors: FieldSelectors, text: str) -> str:
    explicit = _select_text(card, selectors.address)
    if explicit:
        return normalize_space(explicit)

    match = _ADDRESS.search(text)
    if match:
        # Cards prefix the address with badges ("Altan", "Delevenlig"), and the
        # street pattern happily swallows them as part of the street name.
        return _clean_name(match.group(1))

    # Fall back to whichever fragment carries the postal code.
    for fragment in re.split(r"\s*[|•·\n]\s*", text):
        if re.search(r"\b[12]\d{3}\b", fragment) and len(fragment) < 90:
            return normalize_space(fragment)
    return ""


def _first_int(*values: Optional[int]) -> Optional[int]:
    for value in values:
        if value is not None:
            return value
    return None


def extract_listings(
    html: str,
    *,
    page_url: str,
    site_key: str,
    link_pattern: str,
    card_selector: Optional[str] = None,
    selectors: Optional[FieldSelectors] = None,
    known_postal_codes: Optional[set] = None,
) -> list[Listing]:
    """Extract every listing linked from a rendered overview page."""
    selectors = selectors or FieldSelectors()
    pattern = re.compile(link_pattern)
    soup = BeautifulSoup(html, "lxml")

    base_tag = soup.find("base", href=True)
    base_url = urljoin(page_url, base_tag["href"]) if base_tag else page_url

    scope: Iterable[Tag]
    if card_selector:
        scope = soup.select(card_selector)
    else:
        scope = [soup]

    listings: dict[str, Listing] = {}
    for container in scope:
        for anchor in container.find_all("a", href=True):
            url = _is_listing_link(anchor["href"], base_url, pattern, page_url)
            if not url:
                continue
            key = canonical_url(url)
            if key in listings:
                continue

            card = container if card_selector else find_card(anchor, base_url, pattern, page_url)
            text = _text(card)

            price = parse_price(_select_text(card, selectors.price)) if selectors.price else None
            rooms = parse_rooms(_select_text(card, selectors.rooms)) if selectors.rooms else None
            area = parse_area(_select_text(card, selectors.area)) if selectors.area else None

            price = _first_int(price, parse_price(text))
            rooms = rooms if rooms is not None else parse_rooms(text)
            area = _first_int(area, parse_area(text))

            address = _pick_address(card, selectors, text)
            name = _select_text(card, selectors.name) or _pick_name(card, anchor, url, address)
            postal = parse_postal_code(address or text, known_postal_codes)

            listings[key] = Listing(
                site=site_key,
                name=name,
                url=url,
                price=price,
                rooms=rooms,
                area_m2=area,
                address=address,
                postal_code=postal,
                city=_city_from(address or text, postal),
                delevenlig=Delevenlig(parse_delevenlig(text)),
                source_text=text,
            )

    return list(listings.values())


def _city_from(text: str, postal: Optional[str]) -> str:
    """Read the city name that follows the postal code, if present."""
    if not postal:
        return ""
    match = re.search(re.escape(postal) + r"\s+([A-ZÆØÅ][\wÆØÅæøå.\- ]{2,30})", text)
    if not match:
        return ""
    city = normalize_space(match.group(1))
    # Cut the trailing sentence the address ran into.
    city = re.split(r"\s(?:kr|m2|m²|v[æa]r|fra|pr)\b", city, flags=re.IGNORECASE)[0]
    return city.strip(" ,.-")
