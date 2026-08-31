"""Site definitions and search criteria.

Adding a site normally means adding one :class:`SiteConfig` entry below — the
generic scraper handles the rest. Only reach for a custom scraper in
``sites/`` when a site cannot be expressed here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import FrozenSet, Optional

from .extract import FieldSelectors
from .render import RenderOptions

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LISTINGS_CSV = DATA_DIR / "listings.csv"
#: Listings already examined and ruled out, so they are not re-fetched daily.
REJECTIONS_CSV = DATA_DIR / "rejected.csv"
SITE_DIR = ROOT / "docs"

#: Minimum number of rooms we are interested in.
MIN_ROOMS = 5

#: Copenhagen and the districts named in the search brief: Østerbro (2100),
#: Hellerup (2900), Amager / Copenhagen S (2300, 2770), Nordvest (2400),
#: plus the inner city, Frederiksberg, Valby, Sydhavn and Nordhavn.
COPENHAGEN_POSTAL_CODES: FrozenSet[str] = frozenset(
    [str(code) for code in range(1000, 2001)]  # København K/V + Frederiksberg C
    + [
        "2100",  # København Ø / Østerbro
        "2150",  # Nordhavn
        "2200",  # København N / Nørrebro
        "2300",  # København S / Amager, Ørestad, Amager Strand
        "2400",  # København NV / Nordvest
        "2450",  # København SV / Sydhavn
        "2500",  # Valby
        "2770",  # Kastrup (Amager)
        "2900",  # Hellerup
    ]
)

#: Used when a listing has no parsable postal code but names its district.
COPENHAGEN_PLACE_NAMES: FrozenSet[str] = frozenset(
    {
        "københavn", "kobenhavn", "copenhagen", "kbh",
        "frederiksberg", "østerbro", "osterbro", "nørrebro", "norrebro",
        "vesterbro", "amager", "amagerbro", "amager strand", "islands brygge",
        "ørestad", "orestad", "christianshavn", "sydhavn", "sydhavnen",
        "valby", "nordvest", "nordhavn", "hellerup", "kastrup",
    }
)

#: Places that are *not* in scope even though their text mentions Copenhagen.
EXCLUDED_PLACE_NAMES: FrozenSet[str] = frozenset(
    {"roskilde", "køge", "koge", "hillerød", "hillerod", "farum", "herlev",
     "glostrup", "brøndby", "brondby", "hvidovre", "vallensbæk", "vallensbaek",
     "bagsværd", "bagsvaerd", "egedal", "hjørring", "hjorring", "odense",
     "randers", "aalborg", "aarhus", "århus", "esbjerg", "kolding", "horsens"}
)


@dataclass(frozen=True)
class SiteConfig:
    """Everything needed to scrape one rental site."""

    key: str
    name: str
    url: str

    link_pattern: str
    """Regex an absolute URL must match to count as an apartment detail page."""

    render: RenderOptions = field(default_factory=RenderOptions)

    card_selector: Optional[str] = None
    """Optional CSS for the card container; omitted means auto-detect."""

    selectors: FieldSelectors = field(default_factory=FieldSelectors)

    page_url_template: Optional[str] = None
    """URL template with ``{page}`` when results are paginated by URL."""

    max_pages: int = 1

    url_enforced: FrozenSet[str] = frozenset()
    """Which criteria the site's own URL already applies: ``rooms``, ``geo``.

    A criterion listed here is trusted when we cannot parse the value off the
    card, so a listing is not dropped just because its card is terse. Anything
    we *can* parse is still checked.
    """

    fetch_detail: bool = True
    """Open each new listing's page to look for the 'delevenlig' wording."""

    enabled: bool = True


#: Shared render profile for the JavaScript-heavy sites.
_SPA = RenderOptions(wait_ms=4000, scroll=True)


