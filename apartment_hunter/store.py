"""The CSV of everything seen so far.

The file is both the dedup memory and the data behind the published page. It is
keyed on the canonical listing URL, so re-running the scraper never re-reports
an apartment that has already been recorded.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Dict, Iterable, List

from .models import CSV_COLUMNS, Listing, canonical_url

log = logging.getLogger(__name__)


class ListingStore:
    """Append-only store of scraped listings, keyed by canonical URL."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._rows: Dict[str, dict] = {}
        self.load()

    # ------------------------------------------------------------------ #

    def load(self) -> None:
        self._rows = {}
        if not self.path.exists():
            log.info("no store at %s yet — starting fresh", self.path)
            return
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                url = (row.get("url") or "").strip()
                if not url:
                    continue
                self._rows[canonical_url(url)] = row
        log.info("loaded %d known listings from %s", len(self._rows), self.path)

    def __len__(self) -> int:
        return len(self._rows)

    def __contains__(self, listing_or_url) -> bool:
        url = listing_or_url.url if isinstance(listing_or_url, Listing) else listing_or_url
        return canonical_url(url) in self._rows

    @property
    def rows(self) -> List[dict]:
        return list(self._rows.values())

    # ------------------------------------------------------------------ #

    def select_new(self, listings: Iterable[Listing]) -> List[Listing]:
        """Return only listings not already recorded (deduped within the batch)."""
        fresh: Dict[str, Listing] = {}
        for listing in listings:
            key = listing.key
            if key in self._rows or key in fresh:
                continue
            fresh[key] = listing
        return list(fresh.values())

    def add(self, listings: Iterable[Listing]) -> List[Listing]:
        """Record new listings in memory; call :meth:`save` to persist."""
        added = self.select_new(listings)
        for listing in added:
            self._rows[listing.key] = listing.to_row()
        return added

    def save(self) -> None:
        """Write the whole store, newest scrape date first."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rows = sorted(self._rows.values(), key=_sort_key, reverse=True)
        with self.path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})
        log.info("saved %d listings to %s", len(rows), self.path)


def _sort_key(row: dict) -> tuple:
    """Newest scrape date first, then a stable tiebreaker."""
    return (str(row.get("scraped_date") or ""), str(row.get("name") or ""))


REJECTION_COLUMNS = ["id", "url", "site", "reason", "first_seen", "last_seen"]


class RejectionLog:
    """Listings already examined and ruled out.

    Without this, an apartment that fails a criterion only visible on its own
    page — too few rooms, wrong end of town, explicitly not delevenlig — would
    be looked up again on every single run, forever. Only *settled* rejections
    are recorded: one caused by information we could not find stays open, so a
    page that was slow once is not written off permanently.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._rows: Dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        self._rows = {}
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                url = (row.get("url") or "").strip()
                if url:
                    self._rows[canonical_url(url)] = row
        log.info("loaded %d previously rejected listings", len(self._rows))

    def __len__(self) -> int:
        return len(self._rows)

    def __contains__(self, listing_or_url) -> bool:
        url = listing_or_url.url if isinstance(listing_or_url, Listing) else listing_or_url
        return canonical_url(url) in self._rows

    def record(self, listing: Listing, reason: str, date: str) -> None:
        key = listing.key
        existing = self._rows.get(key)
        self._rows[key] = {
            "id": listing.id,
            "url": listing.url,
            "site": listing.site,
            "reason": reason,
            "first_seen": (existing or {}).get("first_seen") or date,
            "last_seen": date,
        }

    def save(self) -> None:
        if not self._rows:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=REJECTION_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in sorted(self._rows.values(), key=lambda item: str(item.get("last_seen") or "")):
                writer.writerow({column: row.get(column, "") for column in REJECTION_COLUMNS})
        log.info("saved %d rejections to %s", len(self._rows), self.path)
