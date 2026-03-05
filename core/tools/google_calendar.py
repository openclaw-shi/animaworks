from __future__ import annotations

# AnimaWorks - Digital Anima Framework
# Copyright (C) 2026 AnimaWorks Authors
# SPDX-License-Identifier: Apache-2.0
#
# This file is part of AnimaWorks core/server, licensed under Apache-2.0.
# See LICENSE for the full license text.

"""AnimaWorks Google Calendar tool -- direct Calendar API access.

Provides calendar event listing and event creation via Google Calendar API.
Uses the same OAuth2 credential pattern as the Gmail tool.
"""

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Execution Profile ─────────────────────────────────────

EXECUTION_PROFILE: dict[str, dict[str, object]] = {
    "list": {"expected_seconds": 10, "background_eligible": False},
    "add": {"expected_seconds": 10, "background_eligible": False},
}

TOOL_DESCRIPTION = "Google Calendar event listing and creation"

# Calendar API scopes
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

_DEFAULT_CREDENTIALS_DIR = Path.home() / ".animaworks" / "credentials" / "google_calendar"


# ── Client ────────────────────────────────────────────────


class GoogleCalendarClient:
    """Google Calendar API client with OAuth2 authentication."""

    def __init__(
        self,
        credentials_path: Path | None = None,
        token_path: Path | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        self.credentials_path = credentials_path or (_DEFAULT_CREDENTIALS_DIR / "credentials.json")
        self.token_path = token_path or (_DEFAULT_CREDENTIALS_DIR / "token.json")
        self.client_id = client_id or os.environ.get("GOOGLE_CALENDAR_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get("GOOGLE_CALENDAR_CLIENT_SECRET")
        self._service = None

    def _get_credentials(self) -> Any:
        """Obtain valid credentials via OAuth2."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            raise ImportError(
                "google_calendar tool requires google-api packages. "
                "Install with: pip install google-api-python-client "
                "google-auth-httplib2 google-auth-oauthlib"
            ) from None

        creds = None

        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.token_path.parent.mkdir(parents=True, exist_ok=True)
                self.token_path.write_text(creds.to_json())
            else:
                if self.credentials_path.exists():
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.credentials_path),
                        SCOPES,
                    )
                elif self.client_id and self.client_secret:
                    client_config = {
                        "installed": {
                            "client_id": self.client_id,
                            "client_secret": self.client_secret,
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                            "redirect_uris": ["http://localhost"],
                        }
                    }
                    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
                else:
                    raise FileNotFoundError(
                        f"No credentials found. Place credentials.json at "
                        f"{self.credentials_path} or set GOOGLE_CALENDAR_CLIENT_ID "
                        f"and GOOGLE_CALENDAR_CLIENT_SECRET environment variables."
                    )
                creds = flow.run_local_server(port=0)
                self.token_path.parent.mkdir(parents=True, exist_ok=True)
                self.token_path.write_text(creds.to_json())

        return creds

    def _build_service(self) -> Any:
        """Build the Calendar API service."""
        if self._service is None:
            from googleapiclient.discovery import build as build_api

            creds = self._get_credentials()
            self._service = build_api("calendar", "v3", credentials=creds)
        return self._service

    def list_events(
        self,
        *,
        max_results: int = 20,
        days: int = 7,
        calendar_id: str = "primary",
    ) -> list[dict[str, Any]]:
        """List upcoming events within the specified day range."""
        service = self._build_service()
        now = datetime.now(UTC)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days)).isoformat()

        result = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        events: list[dict[str, Any]] = []
        for item in result.get("items", []):
            start = item.get("start", {})
            end = item.get("end", {})
            events.append(
                {
                    "id": item.get("id", ""),
                    "summary": item.get("summary", "(no title)"),
                    "start": start.get("dateTime") or start.get("date", ""),
                    "end": end.get("dateTime") or end.get("date", ""),
                    "location": item.get("location", ""),
                    "description": (item.get("description") or "")[:200],
                    "status": item.get("status", ""),
                }
            )
        return events

    def add_event(
        self,
        *,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        location: str = "",
        calendar_id: str = "primary",
        attendees: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new calendar event.

        Args:
            summary: Event title.
            start: Start time in ISO8601 format or date (YYYY-MM-DD).
            end: End time in ISO8601 format or date (YYYY-MM-DD).
            description: Event description.
            location: Event location.
            calendar_id: Calendar ID (default: primary).
            attendees: List of attendee email addresses.
        """
        service = self._build_service()

        is_all_day = len(start) <= 10
        start_body = {"date": start} if is_all_day else {"dateTime": start}
        end_body = {"date": end} if is_all_day else {"dateTime": end}

        event_body: dict[str, Any] = {
            "summary": summary,
            "start": start_body,
            "end": end_body,
        }
        if description:
            event_body["description"] = description
        if location:
            event_body["location"] = location
        if attendees:
            event_body["attendees"] = [{"email": e} for e in attendees]

        created = service.events().insert(calendarId=calendar_id, body=event_body).execute()

        return {
            "id": created.get("id", ""),
            "summary": created.get("summary", ""),
            "htmlLink": created.get("htmlLink", ""),
            "start": created.get("start", {}),
            "end": created.get("end", {}),
            "status": created.get("status", ""),
        }


# ── Tool schemas (empty — use skill-based documentation) ──


def get_tool_schemas() -> list[dict]:
    """Return tool schemas (empty — accessed via use_tool)."""
    return []


# ── Dispatch ──────────────────────────────────────────────


def dispatch(name: str, args: dict[str, Any]) -> Any:
    """Dispatch a tool call by schema name."""
    _args = {k: v for k, v in args.items() if k != "anima_dir"}
    client = GoogleCalendarClient()

    if name == "google_calendar_list":
        return client.list_events(
            max_results=_args.get("max_results", 20),
            days=_args.get("days", 7),
            calendar_id=_args.get("calendar_id", "primary"),
        )

    if name == "google_calendar_add":
        summary = _args.get("summary", "")
        start = _args.get("start", "")
        end = _args.get("end", "")
        if not summary or not start or not end:
            return {"error": "summary, start, and end are required"}
        raw_attendees = _args.get("attendees")
        if isinstance(raw_attendees, str):
            raw_attendees = [raw_attendees]
        elif not isinstance(raw_attendees, list):
            raw_attendees = None
        return client.add_event(
            summary=summary,
            start=start,
            end=end,
            description=_args.get("description", ""),
            location=_args.get("location", ""),
            calendar_id=_args.get("calendar_id", "primary"),
            attendees=raw_attendees,
        )

    return {"error": f"Unknown action: {name}"}


# ── CLI ───────────────────────────────────────────────────


def cli_main(argv: list[str] | None = None) -> None:
    """CLI entry point for the Google Calendar tool."""
    parser = argparse.ArgumentParser(
        prog="animaworks-tool google_calendar",
        description="Google Calendar operations",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # list
    p_list = subparsers.add_parser("list", help="List upcoming events")
    p_list.add_argument("-n", "--max-results", type=int, default=20, help="Max events")
    p_list.add_argument("-d", "--days", type=int, default=7, help="Days ahead")
    p_list.add_argument("--calendar-id", default="primary", help="Calendar ID")
    p_list.add_argument("-j", "--json", action="store_true", help="JSON output")

    # add
    p_add = subparsers.add_parser("add", help="Create a new event")
    p_add.add_argument("summary", help="Event title")
    p_add.add_argument("--start", required=True, help="Start time (ISO8601 or YYYY-MM-DD)")
    p_add.add_argument("--end", required=True, help="End time (ISO8601 or YYYY-MM-DD)")
    p_add.add_argument("--description", default="", help="Description")
    p_add.add_argument("--location", default="", help="Location")
    p_add.add_argument("--calendar-id", default="primary", help="Calendar ID")
    p_add.add_argument("--attendees", nargs="*", help="Attendee email addresses")
    p_add.add_argument("-j", "--json", action="store_true", help="JSON output")

    args = parser.parse_args(argv)
    client = GoogleCalendarClient()

    try:
        if args.command == "list":
            events = client.list_events(
                max_results=args.max_results,
                days=args.days,
                calendar_id=args.calendar_id,
            )
            if getattr(args, "json", False):
                print(json.dumps(events, ensure_ascii=False, indent=2))
            else:
                if not events:
                    print("No upcoming events found.")
                else:
                    for ev in events:
                        start = ev.get("start", "")
                        summary = ev.get("summary", "(no title)")
                        location = ev.get("location", "")
                        loc_str = f"  @ {location}" if location else ""
                        print(f"  {start}  {summary}{loc_str}")

        elif args.command == "add":
            result = client.add_event(
                summary=args.summary,
                start=args.start,
                end=args.end,
                description=args.description,
                location=args.location,
                calendar_id=args.calendar_id,
                attendees=args.attendees,
            )
            if getattr(args, "json", False):
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(f"Created: {result.get('summary', '')} ({result.get('htmlLink', '')})")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
