"""Gmail connector — wraps the existing gmail_ingestor tool.

The standalone tool lives at:
  /Users/macpro2021/AI Ethical Engine/tools/gmail_ingestor/gmail_ingest.py

This connector imports and calls into that tool, then normalizes the
results into Charter events. The tool's authentication, OAuth handling,
and message parsing are reused as-is.

Each ingested email becomes a chain entry of type 'email_ingested'
with the sender, subject, snippet, and Gmail message ID. The sender
is added to the graph as a person entity if not already present.
"""

import os
import sys
from typing import Any, Dict, List, Optional

from charter.connectors import ConnectorBase, ConnectorResult


# Path to the existing Gmail ingestor tool
GMAIL_INGESTOR_PATH = (
    "/Users/macpro2021/AI Ethical Engine/tools/gmail_ingestor"
)


class GmailConnector(ConnectorBase):
    """Pull emails from Gmail and record as Charter events."""

    name = "gmail"
    description = (
        "Ingest emails from Gmail accounts. Wraps the gmail_ingestor "
        "tool. Each email becomes an 'email_ingested' chain entry. "
        "Senders become person entities in the graph."
    )
    version = "1.0"
    requires_auth = True
    config_schema = {
        "account": {
            "type": "string",
            "required": True,
            "description": (
                "Gmail account name (e.g. 'OsteoDensity', "
                "'GermPharm', 'MMLD', 'Personal', 'CharterAgent')"
            ),
        },
        "query": {
            "type": "string",
            "required": False,
            "description": (
                "Optional Gmail search query (e.g. "
                "'from:tata 1mg', 'subject:invoice')"
            ),
        },
    }

    def validate_config(self, config: Optional[Dict[str, Any]] = None) -> List[str]:
        errors = []
        if not config:
            errors.append("config required")
            return errors
        if not config.get("account"):
            errors.append(
                "config.account required (Gmail account name)"
            )
        return errors

    def run(self, config: Optional[Dict[str, Any]] = None,
            since: Optional[str] = None,
            limit: Optional[int] = None,
            dry_run: bool = False) -> ConnectorResult:
        result = ConnectorResult(self.name)

        # Validate config
        errors = self.validate_config(config)
        if errors:
            for e in errors:
                result.add_error(e)
            result.finish()
            return result

        account = config["account"]
        query = config.get("query", "")

        # Build the Gmail query with the optional 'since' filter
        if since:
            # Gmail uses YYYY/MM/DD format
            try:
                since_gmail = since.split("T")[0].replace("-", "/")
                date_filter = "after:{}".format(since_gmail)
                query = "{} {}".format(query, date_filter).strip()
            except Exception:
                result.add_error(
                    "could not parse 'since' filter: {}".format(since)
                )

        # Add the gmail_ingestor path to sys.path so we can import its modules
        if GMAIL_INGESTOR_PATH not in sys.path:
            sys.path.insert(0, GMAIL_INGESTOR_PATH)

        try:
            from gmail_ingest import (
                authenticate, list_thread_ids, fetch_thread,
            )
        except ImportError as e:
            result.add_error(
                "gmail_ingestor tool not importable: {}".format(e)
            )
            result.finish()
            return result

        # Authenticate
        try:
            creds = authenticate(account)
        except Exception as e:
            result.add_error(
                "Gmail authentication failed for account {}: {}".format(
                    account, e
                )
            )
            result.finish()
            return result

        # Build the Gmail API service
        try:
            from googleapiclient.discovery import build
            service = build("gmail", "v1", credentials=creds)
        except Exception as e:
            result.add_error(
                "could not build Gmail service: {}".format(e)
            )
            result.finish()
            return result

        # List threads matching the query
        max_threads = limit or 100
        try:
            thread_ids = list_thread_ids(
                service, query=query, max_threads=max_threads,
            )
        except Exception as e:
            result.add_error(
                "list_thread_ids failed: {}".format(e)
            )
            result.finish()
            return result

        result.metadata["account"] = account
        result.metadata["query"] = query
        result.metadata["thread_ids_found"] = len(thread_ids)

        # Process each thread
        for thread_id in thread_ids:
            try:
                thread_data = fetch_thread(service, thread_id)
                if not thread_data:
                    continue

                messages = thread_data.get("messages", [])
                for msg in messages:
                    headers = {
                        h["name"]: h["value"]
                        for h in msg.get("payload", {}).get("headers", [])
                    }
                    sender = headers.get("From", "")
                    subject = headers.get("Subject", "")
                    date = headers.get("Date", "")
                    snippet = msg.get("snippet", "")

                    if dry_run:
                        result.events_recorded += 1
                        continue

                    # Record the event in the chain
                    self._record_event(
                        "email_ingested",
                        {
                            "account": account,
                            "thread_id": thread_id,
                            "message_id": msg.get("id", ""),
                            "sender": sender[:200],
                            "subject": subject[:200],
                            "snippet": snippet[:200],
                            "date": date,
                        },
                    )
                    result.events_recorded += 1

                    # Add the sender to the graph as a person entity
                    sender_email = self._extract_email(sender)
                    sender_name = self._extract_name(sender) or sender_email
                    if sender_name and not dry_run:
                        added = self._add_entity(
                            entity_type="person",
                            name=sender_name,
                            email=sender_email,
                            context=account.lower(),
                        )
                        if added:
                            result.entities_added += 1

            except Exception as e:
                result.add_error(
                    "thread {}: {}".format(thread_id[:16], str(e)[:100])
                )

        result.finish()
        return result

    @staticmethod
    def _extract_email(from_header: str) -> str:
        """Extract the email address from a From header."""
        import re
        match = re.search(r"<([^>]+)>", from_header)
        if match:
            return match.group(1)
        # If no angle brackets, the whole header may be the email
        if "@" in from_header:
            return from_header.strip()
        return ""

    @staticmethod
    def _extract_name(from_header: str) -> str:
        """Extract the display name from a From header."""
        import re
        match = re.match(r'^"?([^"<]+)"?\s*<', from_header)
        if match:
            return match.group(1).strip()
        return ""
