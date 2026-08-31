"""Command line entry point.

    python -m apartment_hunter                 # scrape everything, rebuild the page
    python -m apartment_hunter --site kereby   # one site, useful when debugging
    python -m apartment_hunter --dry-run       # scrape but do not touch the CSV
    python -m apartment_hunter --report-only   # rebuild the page from the CSV
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import List, Optional

from . import report
from .config import LISTINGS_CSV, SITE_DIR, enabled_sites, site_by_key
from .pipeline import run
from .store import ListingStore


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="apartment_hunter", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--site", action="append", dest="sites", metavar="KEY",
                        help="only scrape this site (repeatable)")
    parser.add_argument("--no-details", action="store_true",
                        help="skip detail pages (faster, but 'delevenlig' stays unknown)")
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--dry-run", action="store_true", help="do not write the CSV or the page")
    parser.add_argument("--report-only", action="store_true", help="rebuild the page from the CSV")
    parser.add_argument("--csv", default=str(LISTINGS_CSV), help="path to the listings CSV")
    parser.add_argument("--out", default=str(SITE_DIR / "index.html"), help="path of the generated page")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    from pathlib import Path

    store = ListingStore(Path(args.csv))

    if args.report_only:
        report.build(store, Path(args.out))
        _copy_csv(store, Path(args.out).parent)
        return 0

    sites = [site_by_key(key) for key in args.sites] if args.sites else enabled_sites()
    summary = run(store, sites, headless=not args.headed, fetch_details=not args.no_details)

    for listing in summary.new_listings:
        logging.info("NEW  %-9s %-52s %s", listing.site, listing.name[:52], listing.url)

    if args.dry_run:
        logging.info("dry run — nothing written")
    else:
        store.save()
        if summary.rejections is not None:
            summary.rejections.save()
        output = Path(args.out)
        report.build(store, output)
        _copy_csv(store, output.parent)

    # Fail the job only if every site broke — one flaky site is normal.
    if summary.failed_sites and len(summary.failed_sites) == len(summary.results):
        logging.error("every site failed")
        return 1
    return 0


def _copy_csv(store: ListingStore, destination_dir) -> None:
    """Publish the CSV next to the page so it can be downloaded."""
    from pathlib import Path
    from shutil import copyfile

    destination_dir = Path(destination_dir)
    if store.path.exists():
        destination_dir.mkdir(parents=True, exist_ok=True)
        copyfile(store.path, destination_dir / "listings.csv")


if __name__ == "__main__":
    sys.exit(main())
