"""Search criteria applied to every scraped listing.

The gates run in order and the first rejection wins, so the run log says
exactly why a listing was dropped. Each gate is deliberately small and pure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, FrozenSet, List, Optional

from .config import (
    COPENHAGEN_PLACE_NAMES,
    COPENHAGEN_POSTAL_CODES,
    EXCLUDED_PLACE_NAMES,
    MIN_ROOMS,
    SiteConfig,
)
from .models import Delevenlig, Listing


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    reason: str = ""
    stable: bool = True
    """Whether this outcome is a settled fact about the apartment.

    A rejection based on something we read ("4 rooms") will not change, so the
    listing can be remembered and skipped cheaply on later runs. A rejection
    caused by information we simply could not find must stay unstable, or a
    listing whose page was slow once would be ignored forever.
    """

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.accepted


ACCEPT = Verdict(True)

Gate = Callable[[Listing, SiteConfig], Verdict]


def _mentions(text: str, names: FrozenSet[str]) -> Optional[str]:
    """Whole-word search so 'Roskildevej' does not read as 'Roskilde'."""
    lowered = text.lower()
    for name in names:
        if re.search(r"\b" + re.escape(name) + r"\b", lowered):
            return name
    return None


def plausibility_gate(listing: Listing, site: SiteConfig) -> Verdict:
    """Is this actually an apartment, rather than a link that looked like one?

    A results page links to its own view routes ("kort", "liste", "filtrer")
    and those can match a site's listing pattern. On a site whose URL already
    applies our criteria the later gates trust the missing values and would let
    such a link through, so it is rejected here: a real listing always states
    at least a rent, a size, a room count or an address.
    """
    if any(value is not None for value in (listing.price, listing.rooms, listing.area_m2)):
        return ACCEPT
    if listing.postal_code or listing.address:
        return ACCEPT
    return Verdict(False, "no apartment details found on the page", stable=False)


def rooms_gate(listing: Listing, site: SiteConfig) -> Verdict:
    """At least :data:`MIN_ROOMS` rooms."""
    if listing.rooms is None:
        if "rooms" in site.url_enforced:
            return ACCEPT  # the site's own filter already guarantees this
        return Verdict(False, "rooms unknown and not filtered by the site URL", stable=False)
    if listing.rooms < MIN_ROOMS:
        return Verdict(False, f"{listing.rooms:g} rooms < {MIN_ROOMS}")
    return ACCEPT


def geography_gate(listing: Listing, site: SiteConfig) -> Verdict:
    """Copenhagen and the districts named in the brief."""
    if listing.postal_code:
        if listing.postal_code in COPENHAGEN_POSTAL_CODES:
            return ACCEPT
        return Verdict(False, f"postal code {listing.postal_code} outside Copenhagen")

    haystack = " ".join([listing.address, listing.city, listing.name, listing.source_text])
    excluded = _mentions(haystack, EXCLUDED_PLACE_NAMES)
    if excluded:
        return Verdict(False, f"location '{excluded}' outside Copenhagen")
    if _mentions(haystack, COPENHAGEN_PLACE_NAMES):
        return ACCEPT
    if "geo" in site.url_enforced:
        return ACCEPT
    return Verdict(False, "location unknown and not filtered by the site URL", stable=False)


def delevenlig_gate(listing: Listing, site: SiteConfig) -> Verdict:
    """Drop listings the site explicitly marks as not suitable for sharing.

    Only some sites state this at all. A listing that says nothing is kept and
    recorded as ``ukendt`` so it can be checked by hand — filtering those out
    would silently hide most of the market.
    """
    if listing.delevenlig is Delevenlig.NO:
        return Verdict(False, "marked as not delevenlig")
    return ACCEPT


DEFAULT_GATES: List[Gate] = [plausibility_gate, rooms_gate, geography_gate, delevenlig_gate]


def evaluate(listing: Listing, site: SiteConfig, gates: Optional[List[Gate]] = None) -> Verdict:
    for gate in gates or DEFAULT_GATES:
        verdict = gate(listing, site)
        if not verdict.accepted:
            return verdict
    return ACCEPT
