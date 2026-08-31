"""Core data types shared by every scraper."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class Delevenlig(str, Enum):
    """Whether a listing is advertised as suitable for sharing (roommates).

    Only some of the sites state this at all, so ``UNKNOWN`` is a normal and
    common outcome rather than an error.
    """

    YES = "ja"
    NO = "nej"
    UNKNOWN = "ukendt"


#: Query parameters that identify the visit rather than the apartment.
TRACKING_PARAMS = frozenset(
    {
        "gclid", "gbraid", "wbraid", "fbclid", "msclkid", "dclid", "yclid",
        "mc_cid", "mc_eid", "igshid", "ref", "referrer", "source", "_ga", "_gl",
        "hsa_acc", "hsa_cam", "hsa_grp", "hsa_ad", "hsa_src", "hsa_tgt",
        "hsa_kw", "hsa_mt", "hsa_net", "hsa_ver", "cx", "ie", "hl",
    }
)


def canonical_url(url: str) -> str:
    """Normalise a listing URL so the same flat always yields the same key.

    Tracking parameters and trailing slashes vary between runs and would make
    the store re-report known flats. Meaningful parameters are kept and sorted:
    some sites (Juli Living, for one) identify the individual unit in the query
    string, so stripping it wholesale would collapse a whole building into one
    row.
    """
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/") or "/"

    kept = sorted(
        (name, value)
        for name, value in parse_qsl(parts.query, keep_blank_values=False)
        if name.lower() not in TRACKING_PARAMS and not name.lower().startswith("utm_")
    )
    return urlunsplit((parts.scheme.lower() or "https", host, path, urlencode(kept), ""))


def listing_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode("utf-8")).hexdigest()[:16]


@dataclass
class Listing:
    """One apartment as scraped from a site."""

    site: str
    name: str
    url: str
    price: Optional[int] = None
    rooms: Optional[float] = None
    area_m2: Optional[int] = None
    address: str = ""
    postal_code: Optional[str] = None
    city: str = ""
    delevenlig: Delevenlig = Delevenlig.UNKNOWN
    scraped_date: str = ""
    # Free text used by the filters (card text + detail page text when fetched).
    source_text: str = field(default="", repr=False, compare=False)

    @property
    def id(self) -> str:
        return listing_id(self.url)

    @property
    def key(self) -> str:
        return canonical_url(self.url)

    def to_row(self) -> dict:
        row = asdict(self)
        row.pop("source_text", None)
        row["id"] = self.id
        row["delevenlig"] = self.delevenlig.value
        row["url"] = self.url
        return row


#: Column order of the dedup store, and of the published table.
CSV_COLUMNS = [
    "id",
    "scraped_date",
    "name",
    "url",
    "price",
    "rooms",
    "area_m2",
    "address",
    "postal_code",
    "city",
    "site",
    "delevenlig",
]
