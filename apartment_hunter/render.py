"""Headless-browser page rendering.

Most of these sites paint their results with JavaScript, and several reject
plain HTTP clients outright, so every page goes through a real browser. This
module is the only place that knows about Playwright — scrapers receive plain
HTML strings, which keeps the extraction layer testable without a browser.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright

log = logging.getLogger(__name__)

#: Seconds to wait after a throttling notice, multiplied by the attempt number.
RATE_LIMIT_BACKOFF_S = 20

#: Some sites answer HTTP 200 with a throttling message in the body, so the
#: status code alone will not reveal that the results are missing.
_RATE_LIMIT_MARKERS = (
    "request limit exceeded",
    "rate limit exceeded",
    "too many requests",
)

#: Script and style bodies are excluded before looking for those markers:
#: front-end bundles ship localised error strings like "Too many requests",
#: and matching those would throttle us against a perfectly healthy page.
_SCRIPTS_AND_STYLES = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)


def _is_rate_limited(html: str) -> bool:
    visible = _SCRIPTS_AND_STYLES.sub(" ", html).lower()
    return any(marker in visible for marker in _RATE_LIMIT_MARKERS)


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

#: Consent dialogs block rendering and lazy loading on most Danish sites —
#: several of these sites render nothing but the banner until it is dismissed.
CONSENT_SELECTORS = [
    # Cookiebot
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#CybotCookiebotDialogBodyButtonAccept",
    "#CybotCookiebotDialogBhagAgreeButton",
    # Cookie Information
    "#declineButton",
    "button[data-cookie-consent='accept-all']",
    ".coi-banner__accept",
    "#coi-banner-wrapper button.coi-banner__accept",
    # OneTrust / Usercentrics / generic
    "#onetrust-accept-btn-handler",
    "[data-testid='uc-accept-all-button']",
    "button#accept-all",
    ".cookie-consent button.accept",
]

#: Text-matching fallback, run inside every frame. Some banners are rendered
#: into an iframe or with generated class names, so ids alone are not enough.
_CONSENT_CLICK_JS = r"""
() => {
  const wanted = /^(accepter( alle)?( cookies)?|acceptér( alle)?|tillad alle( cookies)?|godkend( alle)?|jeg accepterer|ok,? forst[åa]et|accept( all)?|allow all)$/i;
  const selector = "button, a[role='button'], input[type='button'], input[type='submit'], div[role='button'], span[role='button']";
  for (const node of document.querySelectorAll(selector)) {
    const label = (node.innerText || node.value || node.textContent || '').trim().replace(/\s+/g, ' ');
    if (!label || label.length > 40 || !wanted.test(label)) continue;
    const box = node.getBoundingClientRect();
    if (box.width === 0 || box.height === 0) continue;
    node.click();
    return label;
  }
  return null;
}
"""

# Hides the automation flag some bot filters look at.
_STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['da-DK', 'da', 'en-US']});
"""


@dataclass
class RenderOptions:
    """How to coax a given page into showing all of its listings."""

    wait_for: Optional[str] = None
    """CSS selector that must appear before the page counts as loaded."""

    wait_ms: int = 2500
    """Settle time after load, for client-side rendering and XHR results."""

    scroll: bool = True
    """Scroll to the bottom to trigger lazy-loaded cards."""

    scroll_steps: int = 12
    """How far to keep scrolling. Overview pages need more than detail pages."""

    networkidle_ms: int = 6000
    """Cap on waiting for the network to go quiet — ad and analytics traffic
    means many of these pages never actually reach networkidle."""

    load_more_selector: Optional[str] = None
    """Button to click repeatedly to append more results."""

    max_load_more: int = 12
    """Safety cap on 'load more' clicks."""

    timeout_ms: int = 45_000


