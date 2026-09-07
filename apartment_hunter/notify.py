"""Email the new listings at the end of a run.

Sending goes over plain SMTP from the standard library, so there is no service
to sign up for and nothing to pay: any mailbox that offers SMTP will do, and a
Gmail account with an app password is the path of least resistance. The server
is configured entirely through the environment (see :class:`SmtpConfig`), which
keeps the password out of the repository and lets a local run stay silent by
simply not setting it.

Only apartments that are new *in this run* are reported. The CSV is what makes
that meaningful: a listing is new exactly once, so nobody gets the same flat
twice.
"""

from __future__ import annotations

import html
import logging
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from typing import List, Mapping, Optional, Sequence, Tuple

from .config import NOTIFY_RECIPIENTS, SITE_URL
from .models import Delevenlig, Listing
from .report import SITE_NAMES

log = logging.getLogger(__name__)

DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587


@dataclass(frozen=True)
class SmtpConfig:
    """Where to send from. Built from environment variables, never from code."""

    host: str
    port: int
    username: str
    password: str
    sender: str
    recipients: Tuple[str, ...]

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> Optional["SmtpConfig"]:
        """Read the configuration, or return ``None`` if there is none.

        A missing username or password is the normal "not configured" case — a
        local run should scrape without trying to send anything — so it is not
        an error.
        """
        env = os.environ if env is None else env

        username = (env.get("SMTP_USER") or "").strip()
        password = env.get("SMTP_PASSWORD") or ""
        if not username or not password:
            return None

        recipients = _split_recipients(env.get("MAIL_TO")) or tuple(NOTIFY_RECIPIENTS)
        if not recipients:
            return None

        return cls(
            host=(env.get("SMTP_HOST") or DEFAULT_SMTP_HOST).strip(),
            port=_port(env.get("SMTP_PORT")),
            username=username,
            password=password,
            sender=(env.get("MAIL_FROM") or "").strip() or username,
            recipients=recipients,
        )


def _split_recipients(value: Optional[str]) -> Tuple[str, ...]:
    if not value:
        return ()
    parts = (part.strip() for part in value.replace(";", ",").split(","))
    return tuple(part for part in parts if part)


def _port(value: Optional[str]) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return DEFAULT_SMTP_PORT


# --------------------------------------------------------------------------- #
# Formatting
# --------------------------------------------------------------------------- #


def _kroner(price: Optional[int]) -> str:
    """18500 -> '18.500 kr.' — Danish digit grouping, which is the dot."""
    if price is None:
        return "pris ukendt"
    return f"{int(price):,}".replace(",", ".") + " kr."


def _rooms(rooms: Optional[float]) -> str:
    if rooms is None:
        return "vær. ukendt"
    # 5.0 rooms is written "5", 5.5 stays "5,5".
    text = f"{rooms:g}".replace(".", ",")
    return f"{text} vær."


def _area(area_m2: Optional[int]) -> str:
    return "m² ukendt" if area_m2 is None else f"{area_m2} m²"


def _facts(listing: Listing) -> str:
    return " · ".join([_rooms(listing.rooms), _area(listing.area_m2), _kroner(listing.price)])


def _where(listing: Listing) -> str:
    """Address line, without repeating whatever the title already says."""
    parts = [part for part in (listing.postal_code, listing.city) if part]
    place = " ".join(parts)
    if listing.address and listing.address != listing.name:
        return f"{listing.address}, {place}".rstrip(", ") if place else listing.address
    return place


def _site_name(listing: Listing) -> str:
    return SITE_NAMES.get(listing.site, listing.site)


def subject(listings: Sequence[Listing]) -> str:
    count = len(listings)
    noun = "ny lejlighed" if count == 1 else "nye lejligheder"
    return f"{count} {noun} i København"


def _text_body(listings: Sequence[Listing], generated: str) -> str:
    lines = [f"{subject(listings)} — {generated}", ""]
    for number, listing in enumerate(listings, start=1):
        lines.append(f"{number}. {listing.name}")
        where = _where(listing)
        if where:
            lines.append(f"   {where}")
        lines.append(f"   {_facts(listing)}")
        if listing.delevenlig is not Delevenlig.UNKNOWN:
            lines.append(f"   Delevenlig: {listing.delevenlig.value}")
        lines.append(f"   {_site_name(listing)}")
        lines.append(f"   {listing.url}")
        lines.append("")
    if SITE_URL:
        lines.append(f"Alle boliger: {SITE_URL}")
    return "\n".join(lines)


