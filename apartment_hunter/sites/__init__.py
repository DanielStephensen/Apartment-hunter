"""Scraper registry.

Every site uses :class:`GenericSiteScraper` unless it is registered here with a
custom class — register one only when a site genuinely cannot be expressed as a
:class:`~apartment_hunter.config.SiteConfig`.

    @register("example")
    class ExampleScraper(SiteScraper):
        def scrape(self, session): ...
"""

from __future__ import annotations

from typing import Callable, Dict, Type

from ..config import SiteConfig
from .base import GenericSiteScraper, SiteScraper

_REGISTRY: Dict[str, Type[SiteScraper]] = {}


def register(site_key: str) -> Callable[[Type[SiteScraper]], Type[SiteScraper]]:
    def decorator(scraper_class: Type[SiteScraper]) -> Type[SiteScraper]:
        _REGISTRY[site_key] = scraper_class
        return scraper_class

    return decorator


def get_scraper(config: SiteConfig) -> SiteScraper:
    return _REGISTRY.get(config.key, GenericSiteScraper)(config)


__all__ = ["GenericSiteScraper", "SiteScraper", "get_scraper", "register"]
