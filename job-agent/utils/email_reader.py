"""
utils/email_reader.py – Gmail IMAP inbox polling for job-application responses.

The IMAP calls are synchronous (imaplib); they are offloaded to a thread-pool
executor so the function is safe to ``await`` from async code without blocking
the event loop.

Usage::

    from utils.email_reader import poll_inbox

    messages = await poll_inbox(
        gmail_address="you@gmail.com",
        app_password="xxxx xxxx xxxx xxxx",
        since_hours=4,
    )
    for msg in messages:
        print(msg["subject"], msg["from_addr"])
"""

from __future__ import annotations

import asyncio
import email
import email.header
import imaplib
import logging
import quopri
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

logger = logging.getLogger(__name__)

_IMAP_HOST = "imap.gmail.com"
_IMAP_PORT = 993


# ---------------------------------------------------------------------------
# Internal sync helpers (run in executor)
# ---------------------------------------------------------------------------

def _decode_header_value(raw: str | bytes | None) -> str:
    """Decode a potentially RFC-2047-encoded header value to a plain string."""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    parts = email.header.decode_header(raw)
    decoded_parts: list[str] = []
    for fragment, charset in parts:
        if isinstance(fragment, bytes):
            decoded_parts.append(
                fragment.decode(charset or "utf-8", errors="replace")
            )
        else:
            decoded_parts.append(fragment)
    return "".join(decoded_parts)


def _extract_body(msg: email.message.Message) -> str:
    """
    Walk a Message object and return the plain-text body.

    Falls back to HTML stripped of tags when no text/plain part exists.
    """
    plain: list[str] = []
    html: list[str] = []

    for part in msg.walk():
        ct = part.get_content_type()
        disp = str(part.get("Content-Disposition", ""))
        if "attachment" in disp:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            payload = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            continue
        if payload is None:
            continue
        text = payload.decode(charset, errors="replace")
        if ct == "text/plain":
            plain.append(text)
        elif ct == "text/html":
            html.append(text)

    if plain:
        return "\n\n".join(plain).strip()

    # Strip HTML tags as a fallback
    combined = "\n\n".join(html)
    return re.sub(r"<[^>]+>", " ", combined).strip()


def _fetch_messages_sync(
    gmail_address: str,
    app_password: str,
    since_dt: datetime,
) -> list[dict[str, Any]]:
    """
    Synchronous worker: connect to Gmail IMAP and fetch messages received
    since *since_dt*.

    Returns a list of dicts with keys:
        from_addr, subject, body, received_at
    """
    results: list[dict[str, Any]] = []

    # IMAP date criterion uses local-time date string "DD-Mon-YYYY"
    since_str = since_dt.strftime("%d-%b-%Y")

    try:
        conn = imaplib.IMAP4_SSL(_IMAP_HOST, _IMAP_PORT)
    except Exception as exc:  # noqa: BLE001
        logger.error("IMAP connection to %s:%s failed: %s", _IMAP_HOST, _IMAP_PORT, exc)
        return results

    try:
        conn.login(gmail_address, app_password)
        conn.select("INBOX", readonly=True)

        # IMAP SINCE is date-only (not time); we filter by exact time below
        status, data = conn.search(None, f'(SINCE "{since_str}")')
        if status != "OK" or not data or not data[0]:
            logger.debug("IMAP search returned no results (status=%s)", status)
            return results

        message_ids: list[bytes] = data[0].split()
        logger.info("IMAP: %d candidate message(s) since %s", len(message_ids), since_str)

        for msg_id in message_ids:
            fetch_status, fetch_data = conn.fetch(msg_id, "(RFC822)")
            if fetch_status != "OK" or not fetch_data:
                continue

            raw_email: bytes | None = None
            for part in fetch_data:
                if isinstance(part, tuple) and len(part) == 2:
                    raw_email = part[1]
                    break
            if raw_email is None:
                continue

            try:
                msg = email.message_from_bytes(raw_email)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to parse message id=%s: %s", msg_id, exc)
                continue

            # Parse Date header; skip messages older than since_dt
            date_header = msg.get("Date", "")
            try:
                received_at = parsedate_to_datetime(date_header)
                # Normalise to UTC
                received_at = received_at.astimezone(timezone.utc)
            except Exception:  # noqa: BLE001
                received_at = datetime.now(tz=timezone.utc)

            if received_at < since_dt:
                continue

            raw_from = msg.get("From", "")
            _, from_addr = parseaddr(raw_from)
            subject = _decode_header_value(msg.get("Subject", ""))
            body = _extract_body(msg)

            results.append(
                {
                    "from_addr": from_addr,
                    "subject": subject,
                    "body": body,
                    "received_at": received_at.isoformat(),
                    "_raw_email": raw_email.decode("utf-8", errors="replace"),
                }
            )

    except imaplib.IMAP4.error as exc:
        logger.error("IMAP error: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unexpected error during IMAP fetch: %s", exc)
    finally:
        try:
            conn.logout()
        except Exception:  # noqa: BLE001
            pass

    logger.info("IMAP: returned %d message(s) after time filtering", len(results))
    return results


# ---------------------------------------------------------------------------
# Public async interface
# ---------------------------------------------------------------------------

async def poll_inbox(
    gmail_address: str,
    app_password: str,
    since_hours: int = 2,
) -> list[dict[str, Any]]:
    """
    Poll the Gmail INBOX for messages received within the last *since_hours*.

    The underlying IMAP calls are executed in the default thread-pool executor
    to avoid blocking the asyncio event loop.

    Parameters
    ----------
    gmail_address:
        Full Gmail address (e.g. ``you@gmail.com``).
    app_password:
        Google App Password (not your account password).  Generate one at
        https://myaccount.google.com/apppasswords.
    since_hours:
        Look back this many hours from *now* (UTC).  Default is 2.

    Returns
    -------
    list[dict]
        Each dict contains:

        - ``from_addr`` (str) – sender e-mail address
        - ``subject`` (str) – decoded subject line
        - ``body`` (str) – plain-text body (HTML stripped if necessary)
        - ``received_at`` (str) – ISO-8601 datetime string (UTC)

        An additional ``_raw_email`` key holds the full RFC-2822 text and is
        intended for audit storage in the ``responses`` table.
    """
    since_dt = datetime.now(tz=timezone.utc) - timedelta(hours=since_hours)
    loop = asyncio.get_running_loop()
    messages: list[dict[str, Any]] = await loop.run_in_executor(
        None,
        _fetch_messages_sync,
        gmail_address,
        app_password,
        since_dt,
    )
    return messages
