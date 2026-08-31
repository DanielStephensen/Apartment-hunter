"""Extraction tests over card markup shaped like the real sites'."""

from __future__ import annotations

import unittest

from apartment_hunter.extract import extract_listings
from apartment_hunter.models import Delevenlig, canonical_url

# A results grid: two cards, plus navigation that must not be mistaken for one.
GRID = """
<html><body>
  <nav><a href="/bolig/">Alle boliger</a><a href="/om-os/">Om os</a></nav>
  <main>
    <div class="grid">
      <article class="card">
        <span class="badge">Delevenlig</span>
        <a href="/bolig/roskildevej-47-st-2000-frederiksberg/">
          <img alt="Roskildevej 47">
          <h3>Roskildevej 47, st., 2000 Frederiksberg</h3>
        </a>
        <p>6-værelses lejlighed · 152 m<sup>2</sup></p>
        <p>Husleje 34.667 kr. pr. md. Depositum 104.001 kr.</p>
      </article>
      <article class="card">
        <a href="/bolig/stormgade-35-4-th-1555-kobenhavn-v/">
          <h3>Stormgade 35, 4. th, 1555 København V</h3>
        </a>
        <p>7 vær. 180 m<sup>2</sup> 32.209 kr.</p>
      </article>
    </div>
  </main>
</body></html>
"""

PAGE_URL = "https://kereby.dk/bolig/"
PATTERN = r"kereby\.dk/bolig/[^?#]+"


class TestExtractListings(unittest.TestCase):
    def setUp(self):
        self.listings = sorted(
            extract_listings(GRID, page_url=PAGE_URL, site_key="kereby", link_pattern=PATTERN),
            key=lambda item: item.url,
        )

    def test_finds_both_cards_and_ignores_navigation(self):
        self.assertEqual(len(self.listings), 2)

    def test_fields_come_from_the_right_card(self):
        roskildevej = next(item for item in self.listings if "roskildevej" in item.url)
        self.assertEqual(roskildevej.rooms, 6)
        self.assertEqual(roskildevej.area_m2, 152)
        self.assertEqual(roskildevej.price, 34_667)  # not the deposit
        self.assertEqual(roskildevej.postal_code, "2000")
        self.assertEqual(roskildevej.delevenlig, Delevenlig.YES)

    def test_cards_do_not_bleed_into_each_other(self):
        stormgade = next(item for item in self.listings if "stormgade" in item.url)
        self.assertEqual(stormgade.rooms, 7)
        self.assertEqual(stormgade.price, 32_209)
        self.assertEqual(stormgade.delevenlig, Delevenlig.UNKNOWN)

    def test_name_is_the_address_without_the_badge(self):
        roskildevej = next(item for item in self.listings if "roskildevej" in item.url)
        self.assertEqual(roskildevej.name, "Roskildevej 47, st., 2000 Frederiksberg")
        self.assertNotIn("Delevenlig", roskildevej.name)

    def test_the_address_is_cleaned_too(self):
        # Otherwise the page shows the address again as a near-identical
        # sub-line, differing only by the badge.
        roskildevej = next(item for item in self.listings if "roskildevej" in item.url)
        self.assertEqual(roskildevej.address, roskildevej.name)

    def test_urls_are_absolute(self):
        for listing in self.listings:
            self.assertTrue(listing.url.startswith("https://kereby.dk/bolig/"))


class TestLinkSelection(unittest.TestCase):
    def test_the_overview_page_itself_is_not_a_listing(self):
        html = '<a href="https://kereby.dk/bolig/">Boliger</a>'
        self.assertEqual(
            extract_listings(html, page_url=PAGE_URL, site_key="kereby", link_pattern=PATTERN), []
        )

    def test_repeated_links_to_one_listing_yield_one_row(self):
        html = """
          <div class="card">
            <a href="/bolig/x-1234-kobenhavn/"><img alt="foto"></a>
            <a href="/bolig/x-1234-kobenhavn/"><h3>Xvej 2, 1234 København K</h3></a>
            <p>5 vær. 20.000 kr.</p>
          </div>"""
        listings = extract_listings(html, page_url=PAGE_URL, site_key="kereby", link_pattern=PATTERN)
        self.assertEqual(len(listings), 1)
        self.assertEqual(listings[0].rooms, 5)


class TestCanonicalUrl(unittest.TestCase):
    def test_ignores_tracking_and_trailing_slash(self):
        self.assertEqual(
            canonical_url("https://www.balder.dk/lejeboliger/abc/?utm_source=x&gclid=y"),
            canonical_url("https://balder.dk/lejeboliger/abc"),
        )

    def test_keeps_the_identifying_query_parameter(self):
        # Juli Living puts the unit id in the query string; dropping it would
        # collapse every flat in a building into a single row.
        first = canonical_url("https://juliliving.dk/siljangade-bolig/?boligID=2068")
        second = canonical_url("https://juliliving.dk/siljangade-bolig/?boligID=7076")
        self.assertNotEqual(first, second)

    def test_parameter_order_does_not_matter(self):
        self.assertEqual(
            canonical_url("https://x.dk/a?b=2&a=1"), canonical_url("https://x.dk/a?a=1&b=2")
        )


if __name__ == "__main__":
    unittest.main()
