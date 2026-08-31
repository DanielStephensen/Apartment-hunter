"""Tests for the generated page."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from apartment_hunter import report
from apartment_hunter.models import Delevenlig, Listing
from apartment_hunter.store import ListingStore


def embedded_data(html: str) -> list:
    """Pull the JSON the page was built with back out of the page."""
    match = re.search(r"const DATA = (\[.*?\]);\n", html, re.DOTALL)
    assert match, "page carries no data"
    return json.loads(match.group(1).replace("<\\/", "</"))


class TestReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        store = ListingStore(self.root / "listings.csv")
        store.add([
            Listing(site="kereby", name="Ældst Allé 1", url="https://kereby.dk/bolig/a",
                    rooms=5, price=20000, area_m2=120, postal_code="2100",
                    scraped_date="2026-08-01"),
            Listing(site="kereby", name="Nyest Vej 2", url="https://kereby.dk/bolig/b",
                    rooms=6, price=30000, area_m2=150, postal_code="2200",
                    delevenlig=Delevenlig.YES, scraped_date="2026-08-31"),
        ])
        report.build(store, self.root / "index.html")
        self.html = (self.root / "index.html").read_text(encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_page_carries_every_listing(self):
        self.assertEqual(len(embedded_data(self.html)), 2)

    def test_rows_are_newest_first(self):
        dates = [row["date"] for row in embedded_data(self.html)]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_numbers_are_numbers_not_strings(self):
        first = embedded_data(self.html)[0]
        self.assertIsInstance(first["price"], (int, float))
        self.assertIsInstance(first["rooms"], (int, float))

    def test_site_keys_are_shown_as_names(self):
        self.assertEqual(embedded_data(self.html)[0]["site"], "Kereby")

    def test_delevenlig_is_carried_through(self):
        values = {row["name"]: row["delevenlig"] for row in embedded_data(self.html)}
        self.assertEqual(values["Nyest Vej 2"], "ja")
        self.assertEqual(values["Ældst Allé 1"], "ukendt")

    def test_the_page_is_self_contained(self):
        # GitHub Pages serves it as a static file; no build step, no fetches.
        self.assertNotIn("<script src=", self.html)
        self.assertNotIn("fetch(", self.html)

    def test_a_script_tag_in_a_title_cannot_break_out(self):
        store = ListingStore(self.root / "evil.csv")
        store.add([Listing(site="kereby", name="</script><b>x", url="https://kereby.dk/bolig/c",
                           rooms=5, scraped_date="2026-08-31")])
        report.build(store, self.root / "evil.html")
        html = (self.root / "evil.html").read_text(encoding="utf-8")
        self.assertNotIn("</script><b>", html)
        self.assertEqual(len(embedded_data(html)), 1)


if __name__ == "__main__":
    unittest.main()
