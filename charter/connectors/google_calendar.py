"""Google Calendar connector — wraps the existing google_calendar tool.

The standalone tool lives at:
  /Users/macpro2021/AI Ethical Engine/tools/google_calendar/calendar_tool.py

This connector imports the auth and event-listing logic from the
existing tool and normalizes events into Charter chain entries.
Each calendar event becomes a 'calendar_event_recorded' chain entry.
Attendees become person entities in the graph.
"""

import os
import sys
from typing import Any, Dict, List, Optional

from charter.connectors import ConnectorBase, ConnectorResult


CALENDAR_TOOL_PATH = (
    "/Users/macpro2021/AI Ethical Engine/tools/google_calendar"
)
GMAIL_INGESTOR_PATH = (
    "/Users/macpro2021/AI Ethical Engine/tools/gmail_ingestor"
)


class GoogleCalendarConnector(ConnectorBase):
    """Pull calendar events from Google Calendar and record as Charter events."""

    name = "google_calendar"
    description = (
        "Ingest events from a Google Calendar account. Each event "
        "becomes a 'calendar_event_recorded' chain entry. Attendees "
        "become person entities in the graph."
    )
    version = "1.0"
    requires_auth = True
    config_schema = {
        "account": {
            "type": "string",
            "required": True,
            "description": (
                "Google account name (e.g. 'MMLD', 'GermPharm', "
                "'OsteoDensity', 'Personal')"
            ),
        },
        "calendar_id": {
            "type": "string",
            "required": False,
            "description": (
                "Calendar ID (defaults to 'primary')"
            ),
        },
    }

    def validate_config(self, config: Optional[Dict[str, Any]] = None) -> List[str]:
        errors = []
        if not config:
            errors.append("config required")
            return errors
        if not config.get("account"):
            errors.append("config.account required")
        return errors

    def run(self, config: Optional[Dict[str, Any]] = None,
            since: Optional[str] = None,
            limit: Optional[int] = None,
            dry_run: bool = False) -> ConnectorResult:
        result = ConnectorResult(self.name)

        errors = self.validate_config(config)
        if errors:
            for e in errors:
                result.add_error(e)
            result.finish()
            return result

        account = config["account"]
        calendar_id = config.get("calendar_id", "primary")

        # Add tool paths so we can import
        for path in (CALENDAR_TOOL_PATH, GMAIL_INGESTOR_PATH):
            if path not in sys.path:
                sys.path.insert(0, path)

        try:
            from calendar_tool import authenticate as cal_authenticate
        except ImportError as e:
            result.add_error(
                "google_calendar tool not importable: {}".format(e)
            )
            result.finish()
            return result

        try:
            creds = cal_authenticate(account)
        except Exception as e:
            result.add_error(
                "calendar auth failed for {}: {}".format(account, e)
            )
            result.finish()
            return result

        try:
            from googleapiclient.discovery import build
            service = build("calendar", "v3", credentials=creds)
        except Exception as e:
            result.add_error(
                "could not build calendar service: {}".format(e)
            )
            result.finish()
            return result

        # List events
        list_args = {
            "calendarId": calendar_id,
            "maxResults": min(limit or 100, 250),
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if since:
            list_args["timeMin"] = since

        try:
            events_result = service.events().list(**list_args).execute()
            events = events_result.get("items", [])
        except Exception as e:
            result.add_error(
                "calendar events list failed: {}".format(e)
            )
            result.finish()
            return result

        result.metadata["account"] = account
        result.metadata["calendar_id"] = calendar_id
        result.metadata["events_found"] = len(events)

        for event in events:
            try:
                summary = event.get("summary", "(no title)")
                start = event.get("start", {})
                start_time = (
                    start.get("dateTime") or start.get("date") or ""
                )
                end = event.get("end", {})
                end_time = end.get("dateTime") or end.get("date") or ""
                location = event.get("location", "")
                attendees = event.get("attendees", [])

                if dry_run:
                    result.events_recorded += 1
                    continue

                self._record_event(
                    "calendar_event_recorded",
                    {
                        "account": account,
                        "calendar_id": calendar_id,
                        "event_id": event.get("id", ""),
                        "summary": summary[:200],
                        "start": start_time,
                        "end": end_time,
                        "location": location[:200],
                        "attendee_count": len(attendees),
                    },
                )
                result.events_recorded += 1

                # Add attendees as person entities
                for attendee in attendees:
                    email = attendee.get("email", "")
                    name = (
                        attendee.get("displayName", "") or
                        email.split("@")[0] if email else ""
                    )
                    if name and email:
                        added = self._add_entity(
                            entity_type="person",
                            name=name,
                            email=email,
                            context=account.lower(),
                        )
                        if added:
                            result.entities_added += 1
            except Exception as e:
                result.add_error(
                    "event {}: {}".format(
                        event.get("id", "?")[:16], str(e)[:100]
                    )
                )

        result.finish()
        return result
