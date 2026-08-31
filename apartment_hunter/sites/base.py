"""Scraper interface and the config-driven default implementation."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import List

from ..config import COPENHAGEN_POSTAL_CODES, SiteConfig
from ..extract import extract_listings
from ..models import Listing
from ..render import BrowserSession

log = logging.getLogger(__name__)


class SiteScraper(ABC):
    """Produces the listings currently advertised on one site.

    Implementations return everything they find. Filtering, deduplication and
    the 'delevenlig' check happen downstream, so a scraper stays a thin
    site-shaped adapter.
    """

    def __init__(self, config: SiteConfig) -> None:
        self.config = config

    @property
    def key(self) -> str:
        return self.config.key

    @abstractmethod
    def scrape(self, session: BrowserSession) -> List[Listing]:
        ...

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} {self.config.key}>"


class GenericSiteScraper(SiteScraper):
    """Renders the overview page(s) and extracts every linked listing.

    This covers all of the configured sites: whatever the front-end stack, an
    apartment is always a link to its own detail page inside a card.
    """

    def scrape(self, session: BrowserSession) -> List[Listing]:
        config = self.config
        found: dict = {}

        for page_number, url in enumerate(self._page_urls(), start=1):
            log.info("[%s] rendering page %d: %s", config.key, page_number, url)
            html = session.render(url, config.render)
            listings = extract_listings(
                html,
                page_url=url,
                site_key=config.key,
                link_pattern=config.link_pattern,
                card_selector=config.card_selector,
                selectors=config.selectors,
                known_postal_codes=set(COPENHAGEN_POSTAL_CODES),
            )
            log.info("[%s] page %d yielded %d listings", config.key, page_number, len(listings))

            new_on_page = [item for item in listings if item.key not in found]
            for item in new_on_page:
                found[item.key] = item

            # Pagination past the end repeats or empties: stop early.
            if page_number > 1 and not new_on_page:
                log.info("[%s] no new listings on page %d — stopping", config.key, page_number)
                break

        return list(found.values())

    def _page_urls(self) -> List[str]:
        config = self.config
        if not config.page_url_template or config.max_pages <= 1:
            return [config.url]
        return [config.page_url_template.format(page=number) for number in range(1, config.max_pages + 1)]
