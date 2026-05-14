"""Charter Connectors — bridges between platform-specific data sources and the Charter substrate.

The connector layer is the missing piece between Charter's generic ingestion
capability (charter.analytics.indexer.ingest) and the platform-specific APIs
that hold real data. Each connector knows how to pull data from one source,
normalize it into Charter's event format, and push it into the hash chain,
analytics warehouse, and graph memory.

This subsystem follows a hybrid strategy:

  1. First-party connectors for high-value platforms (Gmail, Shopify, Google
     Calendar today; Instagram, TikTok, YouTube, Stripe, Patreon, Substack
     planned). These are productized from the existing standalone tools in
     /Users/macpro2021/AI Ethical Engine/tools/.

  2. A standardized JSON ingestion endpoint that any third-party ETL tool
     (Airbyte, Fivetran, n8n, Zapier, Make.com, Pipedream) can write to.
     Charter becomes a destination for the long tail of platforms we don't
     directly support.

  3. A published connector contract so any developer can build a connector
     against a stable interface.

The strategic principle (from charter_catalog_observations.md Observation 3):
take the high-value ground (the connectors that matter most for the reference
architectures), yield the long tail (where third-party tools already excel),
and ensure data lands in Charter regardless of how it got there.

Usage:
    from charter.connectors import get_connector

    # Pull and ingest from a Charter connector
    connector = get_connector("gmail")
    result = connector.run(
        config={"account": "OsteoDensity", "query": "from:tata"},
        since="2026-04-01",
    )

    # The result includes counts, errors, and chain entry hashes
    print(result["events_recorded"])
"""

import importlib
import inspect
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class ConnectorResult:
    """Result of a connector run.

    A connector run produces zero or more Charter events. Each event is
    recorded in the hash chain with actor=collaborative (the connector
    is acting on behalf of the user it's authenticated as).

    Attributes:
        connector_name: The name of the connector that produced this result.
        events_recorded: Count of events written to the chain.
        entities_added: Count of new graph entities created.
        relationships_added: Count of new graph relationships created.
        errors: List of error strings encountered during the run.
        started_at: ISO 8601 timestamp when the run started.
        finished_at: ISO 8601 timestamp when the run completed.
        chain_entry_hashes: Hashes of the events written to the chain.
        metadata: Connector-specific metadata about the run.
    """

    def __init__(self, connector_name: str):
        self.connector_name = connector_name
        self.events_recorded = 0
        self.entities_added = 0
        self.relationships_added = 0
        self.errors: List[str] = []
        self.started_at = self._now()
        self.finished_at: Optional[str] = None
        self.chain_entry_hashes: List[str] = []
        self.metadata: Dict[str, Any] = {}

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    def finish(self):
        """Mark the run as complete."""
        self.finished_at = self._now()

    def add_error(self, error: str):
        """Record an error encountered during the run."""
        self.errors.append(error)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable summary of the result."""
        return {
            "connector_name": self.connector_name,
            "events_recorded": self.events_recorded,
            "entities_added": self.entities_added,
            "relationships_added": self.relationships_added,
            "error_count": len(self.errors),
            "errors": self.errors[:10],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "chain_entry_hashes": (
                self.chain_entry_hashes[:5] +
                ([f"... and {len(self.chain_entry_hashes) - 5} more"]
                 if len(self.chain_entry_hashes) > 5 else [])
            ),
            "metadata": self.metadata,
        }


class ConnectorBase(ABC):
    """Base class for Charter connectors.

    A connector knows how to:
      1. Authenticate against a specific platform
      2. Pull data from that platform (with optional filters like 'since')
      3. Normalize the data into Charter event format
      4. Push the events into the chain, analytics warehouse, and graph memory

    Subclasses must implement run(). They may override the helper methods
    for authentication, data pulling, and normalization.

    The contract for run() is:
      - Input: a config dict (connector-specific) and optional kwargs
      - Output: a ConnectorResult instance
      - Side effects: zero or more chain entries written; zero or more
        graph entities/relationships added; zero or more analytics rows added
    """

    name: str = "unknown"
    description: str = ""
    version: str = "1.0"
    requires_auth: bool = True
    config_schema: Dict[str, Any] = {}

    @abstractmethod
    def run(self, config: Optional[Dict[str, Any]] = None,
            since: Optional[str] = None,
            limit: Optional[int] = None,
            dry_run: bool = False) -> ConnectorResult:
        """Run the connector.

        Args:
            config: Connector-specific configuration dict.
            since: Optional ISO 8601 timestamp to filter data after.
            limit: Optional max number of records to ingest.
            dry_run: If True, fetch data but don't write to the chain.

        Returns:
            ConnectorResult with counts, errors, and metadata.
        """

    def validate_config(self, config: Optional[Dict[str, Any]] = None) -> List[str]:
        """Validate the config against config_schema.

        Default implementation: no validation. Subclasses can override
        to enforce required fields, type checks, etc.

        Returns:
            List of validation error strings. Empty list = valid.
        """
        return []

    def info(self) -> Dict[str, Any]:
        """Return connector metadata for catalog and CLI display."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "requires_auth": self.requires_auth,
            "config_schema": self.config_schema,
        }

    def _record_event(self, event_type: str,
                       data: Dict[str, Any],
                       actor: str = "ai") -> Optional[str]:
        """Helper: record a single event in the Charter chain.

        Args:
            event_type: The Charter event type (e.g. "email_received").
            data: Event payload dict.
            actor: Actor attribution. Defaults to "ai" because a
                connector run is autonomous data ingestion — the human
                kicked it off but the events themselves are produced
                by software walking an external API. Subclasses may
                override (e.g. a connector that wraps a human-in-the
                -loop review tool can pass "collaborative").

        The active operator identity is attached automatically by
        append_to_chain() via actor_id, so the connector does not need
        to thread it through.

        Returns:
            The hash of the chain entry, or None on failure.
        """
        try:
            from charter.identity import append_to_chain
            append_to_chain(event_type, data, actor=actor)
            # append_to_chain doesn't return the hash directly;
            # we'd need to read the latest entry to get it. For now
            # return a placeholder so the result tracking works.
            return "logged"
        except Exception as e:
            return None

    def _add_entity(self, entity_type: str, name: str,
                     properties: Optional[Dict[str, Any]] = None,
                     context: str = "",
                     email: str = "") -> bool:
        """Helper: add a graph entity if it doesn't already exist.

        Args:
            entity_type: One of "person", "organization", "project", etc.
            name: Entity display name.
            properties: Optional properties dict.
            context: Optional context label (e.g. "personal", "work").
            email: Optional email for person entities.

        Returns:
            True if added, False on failure or duplicate.
        """
        try:
            import sys
            import os
            sys.path.insert(0, os.path.join(
                os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.dirname(
                        os.path.abspath(__file__)
                    ))
                )),
            ))
            from core.graph_memory.engine import GraphMemory, make_id
            gm = GraphMemory()
            entity_id = make_id(entity_type, name)
            existing = gm.get_entity(entity_id)
            if existing:
                gm.close()
                return False
            gm.add_entity(
                entity_type=entity_type,
                name=name,
                email=email,
                context=context,
                properties=properties or {},
            )
            gm.close()
            return True
        except Exception:
            return False


