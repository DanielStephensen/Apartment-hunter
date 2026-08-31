"""Enrich a listing from its own detail page.

Overview cards are terse: they often omit the size or the room count, and the
word "delevenlig" is nearly always on the detail page rather than the card.
Detail pages are only fetched for listings that are new *and* not already
ruled out, so a daily run costs one request per genuinely new apartment.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import List, Optional

from .config import COPENHAGEN_POSTAL_CODES
from .models import Delevenlig, Listing
from .parsing import (
    normalize_space,
    parse_area,
    parse_delevenlig,
    parse_postal_code,
    parse_price,
    parse_rooms,
)
from .render import BrowserSession, RenderOptions

log = logging.getLogger(__name__)

# Detail pages are plain documents: a short settle and a light scroll is
# enough to reach the description where "delevenlig" is stated.
DETAIL_RENDER = RenderOptions(wait_ms=1200, scroll=True, scroll_steps=4, networkidle_ms=4000)

#: Boilerplate that would otherwise poison the field parsers — site-wide
#: footers advertise "delevenlige boliger" and other apartments' prices.
_STRIP_TAGS = ("script", "style", "noscript", "header", "footer", "nav")


def page_text(html: str) -> str:
    """Readable text of the page body, without navigation and script noise."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(list(_STRIP_TAGS)):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return normalize_space(main.get_text(" ", strip=True))


def enrich(listing: Listing, session: BrowserSession) -> Listing:
    """Return a copy of ``listing`` completed from its detail page.

    Card values win where they exist — they are the site's own summary — and
    the detail page fills the gaps. The exception is ``delevenlig``, where an
    explicit statement on the detail page is the authoritative answer.
    """
    try:
        html = session.render(listing.url, DETAIL_RENDER, retries=1)
    except Exception as exc:  # noqa: BLE001 - a bad detail page must not stop the run
        log.warning("could not open detail page %s: %s", listing.url, exc)
        return listing

    text = page_text(html)
    if not text:
        return listing

    combined = f"{listing.source_text} {text}"
    updates = {
        "rooms": listing.rooms if listing.rooms is not None else parse_rooms(text),
        "price": listing.price if listing.price is not None else parse_price(text),
        "area_m2": listing.area_m2 if listing.area_m2 is not None else parse_area(text),
        "source_text": combined,
    }

    detail_delevenlig = Delevenlig(parse_delevenlig(text))
    if detail_delevenlig is not Delevenlig.UNKNOWN:
        updates["delevenlig"] = detail_delevenlig

    if not listing.postal_code:
        postal = parse_postal_code(text, set(COPENHAGEN_POSTAL_CODES))
        if postal:
            updates["postal_code"] = postal

    return dataclasses.replace(listing, **updates)


def enrich_all(listings: List[Listing], session: BrowserSession, limit: Optional[int] = None) -> List[Listing]:
    """Enrich each listing, keeping going when individual pages fail."""
    selected = listings[:limit] if limit else listings
    enriched = []
    for index, listing in enumerate(selected, start=1):
        log.info("enriching %d/%d: %s", index, len(selected), listing.url)
        enriched.append(enrich(listing, session))
    # Anything beyond the limit passes through untouched.
    return enriched + list(listings[len(selected):])
