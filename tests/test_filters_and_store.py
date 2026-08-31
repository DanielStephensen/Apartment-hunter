"""Tests for the search criteria and the dedup store."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from apartment_hunter.config import SiteConfig
from apartment_hunter.filters import evaluate
from apartment_hunter.models import Delevenlig, Listing
from apartment_hunter.store import ListingStore, RejectionLog


def make_site(**overrides) -> SiteConfig:
    defaults = dict(key="test", name="Test", url="https://test.dk/", link_pattern=r"test\.dk/b/")
    defaults.update(overrides)
    return SiteConfig(**defaults)


def make_listing(**overrides) -> Listing:
    defaults = dict(
        site="test",
        name="Testvej 1",
        url="https://test.dk/b/1",
        rooms=5.0,
        postal_code="2100",
        price=20000,
    )
    defaults.update(overrides)
    return Listing(**defaults)


UNFILTERED = make_site(url_enforced=frozenset())
FILTERED = make_site(url_enforced=frozenset({"rooms", "geo"}))


class TestPlausibilityGate(unittest.TestCase):
    """A link that matched the pattern is not necessarily an apartment."""

    def test_a_view_route_with_no_details_is_rejected(self):
        # e.g. CEJ's own "kort"/"liste"/"filtrer" pages, which used to be
        # accepted on sites we trust for room and location filtering.
        junk = make_listing(rooms=None, price=None, area_m2=None,
                            postal_code=None, address="", name="Kort")
        verdict = evaluate(junk, FILTERED)
        self.assertFalse(verdict.accepted)
        self.assertIn("no apartment details", verdict.reason)

    def test_any_single_detail_is_enough(self):
        base = dict(rooms=None, price=None, area_m2=None, postal_code=None, address="")
        for field, value in [("price", 20000), ("area_m2", 130), ("postal_code", "2100"),
                             ("address", "Testvej 1, 2100 København Ø")]:
            listing = make_listing(**{**base, field: value})
            self.assertTrue(evaluate(listing, FILTERED).accepted, field)

    def test_a_missing_page_is_not_written_off_permanently(self):
        junk = make_listing(rooms=None, price=None, area_m2=None,
                            postal_code=None, address="", name="")
        self.assertFalse(evaluate(junk, FILTERED).stable)


class TestRoomsGate(unittest.TestCase):
    def test_accepts_five_or_more(self):
        self.assertTrue(evaluate(make_listing(rooms=5), UNFILTERED).accepted)
        self.assertTrue(evaluate(make_listing(rooms=7), UNFILTERED).accepted)

    def test_rejects_fewer(self):
        verdict = evaluate(make_listing(rooms=4), UNFILTERED)
        self.assertFalse(verdict.accepted)
        self.assertIn("4 rooms", verdict.reason)

    def test_a_site_filtered_by_url_is_trusted_when_the_card_is_terse(self):
        self.assertTrue(evaluate(make_listing(rooms=None), FILTERED).accepted)

    def test_an_unfiltered_site_must_state_the_room_count(self):
        self.assertFalse(evaluate(make_listing(rooms=None), UNFILTERED).accepted)

    def test_a_parsed_room_count_is_checked_even_on_a_filtered_site(self):
        # The site's own filter can silently break; what we can read, we check.
        self.assertFalse(evaluate(make_listing(rooms=2), FILTERED).accepted)


class TestGeographyGate(unittest.TestCase):
    def test_accepts_copenhagen_districts(self):
        for postal in ["1050", "2100", "2200", "2300", "2400", "2450", "2500", "2900", "2770"]:
            self.assertTrue(evaluate(make_listing(postal_code=postal), UNFILTERED).accepted, postal)

    def test_rejects_the_rest_of_the_country(self):
        for postal in ["8000", "5000", "4000", "2750", "9000"]:
            self.assertFalse(evaluate(make_listing(postal_code=postal), UNFILTERED).accepted, postal)

    def test_falls_back_to_place_names(self):
        listing = make_listing(postal_code=None, address="", city="", source_text="Lejlighed på Østerbro")
        self.assertTrue(evaluate(listing, UNFILTERED).accepted)

    def test_rejects_suburbs_named_in_the_text(self):
        listing = make_listing(postal_code=None, source_text="Dejlig villa i Roskilde")
        self.assertFalse(evaluate(listing, UNFILTERED).accepted)

    def test_a_street_name_is_not_a_town(self):
        # "Roskildevej" is in Frederiksberg — the town filter must not fire.
        listing = make_listing(postal_code=None, address="Roskildevej 47, København")
        self.assertTrue(evaluate(listing, UNFILTERED).accepted)

    def test_postal_code_beats_stray_text(self):
        listing = make_listing(postal_code="2100", source_text="Tæt på motorvejen mod Roskilde")
        self.assertTrue(evaluate(listing, UNFILTERED).accepted)


class TestDelevenligGate(unittest.TestCase):
    def test_rejects_an_explicit_no(self):
        verdict = evaluate(make_listing(delevenlig=Delevenlig.NO), UNFILTERED)
        self.assertFalse(verdict.accepted)
        self.assertIn("delevenlig", verdict.reason)

    def test_keeps_yes_and_unknown(self):
        # Only some sites state it; treating silence as "no" would hide most
        # of the market.
        self.assertTrue(evaluate(make_listing(delevenlig=Delevenlig.YES), UNFILTERED).accepted)
        self.assertTrue(evaluate(make_listing(delevenlig=Delevenlig.UNKNOWN), UNFILTERED).accepted)


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "listings.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip(self):
        store = ListingStore(self.path)
        store.add([make_listing(scraped_date="2026-08-31")])
        store.save()

        reloaded = ListingStore(self.path)
        self.assertEqual(len(reloaded), 1)
        self.assertIn("https://test.dk/b/1", reloaded)

    def test_a_known_listing_is_never_reported_twice(self):
        store = ListingStore(self.path)
        store.add([make_listing(scraped_date="2026-08-30")])
        store.save()

        reloaded = ListingStore(self.path)
        again = reloaded.select_new([make_listing(scraped_date="2026-08-31")])
        self.assertEqual(again, [])

    def test_url_variants_of_one_listing_are_the_same_row(self):
        store = ListingStore(self.path)
        store.add([make_listing(url="https://test.dk/b/1")])
        fresh = store.select_new([make_listing(url="https://www.test.dk/b/1/?utm_source=mail")])
        self.assertEqual(fresh, [])

    def test_duplicates_within_one_batch_collapse(self):
        store = ListingStore(self.path)
        added = store.add([make_listing(), make_listing(), make_listing(url="https://test.dk/b/2")])
        self.assertEqual(len(added), 2)

    def test_saved_rows_are_newest_first(self):
        store = ListingStore(self.path)
        store.add([
            make_listing(url="https://test.dk/b/old", scraped_date="2026-08-01"),
            make_listing(url="https://test.dk/b/new", scraped_date="2026-08-31"),
        ])
        store.save()
        rows = ListingStore(self.path).rows
        self.assertEqual(rows[0]["scraped_date"], "2026-08-31")


class TestRejectionStability(unittest.TestCase):
    """Which rejections may be remembered, and which must stay open."""

    def test_a_fact_we_read_is_settled(self):
        self.assertTrue(evaluate(make_listing(rooms=3), UNFILTERED).stable)
        self.assertTrue(evaluate(make_listing(postal_code="8000"), UNFILTERED).stable)
        self.assertTrue(evaluate(make_listing(delevenlig=Delevenlig.NO), UNFILTERED).stable)

    def test_a_gap_in_our_information_is_not(self):
        # The page may simply have been slow; do not write the flat off forever.
        self.assertFalse(evaluate(make_listing(rooms=None), UNFILTERED).stable)
        listing = make_listing(postal_code=None, address="", city="", name="", source_text="")
        self.assertFalse(evaluate(listing, UNFILTERED).stable)


class TestRejectionLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "rejected.csv"

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_recorded_rejection_survives_a_restart(self):
        log = RejectionLog(self.path)
        log.record(make_listing(), "3 rooms < 5", "2026-08-31")
        log.save()

        reloaded = RejectionLog(self.path)
        self.assertIn(make_listing(), reloaded)
        self.assertIn("https://test.dk/b/1", reloaded)

    def test_an_unrecorded_listing_is_not_in_the_log(self):
        log = RejectionLog(self.path)
        self.assertNotIn(make_listing(), log)

    def test_first_seen_is_preserved_when_seen_again(self):
        log = RejectionLog(self.path)
        log.record(make_listing(), "3 rooms < 5", "2026-08-01")
        log.record(make_listing(), "3 rooms < 5", "2026-08-31")
        log.save()

        row = next(iter(RejectionLog(self.path)._rows.values()))
        self.assertEqual(row["first_seen"], "2026-08-01")
        self.assertEqual(row["last_seen"], "2026-08-31")

    def test_an_empty_log_writes_no_file(self):
        RejectionLog(self.path).save()
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
