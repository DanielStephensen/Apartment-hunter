"""Tests for the new-listing email."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from apartment_hunter import __main__ as cli
from apartment_hunter import notify
from apartment_hunter.config import NOTIFY_RECIPIENTS
from apartment_hunter.models import Delevenlig, Listing
from apartment_hunter.notify import SmtpConfig
from apartment_hunter.pipeline import RunSummary, SiteResult

CONFIGURED = {"SMTP_USER": "hunter@gmail.com", "SMTP_PASSWORD": "app-password"}


def listing(**overrides) -> Listing:
    fields = dict(
        site="kereby",
        name="Testvej 1",
        url="https://kereby.dk/bolig/a",
        price=18500,
        rooms=5,
        area_m2=130,
        address="Testvej 1, 3. th",
        postal_code="2100",
        city="København Ø",
        scraped_date="2026-09-07",
    )
    fields.update(overrides)
    return Listing(**fields)


class TestSmtpConfig(unittest.TestCase):
    def test_no_credentials_means_not_configured(self):
        self.assertIsNone(SmtpConfig.from_env({}))
        self.assertIsNone(SmtpConfig.from_env({"SMTP_USER": "hunter@gmail.com"}))
        self.assertIsNone(SmtpConfig.from_env({"SMTP_PASSWORD": "app-password"}))

    def test_blank_credentials_mean_not_configured(self):
        # Unset repository secrets arrive as empty strings, not as absent keys.
        self.assertIsNone(SmtpConfig.from_env({"SMTP_USER": "", "SMTP_PASSWORD": ""}))

    def test_gmail_is_the_default_server(self):
        config = SmtpConfig.from_env(CONFIGURED)
        self.assertEqual(config.host, "smtp.gmail.com")
        self.assertEqual(config.port, 587)

    def test_the_sender_defaults_to_the_login(self):
        self.assertEqual(SmtpConfig.from_env(CONFIGURED).sender, "hunter@gmail.com")

    def test_the_configured_recipients_are_used_by_default(self):
        self.assertEqual(SmtpConfig.from_env(CONFIGURED).recipients, tuple(NOTIFY_RECIPIENTS))

    def test_mail_to_overrides_the_recipients(self):
        config = SmtpConfig.from_env({**CONFIGURED, "MAIL_TO": "a@x.dk, b@y.dk;c@z.dk"})
        self.assertEqual(config.recipients, ("a@x.dk", "b@y.dk", "c@z.dk"))

    def test_an_unreadable_port_falls_back_to_the_default(self):
        self.assertEqual(SmtpConfig.from_env({**CONFIGURED, "SMTP_PORT": "nonsense"}).port, 587)
        self.assertEqual(SmtpConfig.from_env({**CONFIGURED, "SMTP_PORT": "465"}).port, 465)


class TestSubject(unittest.TestCase):
    def test_one_listing_is_singular(self):
        self.assertEqual(notify.subject([listing()]), "1 ny lejlighed i København")

    def test_several_listings_are_plural(self):
        self.assertEqual(notify.subject([listing(), listing()]), "2 nye lejligheder i København")


class TestMessage(unittest.TestCase):
    def setUp(self):
        self.config = SmtpConfig.from_env(CONFIGURED)

    def bodies(self, listings):
        message = notify.build_message(listings, self.config, generated="07-09-2026 11:00")
        text = message.get_body(("plain",)).get_content()
        html = message.get_body(("html",)).get_content()
        return text, html

    def test_both_a_text_and_an_html_part_are_present(self):
        message = notify.build_message([listing()], self.config)
        self.assertIsNotNone(message.get_body(("plain",)))
        self.assertIsNotNone(message.get_body(("html",)))

    def test_every_recipient_is_addressed(self):
        message = notify.build_message([listing()], self.config)
        for address in NOTIFY_RECIPIENTS:
            self.assertIn(address, message["To"])

    def test_the_link_to_the_listing_is_in_both_parts(self):
        text, html = self.bodies([listing()])
        self.assertIn("https://kereby.dk/bolig/a", text)
        self.assertIn("https://kereby.dk/bolig/a", html)

    def test_prices_are_grouped_the_danish_way(self):
        text, html = self.bodies([listing(price=18500)])
        self.assertIn("18.500 kr.", text)
        self.assertIn("18.500 kr.", html)

    def test_missing_facts_are_named_not_blank(self):
        text, _ = self.bodies([listing(price=None, rooms=None, area_m2=None)])
        self.assertIn("pris ukendt", text)
        self.assertIn("vær. ukendt", text)
        self.assertIn("m² ukendt", text)

    def test_half_rooms_survive(self):
        text, _ = self.bodies([listing(rooms=5.5)])
        self.assertIn("5,5 vær.", text)
        self.assertNotIn("5.5", text)

    def test_whole_rooms_have_no_decimal(self):
        text, _ = self.bodies([listing(rooms=5.0)])
        self.assertIn("5 vær.", text)

    def test_the_site_key_is_shown_as_its_name(self):
        text, html = self.bodies([listing()])
        self.assertIn("Kereby", text)
        self.assertIn("Kereby", html)

    def test_delevenlig_is_only_mentioned_when_it_is_known(self):
        known, _ = self.bodies([listing(delevenlig=Delevenlig.YES)])
        unknown, _ = self.bodies([listing(delevenlig=Delevenlig.UNKNOWN)])
        self.assertIn("Delevenlig", known)
        self.assertNotIn("Delevenlig", unknown)

    def test_html_in_a_listing_title_is_escaped(self):
        _, html = self.bodies([listing(name='<img src=x onerror="alert(1)">')])
        self.assertNotIn("<img", html)
        self.assertIn("&lt;img", html)

    def test_every_listing_appears(self):
        listings = [listing(name=f"Vej {n}", url=f"https://kereby.dk/bolig/{n}") for n in range(5)]
        text, html = self.bodies(listings)
        for item in listings:
            self.assertIn(item.name, text)
            self.assertIn(item.url, html)


class TestSend(unittest.TestCase):
    def test_nothing_new_sends_nothing(self):
        self.assertFalse(notify.send([], config=SmtpConfig.from_env(CONFIGURED)))

    def test_no_configuration_sends_nothing(self):
        # A local run with no secrets must scrape happily and stay quiet.
        self.assertFalse(notify.send([listing()], config=None))

    def test_a_configured_run_hands_the_message_to_the_server(self):
        delivered = []
        original = notify._deliver
        notify._deliver = lambda message, config: delivered.append((message, config))
        try:
            sent = notify.send([listing()], config=SmtpConfig.from_env(CONFIGURED))
        finally:
            notify._deliver = original

        self.assertTrue(sent)
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0][0]["Subject"], "1 ny lejlighed i København")

    def test_a_failing_server_is_not_swallowed(self):
        original = notify._deliver

        def explode(message, config):
            raise OSError("connection refused")

        notify._deliver = explode
        try:
            with self.assertRaises(OSError):
                notify.send([listing()], config=SmtpConfig.from_env(CONFIGURED))
        finally:
            notify._deliver = original


class TestOrdering(unittest.TestCase):
    def test_cheapest_first(self):
        listings = [listing(price=30000), listing(price=12000), listing(price=None)]
        prices = [item.price for item in notify.sorted_for_email(listings)]
        self.assertEqual(prices, [12000, 30000, None])


class TestCommandLineWiring(unittest.TestCase):
    """The command line is what the workflow runs, so its wiring is the part
    that actually decides whether an email ever leaves the machine."""

    def setUp(self):
        # main() calls logging.basicConfig, which would otherwise leave a root
        # handler behind and make every later test print its log lines.
        root_logger = logging.getLogger()
        self.log_state = (list(root_logger.handlers), root_logger.level)
        logging.disable(logging.CRITICAL)

        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        # The page goes in its own directory, as in the real layout, because the
        # CSV is published alongside it under the same name.
        self.csv = root / "listings.csv"
        self.argv = ["--csv", str(self.csv), "--out", str(root / "docs" / "index.html")]
        self.found = [listing()]
        self.sent = []

        summary = RunSummary(started_at="2026-09-07T11:00:00")
        summary.results.append(SiteResult(site="kereby", name="Kereby", new=list(self.found)))

        self.original_run = cli.run
        self.original_send = notify.send
        cli.run = lambda *args, **kwargs: summary
        notify.send = lambda listings, **kwargs: self.sent.append(list(listings)) or True

    def tearDown(self):
        cli.run = self.original_run
        notify.send = self.original_send
        self.tmp.cleanup()

        logging.disable(logging.NOTSET)
        root_logger = logging.getLogger()
        root_logger.handlers, root_logger.level = self.log_state

    def test_a_normal_run_emails_what_it_found(self):
        self.assertEqual(cli.main(self.argv), 0)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0][0].url, self.found[0].url)

    def test_no_email_stops_the_send(self):
        self.assertEqual(cli.main(self.argv + ["--no-email"]), 0)
        self.assertEqual(self.sent, [])

    def test_a_dry_run_never_mails_anyone(self):
        # It writes no CSV, so anything it sent would be sent again tomorrow.
        self.assertEqual(cli.main(self.argv + ["--dry-run"]), 0)
        self.assertEqual(self.sent, [])

    def test_a_failed_send_fails_the_run(self):
        def explode(listings, **kwargs):
            raise OSError("connection refused")

        notify.send = explode
        # Non-zero keeps the workflow from committing the CSV, so the listings
        # stay new and go out with the next run.
        self.assertEqual(cli.main(self.argv), 1)

    def test_the_csv_is_still_written_when_the_send_fails(self):
        def explode(listings, **kwargs):
            raise OSError("connection refused")

        notify.send = explode
        cli.main(self.argv)
        self.assertTrue(self.csv.exists())


if __name__ == "__main__":
    unittest.main()
