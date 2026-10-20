"""Read-only mail access over IMAP. The mailbox is opened read-only and messages are fetched with
BODY.PEEK, so nothing is ever marked read, moved or deleted. The Worker never touches the mailbox:
it only receives the short text this module extracts. Stdlib only."""
from __future__ import annotations

import imaplib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from typing import Callable

MAX_MESSAGES = 40
MAX_SIZE_BYTES = 1_500_000  # bigger messages (attachments) are listed by header only
SNIPPET_CHARS = 400
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
ENV_KEY = re.compile(r"^JARVIS_IMAP_([A-Z0-9]+)_USER$")


@dataclass(frozen=True)
class MailAccount:
    name: str  # "profissional", "cafe"
    user: str
    password: str = field(repr=False)  # an app password; never printed
    host: str = "imap.gmail.com"


@dataclass(frozen=True)
class Mail:
    sender: str
    subject: str
    date: str
    snippet: str
    when: datetime | None = None  # timezone-aware when the Date header could be read


def parse_accounts(values: dict[str, str]) -> tuple[MailAccount, ...]:
    """JARVIS_IMAP_<NAME>_USER / _PASSWORD (/ _HOST) pairs from the environment; incomplete pairs are skipped."""
    found = []
    for key in sorted(values):
        match = ENV_KEY.match(key)
        if not match:
            continue
        name = match.group(1)
        user = (values.get(key) or "").strip()
        password = re.sub(r"\s+", "", values.get(f"JARVIS_IMAP_{name}_PASSWORD") or "")
        host = (values.get(f"JARVIS_IMAP_{name}_HOST") or "imap.gmail.com").strip()
        if user and password:
            found.append(MailAccount(name.lower(), user, password, host))
    return tuple(found)


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return value.strip()


def _text_of(message: Message) -> str:
    """The first text/plain part, or the first text/html with tags removed; collapsed to one line."""
    plain = html = ""
    for part in message.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        kind = part.get_content_type()
        if kind not in ("text/plain", "text/html"):
            continue
        try:
            payload = part.get_payload(decode=True) or b""
            text = payload.decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if kind == "text/plain" and not plain:
            plain = text
        elif kind == "text/html" and not html:
            html = text
    text = plain or re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", html))
    return re.sub(r"\s+", " ", unescape(text)).strip()


def to_mail(raw: bytes, with_body: bool = True) -> Mail:
    message = message_from_bytes(raw)
    name, address = parseaddr(_decode(message.get("From")))
    try:
        when = parsedate_to_datetime(message.get("Date"))
        when = when if when.tzinfo else None
    except Exception:
        when = None
    return Mail(
        sender=(name or address)[:80],
        subject=_decode(message.get("Subject"))[:150] or "(sem assunto)",
        date=_decode(message.get("Date"))[:40],
        snippet=_text_of(message)[:SNIPPET_CHARS] if with_body else "",
        when=when,
    )


def _imap_date(day: date) -> str:
    return f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"


def fetch_recent(account: MailAccount, since: date, limit: int = MAX_MESSAGES, connect: Callable | None = None) -> list[Mail]:
    """Inbox messages received since `since`, newest last. Raises imaplib.IMAP4.error / OSError on failure."""
    connection = (connect or imaplib.IMAP4_SSL)(account.host)
    try:
        connection.login(account.user, account.password)
        status, _ = connection.select("INBOX", readonly=True)
        if status != "OK":
            raise imaplib.IMAP4.error("could not open the inbox read-only")
        status, data = connection.search(None, "SINCE", _imap_date(since))
        ids = (data[0].split() if status == "OK" and data and data[0] else [])[-limit:]
        mails = []
        for uid in ids:
            status, sized = connection.fetch(uid, "(RFC822.SIZE)")
            size = int(m.group(1)) if status == "OK" and (m := re.search(rb"RFC822\.SIZE (\d+)", b" ".join(x if isinstance(x, bytes) else x[0] for x in sized))) else 0
            if size > MAX_SIZE_BYTES:
                status, got = connection.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                body = False
            else:
                status, got = connection.fetch(uid, "(BODY.PEEK[])")
                body = True
            if status == "OK" and got and isinstance(got[0], tuple):
                mails.append(to_mail(got[0][1], body))
        return mails
    finally:
        try:
            connection.logout()
        except Exception:
            pass