CONNECTORS: Dict[str, type] = {}


def register_connector(name: str, connector_class: type):
    """Register a connector class by name."""
    CONNECTORS[name] = connector_class


def get_connector(name: str) -> ConnectorBase:
    """Get an instantiated connector by name.

    Args:
        name: The connector name (e.g. "gmail", "shopify", "google_calendar").

    Returns:
        An instance of the requested connector.

    Raises:
        ValueError: If no connector with that name is registered.
    """
    if name not in CONNECTORS:
        available = ", ".join(sorted(CONNECTORS.keys())) or "none"
        raise ValueError(
            "Unknown connector: {}. Available: {}".format(
                name, available
            )
        )
    return CONNECTORS[name]()


def list_connectors() -> List[Dict[str, Any]]:
    """List all registered connectors with their metadata."""
    result = []
    for name in sorted(CONNECTORS.keys()):
        try:
            connector = CONNECTORS[name]()
            result.append(connector.info())
        except Exception as e:
            result.append({
                "name": name,
                "error": str(e),
            })
    return result


# ── Auto-registration of built-in connectors ──────────────────────


def _auto_register():
    """Discover and register built-in connectors.

    Connectors fail silently on import if their underlying tool
    dependencies are missing. This lets the connectors subsystem
    work even when not all platform tools are installed.
    """
    builtin_connectors = [
        ("gmail", "charter.connectors.gmail", "GmailConnector"),
        ("shopify", "charter.connectors.shopify", "ShopifyConnector"),
        ("google_calendar", "charter.connectors.google_calendar",
         "GoogleCalendarConnector"),
        ("json_ingestion", "charter.connectors.json_ingestion",
         "JsonIngestionConnector"),
        ("instagram", "charter.connectors.instagram",
         "InstagramConnector"),
        ("tiktok", "charter.connectors.tiktok",
         "TikTokConnector"),
        ("youtube", "charter.connectors.youtube",
         "YouTubeConnector"),
        ("stripe", "charter.connectors.stripe",
         "StripeConnector"),
        ("apple_messages", "charter.connectors.apple_messages",
         "AppleMessagesConnector"),
    ]
    for name, module_path, class_name in builtin_connectors:
        try:
            module = importlib.import_module(module_path)
            connector_class = getattr(module, class_name)
            register_connector(name, connector_class)
        except Exception:
            # Silent failure — connector is unavailable but not broken
            pass


_auto_register()