def _html_body(listings: Sequence[Listing], generated: str) -> str:
    """Inline styles only — mail clients discard <style> blocks."""
    cards = []
    for listing in listings:
        rows = [
            '<div style="font-size:11px;text-transform:uppercase;letter-spacing:.06em;'
            f'color:#6b7280">{html.escape(_site_name(listing))}</div>',
            '<div style="margin:2px 0 6px">'
            f'<a href="{html.escape(listing.url, quote=True)}" '
            'style="color:#111827;font-size:17px;font-weight:600;text-decoration:none">'
            f"{html.escape(listing.name)}</a></div>",
        ]
        where = _where(listing)
        if where:
            rows.append(f'<div style="color:#4b5563">{html.escape(where)}</div>')
        rows.append(
            f'<div style="margin-top:6px;color:#111827">{html.escape(_facts(listing))}</div>'
        )
        if listing.delevenlig is Delevenlig.YES:
            rows.append(
                '<div style="margin-top:6px;display:inline-block;padding:2px 8px;border-radius:9px;'
                'background:#dcfce7;color:#166534;font-size:12px">Delevenlig</div>'
            )
        elif listing.delevenlig is Delevenlig.NO:
            rows.append(
                '<div style="margin-top:6px;color:#6b7280;font-size:12px">Ikke delevenlig</div>'
            )
        cards.append(
            '<td style="padding:14px 16px;border:1px solid #e5e7eb;border-radius:10px;'
            'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;font-size:14px">'
            + "".join(rows)
            + "</td>"
        )

    footer = (
        f'<p style="margin-top:22px;font-size:13px;color:#6b7280">'
        f'<a href="{html.escape(SITE_URL, quote=True)}" style="color:#2563eb">Se alle boliger</a></p>'
        if SITE_URL
        else ""
    )
    body = "".join(f'<tr>{card}</tr><tr><td style="height:10px"></td></tr>' for card in cards)

    return (
        '<html><body style="margin:0;padding:20px;background:#f9fafb">'
        '<div style="max-width:620px;margin:0 auto">'
        '<p style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'font-size:15px;color:#111827">'
        f"{html.escape(subject(listings))} — {html.escape(generated)}</p>"
        f'<table cellpadding="0" cellspacing="0" style="width:100%">{body}</table>'
        f"{footer}</div></body></html>"
    )


def build_message(
    listings: Sequence[Listing],
    config: SmtpConfig,
    *,
    generated: Optional[str] = None,
) -> EmailMessage:
    """Render one multipart/alternative email for ``listings``."""
    generated = generated or datetime.now().strftime("%d-%m-%Y %H:%M")

    message = EmailMessage()
    message["Subject"] = subject(listings)
    message["From"] = config.sender
    message["To"] = ", ".join(config.recipients)
    message.set_content(_text_body(listings, generated))
    message.add_alternative(_html_body(listings, generated), subtype="html")
    return message


# --------------------------------------------------------------------------- #
# Sending
# --------------------------------------------------------------------------- #


def send(
    listings: Sequence[Listing],
    *,
    config: Optional[SmtpConfig] = None,
    generated: Optional[str] = None,
) -> bool:
    """Email ``listings``. Returns whether anything was actually sent.

    Nothing to report and no configuration are both ordinary outcomes and
    return ``False``. A server that rejects the message raises, because a
    notification that quietly fails is worse than a run that goes red.
    """
    listings = list(listings)
    if not listings:
        log.info("no new listings — no email")
        return False

    config = config or SmtpConfig.from_env()
    if config is None:
        log.info("SMTP is not configured (SMTP_USER/SMTP_PASSWORD) — no email")
        return False

    message = build_message(listings, config, generated=generated)
    _deliver(message, config)
    log.info("emailed %d new listing(s) to %s", len(listings), ", ".join(config.recipients))
    return True


def _deliver(message: EmailMessage, config: SmtpConfig) -> None:
    """Open a connection and hand the message over.

    Port 465 is implicit TLS; everything else is assumed to be the submission
    port, where the connection starts in the clear and is upgraded.
    """
    if config.port == 465:
        with smtplib.SMTP_SSL(config.host, config.port, timeout=30) as server:
            server.login(config.username, config.password)
            server.send_message(message)
        return

    with smtplib.SMTP(config.host, config.port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(config.username, config.password)
        server.send_message(message)


def sorted_for_email(listings: Sequence[Listing]) -> List[Listing]:
    """Cheapest first — that is the order these get read in."""
    return sorted(listings, key=lambda listing: (listing.price is None, listing.price or 0))
