"""Developer tool: inspect what a site's overview page actually links to.

Use it when adding a site or when a site stops returning results, to work out
the right ``link_pattern`` for its :class:`SiteConfig`:

    python -m tools.discover kereby balder
    python -m tools.discover --all --save-html
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from apartment_hunter.config import SITES, site_by_key
from apartment_hunter.extract import extract_listings
from apartment_hunter.render import BrowserSession


def link_shapes(html: str, page_url: str, limit: int = 25) -> None:
    """Print link path shapes on the page, most frequent first."""
    soup = BeautifulSoup(html, "lxml")
    host = urlsplit(page_url).netloc.lower().lstrip("www.")

    shapes: Counter = Counter()
    examples: dict = {}
    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(page_url, anchor["href"])
        parts = urlsplit(absolute)
        if not parts.netloc.lower().lstrip("www.").endswith(host):
            continue
        segments = [segment for segment in parts.path.split("/") if segment]
        if not segments:
            continue
        # Generalise the last segment so per-listing slugs collapse together.
        shape = "/" + "/".join(segments[:-1] + ["<slug>"]) if len(segments) > 1 else "/<slug>"
        shapes[shape] += 1
        examples.setdefault(shape, absolute)

    print(f"  link shapes ({len(shapes)} distinct):")
    for shape, count in shapes.most_common(limit):
        print(f"    {count:4d}  {shape:<45} e.g. {examples[shape]}")


def main(argv: list) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("keys", nargs="*", help="site keys to inspect (default: all)")
    parser.add_argument("--all", action="store_true", help="inspect every configured site")
    parser.add_argument("--save-html", action="store_true", help="dump rendered HTML next to this tool")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    configs = [site_by_key(key) for key in args.keys] if args.keys else list(SITES)
    out_dir = Path(__file__).resolve().parent / "_rendered"

    with BrowserSession(headless=not args.headed) as session:
        for config in configs:
            print(f"\n=== {config.key} ({config.name}) ===\n  {config.url}")
            try:
                html = session.render(config.url, config.render)
            except Exception as exc:  # noqa: BLE001 - diagnostics tool
                print(f"  RENDER FAILED: {exc}")
                continue

            if args.save_html:
                out_dir.mkdir(exist_ok=True)
                path = out_dir / f"{config.key}.html"
                path.write_text(html, encoding="utf-8")
                print(f"  saved {len(html):,} bytes to {path}")

            link_shapes(html, config.url)

            matched = extract_listings(
                html,
                page_url=config.url,
                site_key=config.key,
                link_pattern=config.link_pattern,
                card_selector=config.card_selector,
                selectors=config.selectors,
            )
            print(f"  current pattern {config.link_pattern!r} matched {len(matched)} listings")
            for listing in matched[:4]:
                print(
                    f"    - {listing.name[:52]!r} rooms={listing.rooms} "
                    f"price={listing.price} m2={listing.area_m2} postal={listing.postal_code}"
                )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
