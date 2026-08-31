"""Orchestration: scrape → dedup → enrich → filter → store.

The order matters. Deduplication runs *before* detail pages are opened, so a
daily run only pays for apartments it has never seen. Cheap rejects (wrong room
count, wrong end of the country) are dropped even earlier.
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .config import REJECTIONS_CSV, SiteConfig, enabled_sites
from .detail import enrich_all
from .filters import evaluate, geography_gate, rooms_gate
from .models import Listing
from .render import BrowserSession
from .sites import get_scraper
from .store import ListingStore, RejectionLog

log = logging.getLogger(__name__)


@dataclass
class SiteResult:
    site: str
    name: str
    scraped: int = 0
    already_known: int = 0
    rejected: int = 0
    new: List[Listing] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass
class RunSummary:
    started_at: str
    results: List[SiteResult] = field(default_factory=list)
    rejections: Optional[RejectionLog] = None

    @property
    def new_listings(self) -> List[Listing]:
        return [listing for result in self.results for listing in result.new]

    @property
    def failed_sites(self) -> List[SiteResult]:
        return [result for result in self.results if not result.ok]

    def log_report(self) -> None:
        log.info("─" * 68)
        for result in self.results:
            if result.ok:
                log.info(
                    "%-22s scraped=%-4d known=%-4d rejected=%-4d NEW=%d",
                    result.name, result.scraped, result.already_known, result.rejected, len(result.new),
                )
            else:
                log.error("%-22s FAILED: %s", result.name, result.error)
        log.info("─" * 68)
        log.info("%d new listing(s) across %d site(s)", len(self.new_listings), len(self.results))


def _prefilter(listings: List[Listing], site: SiteConfig) -> tuple:
    """Drop listings we can rule out from the card alone.

    Only gates that need no extra information run here; anything uncertain is
    passed on so the detail page gets a chance to complete it.
    """
    kept, dropped = [], 0
    for listing in listings:
        if listing.rooms is not None and not rooms_gate(listing, site).accepted:
            dropped += 1
            continue
        if listing.postal_code and not geography_gate(listing, site).accepted:
            dropped += 1
            continue
        kept.append(listing)
    return kept, dropped


def scrape_site(
    site: SiteConfig,
    session: BrowserSession,
    store: ListingStore,
    rejections: RejectionLog,
    scraped_date: str,
    fetch_details: bool = True,
) -> SiteResult:
    result = SiteResult(site=site.key, name=site.name)
    try:
        listings = get_scraper(site).scrape(session)
    except Exception as exc:  # noqa: BLE001 - one broken site must not end the run
        log.exception("[%s] scrape failed", site.key)
        result.error = f"{type(exc).__name__}: {exc}"
        return result

    result.scraped = len(listings)

    candidates, cheap_rejects = _prefilter(listings, site)
    result.rejected += cheap_rejects

    fresh = store.select_new(candidates)
    result.already_known = len(candidates) - len(fresh)

    # Already ruled out on an earlier run — no need to open the page again.
    settled = [listing for listing in fresh if listing in rejections]
    result.already_known += len(settled)
    fresh = [listing for listing in fresh if listing not in rejections]

    log.info("[%s] %d scraped, %d new to check", site.key, len(listings), len(fresh))

    if fresh and fetch_details and site.fetch_detail:
        fresh = enrich_all(fresh, session)

    for listing in fresh:
        verdict = evaluate(listing, site)
        if verdict.accepted:
            result.new.append(dataclasses.replace(listing, scraped_date=scraped_date))
            continue

        result.rejected += 1
        log.info("[%s] rejected %s — %s", site.key, listing.url, verdict.reason)
        if verdict.stable:
            rejections.record(listing, verdict.reason, scraped_date)

    return result


def run(
    store: ListingStore,
    sites: Optional[List[SiteConfig]] = None,
    *,
    rejections: Optional[RejectionLog] = None,
    headless: bool = True,
    fetch_details: bool = True,
    scraped_date: Optional[str] = None,
) -> RunSummary:
    """Scrape every site and record whatever is new."""
    sites = sites if sites is not None else enabled_sites()
    rejections = rejections if rejections is not None else RejectionLog(REJECTIONS_CSV)
    scraped_date = scraped_date or datetime.now().strftime("%Y-%m-%d")
    summary = RunSummary(started_at=datetime.now().isoformat(timespec="seconds"), rejections=rejections)

    with BrowserSession(headless=headless) as session:
        for site in sites:
            log.info("=== %s ===", site.name)
            result = scrape_site(site, session, store, rejections, scraped_date, fetch_details)
            store.add(result.new)
            summary.results.append(result)

    summary.log_report()
    return summary
