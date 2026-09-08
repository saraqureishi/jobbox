"""Read-only Gmail client.

Uses the Gmail API with the ``gmail.readonly`` scope only — JobBox can never
send, delete, or modify anything in your inbox.

The whole point of JobBox is that it reads ALL of Gmail, including the
"Updates" and "Promotions" tabs where the real jobbox.cc missed alerts. Gmail's
"tabs" are just categories; a plain search query (without a ``category:``
filter) spans every category automatically, so we simply do NOT constrain by
category.

This module exposes a small, plain-data :class:`EmailMessage` so the parsing
layer can be developed and tested with fixtures, without a live Gmail account.
"""

from __future__ import annotations

import base64
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Read-only. This is the narrowest scope that lets us read message content.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


@dataclass
class EmailMessage:
    """A normalised email, independent of the Gmail API wire format."""

    id: str
    thread_id: str
    sender: str            # e.g. "LinkedIn <jobalerts-noreply@linkedin.com>"
    sender_email: str      # e.g. "jobalerts-noreply@linkedin.com"
    subject: str
    date: dt.datetime      # timezone-aware (UTC)
    snippet: str = ""
    text_body: str = ""    # plain-text part, if any
    html_body: str = ""    # text/html part, if any
    labels: List[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        """Best available body: prefer HTML (richer), fall back to text."""
        return self.html_body or self.text_body


def _extract_email_address(from_header: str) -> str:
    """Pull the bare address out of a From header."""
    if "<" in from_header and ">" in from_header:
        return from_header.split("<", 1)[1].split(">", 1)[0].strip().lower()
    return from_header.strip().lower()


def _decode_b64url(data: str) -> str:
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _walk_parts(payload: dict, out: Dict[str, str]) -> None:
    """Recursively collect text/plain and text/html bodies from a payload."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    data = body.get("data")

    if mime == "text/plain" and data and "text" not in out:
        out["text"] = _decode_b64url(data)
    elif mime == "text/html" and data:
        # Concatenate multiple HTML parts (some alerts split content).
        out["html"] = out.get("html", "") + _decode_b64url(data)

    for part in payload.get("parts", []) or []:
        _walk_parts(part, out)


class GmailClient:
    """Thin wrapper over the Gmail API with OAuth handled per profile."""

    def __init__(self, credentials_file: Path, token_file: Path):
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self._service = None

    # -- Auth ---------------------------------------------------------------
    def _get_service(self):
        if self._service is not None:
            return self._service

        # Imported lazily so the rest of JobBox (parsers, storage, tests) works
        # without the Google libraries installed.
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.credentials_file.exists():
                    raise FileNotFoundError(
                        f"OAuth client file not found: {self.credentials_file}\n"
                        "Create an OAuth 'Desktop app' client in Google Cloud "
                        "Console, download it, and save it there. See the README."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_file), SCOPES
                )
                # Opens a browser once; subsequent syncs reuse the token.
                creds = flow.run_local_server(port=0)
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_file, "w", encoding="utf-8") as fh:
                fh.write(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    # -- Reading ------------------------------------------------------------
    def build_query(self, senders: Optional[List[str]], lookback_days: int) -> str:
        """Build a Gmail search query spanning ALL tabs/categories.

        We deliberately never add ``category:`` so Updates/Promotions/Social
        are all included. If senders are given we OR them; otherwise we scan
        everything within the lookback window.
        """
        parts: List[str] = []
        after = (dt.datetime.utcnow() - dt.timedelta(days=lookback_days)).strftime("%Y/%m/%d")
        parts.append(f"after:{after}")
        if senders:
            ors = " OR ".join(f"from:{s}" for s in senders)
            parts.append(f"({ors})")
        return " ".join(parts)

    def list_message_ids(self, query: str, max_results: int = 500) -> List[str]:
        service = self._get_service()
        ids: List[str] = []
        page_token = None
        while True:
            resp = (
                service.users()
                .messages()
                .list(userId="me", q=query, maxResults=100, pageToken=page_token)
                .execute()
            )
            ids.extend(m["id"] for m in resp.get("messages", []))
            page_token = resp.get("nextPageToken")
            if not page_token or len(ids) >= max_results:
                break
        return ids[:max_results]

    def get_message(self, message_id: str) -> EmailMessage:
        service = self._get_service()
        raw = (
            service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return self._parse_raw(raw)

    @staticmethod
    def _parse_raw(raw: dict) -> EmailMessage:
        payload = raw.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        from_header = headers.get("from", "")

        # Gmail internalDate is epoch ms (UTC).
        internal = raw.get("internalDate")
        if internal:
            date = dt.datetime.fromtimestamp(int(internal) / 1000, tz=dt.timezone.utc)
        else:
            date = dt.datetime.now(tz=dt.timezone.utc)

        bodies: Dict[str, str] = {}
        _walk_parts(payload, bodies)

        return EmailMessage(
            id=raw.get("id", ""),
            thread_id=raw.get("threadId", ""),
            sender=from_header,
            sender_email=_extract_email_address(from_header),
            subject=headers.get("subject", ""),
            date=date,
            snippet=raw.get("snippet", ""),
            text_body=bodies.get("text", ""),
            html_body=bodies.get("html", ""),
            labels=raw.get("labelIds", []),
        )

    def fetch_messages(
        self,
        senders: Optional[List[str]],
        lookback_days: int,
        max_results: int = 500,
    ) -> List[EmailMessage]:
        """Convenience: build query, list ids, fetch and parse each message."""
        query = self.build_query(senders, lookback_days)
        ids = self.list_message_ids(query, max_results=max_results)
        return [self.get_message(mid) for mid in ids]