SITES: list[SiteConfig] = [
    SiteConfig(
        key="cej",
        name="CEJ Udlejning",
        url=(
            "https://udlejning.cej.dk/find-bolig/overblik?collection=residences"
            "&minRooms=5&monthlyPrice=0-50000"
            "&p=frederiksberg%2Cfrederiksberg+c%2Ck%C3%B8benhavn+k%2Ck%C3%B8benhavn+n"
            "%2Ck%C3%B8benhavn+nv%2Ck%C3%B8benhavn+v%2Ck%C3%B8benhavn+%C3%B8"
        ),
        # Listings live at /boliger/<hex id>; everything under /find-bolig/ is
        # the search app's own views (overblik, kort, liste, filtrer).
        link_pattern=r"cej\.dk/boliger/[0-9a-f]{8,}",
        render=RenderOptions(wait_ms=6000, scroll=True),
        url_enforced=frozenset({"rooms", "geo"}),
    ),
    SiteConfig(
        key="heimstaden",
        name="Heimstaden",
        url="https://www.heimstaden.dk/ledige-lejeboliger/?rooms=5%2C10&search=k%C3%B8benhavn",
        link_pattern=r"heimstaden\.dk/lejebolig/[^?#]+",
        render=_SPA,
        url_enforced=frozenset({"rooms", "geo"}),
    ),
    SiteConfig(
        key="kereby",
        name="Kereby",
        url="https://kereby.dk/bolig/",
        link_pattern=r"kereby\.dk/bolig/[^?#]+",
        render=RenderOptions(wait_ms=2500, scroll=True),
        # No filters in the URL: our own room and area criteria must decide.
        url_enforced=frozenset(),
    ),
    SiteConfig(
        key="cityapartment",
        name="City Apartment",
        url="https://cityapartment.dk/da/lejeboliger-koebenhavn/?_sfm_pris=0+50000&_sfm_ikon_m2=130+300",
        link_pattern=r"cityapartment\.dk/da/(?:lejebolig|bolig|ejendom)[^?#]*/[^?#]+",
        render=_SPA,
        # The URL filters price and size only — rooms are on us.
        url_enforced=frozenset({"geo"}),
    ),
    SiteConfig(
        key="propstep",
        name="Propstep",
        url=(
            "https://propstep.com/da-DK/soeg?roomsMin=5&page=1"
            "&zipCodes=1050,1100,1150,1200,1250,1300,1350,1400,1450,1500,1550,1600,"
            "1650,1700,1750,1800,1850,1900,1950,2000,2100,2150,2200,2300,2400,2450,"
            "2500,2770,2900"
        ),
        link_pattern=r"propstep\.com/da-DK/bolig/[^?#]+",
        render=_SPA,
        url_enforced=frozenset({"rooms", "geo"}),
    ),
    SiteConfig(
        key="nextkey",
        name="NextKey",
        url="https://nextkey.dk/bolig/?_min_boligareal=0%2C_&_vaerelser=5&_omrade=K%C3%B8benhavn",
        link_pattern=r"nextkey\.dk/(?:bolig|lejemaal|lejebolig)/[^?#]+",
        render=_SPA,
        url_enforced=frozenset({"rooms", "geo"}),
    ),
    SiteConfig(
        key="danskboligformidling",
        name="Dansk Boligformidling",
        url=(
            "https://www.danskboligformidling.dk/lej-bolig/?SearchTerm=K%C3%B8benhavn"
            "&Rooms=5%2B&SortBy=newest&Page=1"
        ),
        link_pattern=r"danskboligformidling\.dk/(?:lej-bolig|bolig|lejemaal)/[^?#]+",
        render=_SPA,
        page_url_template=(
            "https://www.danskboligformidling.dk/lej-bolig/?SearchTerm=K%C3%B8benhavn"
            "&Rooms=5%2B&SortBy=newest&Page={page}"
        ),
        max_pages=3,
        url_enforced=frozenset({"rooms", "geo"}),
    ),
    SiteConfig(
        key="akf_boligportal",
        name="AKF Holding (Boligportal)",
        url=(
            "https://www.boligportal.dk/cp/akf-holding/lejeboliger/alle-byer/5+-v%C3%A6relser/"
            "?company_filter_key=wE6UFvlbmfbVlFuXTkq3QnwGoTxgFqj7"
        ),
        link_pattern=r"boligportal\.dk/(?:lejlighed|lejebolig|hus|vaerelse|rækkehus)[^?#]*/[^?#]+",
        render=_SPA,
        # Rooms are filtered by the URL, but it searches *all* cities.
        url_enforced=frozenset({"rooms"}),
    ),
    SiteConfig(
        key="eltoftnielsen",
        name="Eltoft Nielsen",
        url=(
            "https://eltoftnielsen.dk/boliger/udlejning/?_search=K%C3%B8benhavn%20"
            "&_salgleje=leje&_kvadratmeter=160.00%2C202.00"
        ),
        link_pattern=r"eltoftnielsen\.dk/bolig/[^?#]+",
        render=_SPA,
        url_enforced=frozenset({"geo"}),
    ),
    SiteConfig(
        key="juliliving",
        name="Juli Living",
        url="https://juliliving.dk/find-lejebolig/",
        # Units live at /<ejendom>-bolig/?boligID=NNNN — the id in the query
        # string is what separates the flats within one building.
        link_pattern=r"juliliving\.dk/[^/?#]+-bolig/\?.*boligID=\d+",
        render=RenderOptions(
            wait_for="a.jlet-unit-card__full-link",
            wait_ms=9000,
            scroll=True,
        ),
        url_enforced=frozenset(),
    ),
    SiteConfig(
        key="balder",
        name="Balder",
        url=(
            "https://www.balder.dk/lejeboliger?areas=K%C3%B8benhavn+SV,Amager+Strand,"
            "%C3%98restad,Valby,%C3%98sterbro&rooms=5"
        ),
        link_pattern=r"balder\.dk/lejeboliger/[^?#]+",
        render=_SPA,
        url_enforced=frozenset({"rooms", "geo"}),
    ),
]


def enabled_sites() -> list[SiteConfig]:
    return [site for site in SITES if site.enabled]


def site_by_key(key: str) -> SiteConfig:
    for site in SITES:
        if site.key == key:
            return site
    raise KeyError(f"unknown site: {key}")