class BrowserSession:
    """A single browser reused across all sites in a run."""

    def __init__(self, headless: bool = True, slow_mo: int = 0) -> None:
        self._headless = headless
        self._slow_mo = slow_mo
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self) -> "BrowserSession":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self._headless,
            slow_mo=self._slow_mo,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        self._context = self._browser.new_context(
            user_agent=USER_AGENT,
            locale="da-DK",
            timezone_id="Europe/Copenhagen",
            viewport={"width": 1440, "height": 1000},
            extra_http_headers={"Accept-Language": "da-DK,da;q=0.9,en;q=0.8"},
        )
        self._context.add_init_script(_STEALTH)
        return self

    def __exit__(self, *exc) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer:
                    closer.close()
            except PlaywrightError:  # pragma: no cover - teardown best effort
                pass
        if self._playwright:
            self._playwright.stop()

    # ------------------------------------------------------------------ #

    def render(self, url: str, options: Optional[RenderOptions] = None, retries: int = 2) -> str:
        """Load ``url`` and return the fully rendered HTML."""
        options = options or RenderOptions()
        last_error: Optional[Exception] = None
        html = ""

        for attempt in range(1, retries + 2):
            page = self._context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=options.timeout_ms)
                # Banners usually appear a beat after the document does, and a
                # few sites inject theirs only once the app has booted.
                page.wait_for_timeout(1200)
                self._dismiss_consent(page)
                self._await_content(page, options)
                self._dismiss_consent(page)
                if options.scroll:
                    self._scroll_to_bottom(page, options.scroll_steps)
                self._click_load_more(page, options)
                page.wait_for_timeout(400)
                html = page.content()

                if _is_rate_limited(html) and attempt <= retries:
                    # The site answers 200 with a throttling notice in the body,
                    # so only the text gives it away. Back off and try again.
                    delay = RATE_LIMIT_BACKOFF_S * attempt
                    log.warning("%s is rate limiting us — waiting %ds", url, delay)
                    time.sleep(delay)
                    continue
                return html
            except (PlaywrightTimeout, PlaywrightError) as exc:
                last_error = exc
                log.warning("render failed (attempt %s/%s) for %s: %s", attempt, retries + 1, url, exc)
                time.sleep(1.5 * attempt)
            finally:
                page.close()

        if html:
            log.warning("returning last response for %s despite throttling", url)
            return html
        raise RuntimeError(f"could not render {url}: {last_error}")

    # ------------------------------------------------------------------ #

    @staticmethod
    def _dismiss_consent(page: Page) -> None:
        """Accept the cookie banner, by id first and by button text second.

        Runs across every frame: some consent providers render their dialog in
        an iframe, and until it is gone the site will not load its results.
        """
        for selector in CONSENT_SELECTORS:
            try:
                element = page.locator(selector).first
                if element.count() and element.is_visible(timeout=500):
                    element.click(timeout=2500)
                    page.wait_for_timeout(900)
                    log.debug("consent accepted via %s", selector)
                    return
            except (PlaywrightTimeout, PlaywrightError):
                continue

        for frame in page.frames:
            try:
                label = frame.evaluate(_CONSENT_CLICK_JS)
            except (PlaywrightTimeout, PlaywrightError):
                continue
            if label:
                log.debug("consent accepted via button text %r", label)
                page.wait_for_timeout(900)
                return

    @staticmethod
    def _await_content(page: Page, options: RenderOptions) -> None:
        if options.wait_for:
            try:
                page.wait_for_selector(options.wait_for, timeout=options.timeout_ms, state="attached")
            except PlaywrightTimeout:
                log.warning("selector %r never appeared on %s", options.wait_for, page.url)
        try:
            page.wait_for_load_state("networkidle", timeout=options.networkidle_ms)
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(options.wait_ms)

    @staticmethod
    def _scroll_to_bottom(page: Page, steps: int = 12) -> None:
        """Scroll down in steps so lazy-loading and infinite scroll both fire.

        Stops only once the bottom is reached *and* the page has stopped
        growing. Watching the height alone is not enough: a long page that
        loads nothing new on the first nudge would end the scroll while most of
        its listings were still below the fold.
        """
        previous_height = -1
        for _ in range(max(1, steps)):
            page.mouse.wheel(0, 2200)
            page.wait_for_timeout(400)
            metrics = page.evaluate(
                "({height: document.body.scrollHeight,"
                " reach: window.scrollY + window.innerHeight})"
            )
            at_bottom = metrics["reach"] >= metrics["height"] - 60
            if at_bottom and metrics["height"] == previous_height:
                break
            previous_height = metrics["height"]
        page.evaluate("window.scrollTo(0, 0)")

    @staticmethod
    def _click_load_more(page: Page, options: RenderOptions) -> None:
        if not options.load_more_selector:
            return
        for _ in range(options.max_load_more):
            try:
                button = page.locator(options.load_more_selector).first
                if not button.is_visible(timeout=1500):
                    return
                button.scroll_into_view_if_needed(timeout=2000)
                button.click(timeout=3000)
                page.wait_for_timeout(1800)
            except (PlaywrightTimeout, PlaywrightError):
                return
