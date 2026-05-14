"""JSON Ingestion connector — long-tail entry point for third-party ETL tools.

This is the connector that lets any third-party tool (Airbyte, Fivetran,
n8n, Zapier, Make.com, Pipedream, custom scripts) push data into Charter
without needing a platform-specific Charter connector.

The contract:

A caller provides a list of "events" in a normalized JSON format. Each
event has:
  - event_type (string, required) — the Charter event type to record
  - data (dict, required) — the event payload
  - actor (string, optional) — "human", "ai", or "collaborative" (default)
  - timestamp (string, optional) — ISO 8601 timestamp (defaults to now)
  - entities (list of dict, optional) — graph entities to add along with
    the event. Each entity has type, name, and optionally email, context,
    properties.

Usage from the CLI:
  charter connectors run --connector json_ingestion --input events.json

Usage programmatically:
  from charter.connectors import get_connector
  connector = get_connector("json_ingestion")
  result = connector.run(config={"events": [...]})

Usage as an HTTP/MCP endpoint:
  When charter mcp-serve is running, the JsonIngestion connector can be
  called via the charter_connector_run MCP tool with the events payload.

This is the bridging strategy from charter_catalog_observations.md
Observation 3: own high-value first-party connectors, and yield the long
tail to third-party ETL tools by giving them a clean place to land data.
"""

import json
import os
from typing import Any, Dict, List, Optional

from charter.connectors import ConnectorBase, ConnectorResult


class JsonIngestionConnector(ConnectorBase):
    """Accept normalized JSON events from any third-party ETL source."""

    name = "json_ingestion"
    description = (
        "Accept normalized JSON events from any third-party ETL "
        "tool. The standardized entry point for the long tail of "
        "platforms Charter does not have first-party connectors for."
    )
    version = "1.0"
    requires_auth = False  # The caller is already authenticated by their ETL tool
    config_schema = {
        "events": {
            "type": "list",
            "required": False,
            "description": (
                "List of normalized event dicts. Each must have "
                "event_type and data."
            ),
        },
        "input_file": {
            "type": "string",
            "required": False,
            "description": (
                "Path to a JSON file containing the events list. "
                "Used as an alternative to passing events inline."
            ),
        },
    }

    def validate_config(self, config: Optional[Dict[str, Any]] = None) -> List[str]:
        errors = []
        if not config:
            errors.append("config required")
            return errors
        if not config.get("events") and not config.get("input_file"):
            errors.append(
                "either config.events or config.input_file required"
            )
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

        # Load events from inline config or file
        events = config.get("events")
        if events is None and config.get("input_file"):
            input_path = config["input_file"]
            if not os.path.isfile(input_path):
                result.add_error(
                    "input_file not found: {}".format(input_path)
                )
                result.finish()
                return result
            try:
                with open(input_path) as f:
                    payload = json.load(f)
                # Support either {"events": [...]} or just [...]
                if isinstance(payload, dict):
                    events = payload.get("events", [])
                elif isinstance(payload, list):
                    events = payload
                else:
                    result.add_error(
                        "input_file must contain a JSON object with "
                        "'events' key or a JSON array of events"
                    )
                    result.finish()
                    return result
            except json.JSONDecodeError as e:
                result.add_error(
                    "input_file is not valid JSON: {}".format(e)
                )
                result.finish()
                return result

        if not isinstance(events, list):
            result.add_error("events must be a list")
            result.finish()
            return result

        result.metadata["events_received"] = len(events)
        if limit:
            events = events[:limit]
            result.metadata["events_after_limit"] = len(events)

        # Process each event
        for i, event in enumerate(events):
            if not isinstance(event, dict):
                result.add_error(
                    "event {}: not a dict".format(i)
                )
                continue

            event_type = event.get("event_type")
            data = event.get("data")
            actor = event.get("actor", "collaborative")
            timestamp = event.get("timestamp")  # Optional, defaults to now
            entities = event.get("entities", [])

            if not event_type:
                result.add_error(
                    "event {}: missing event_type".format(i)
                )
                continue
            if not isinstance(data, dict):
                result.add_error(
                    "event {}: data must be a dict".format(i)
                )
                continue

            # Apply 'since' filter if the event has a timestamp
            if since and timestamp and timestamp < since:
                continue

            if dry_run:
                result.events_recorded += 1
                continue

            # Optionally include the timestamp in the data payload
            if timestamp:
                data = dict(data)
                data["_source_timestamp"] = timestamp

            # Record the event in the chain
            self._record_event(event_type, data, actor=actor)
            result.events_recorded += 1

            # Process associated entities
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                entity_type = entity.get("type", "")
                entity_name = entity.get("name", "")
                if not entity_type or not entity_name:
                    continue
                added = self._add_entity(
                    entity_type=entity_type,
                    name=entity_name,
                    email=entity.get("email", ""),
                    context=entity.get("context", ""),
                    properties=entity.get("properties", {}),
                )
                if added:
                    result.entities_added += 1

        result.finish()
        return result


def validate_payload(payload: Any) -> List[str]:
    """Validate a JSON payload against the connector contract.

    Accepts either a dict with an "events" key or a bare list of events.
    Returns a list of error strings; empty list means valid.

    This is the shared validator used by the file path, the CLI
    --json-payload flag, the charter_connector_json_ingest MCP tool,
    and the HTTP /connectors/json_ingestion endpoint.
    """
    errors: List[str] = []
    if payload is None:
        errors.append("payload is required")
        return errors

    if isinstance(payload, dict):
        events = payload.get("events")
    elif isinstance(payload, list):
        events = payload
    else:
        errors.append(
            "payload must be a JSON object with 'events' key or a "
            "JSON array of events"
        )
        return errors

    if not isinstance(events, list):
        errors.append("'events' must be a list")
        return errors

    for i, event in enumerate(events):
        if not isinstance(event, dict):
            errors.append("event {}: not a dict".format(i))
            continue
        if not event.get("event_type"):
            errors.append("event {}: missing event_type".format(i))
        if not isinstance(event.get("data"), dict):
            errors.append("event {}: data must be a dict".format(i))

    return errors


def ingest_payload(payload: Any,
                   since: Optional[str] = None,
                   limit: Optional[int] = None,
                   dry_run: bool = False) -> Dict[str, Any]:
    """Validate and ingest a JSON payload, returning a ConnectorResult dict.

    Single entry point used by all non-file transports (CLI inline,
    MCP tool, HTTP endpoint). Pre-validates against the connector
    contract before invoking the connector so callers get a clean
    error envelope rather than partial chain writes.
    """
    errors = validate_payload(payload)
    if errors:
        return {
            "ok": False,
            "errors": errors,
            "events_recorded": 0,
            "entities_added": 0,
        }

    events = payload["events"] if isinstance(payload, dict) else payload
    connector = JsonIngestionConnector()
    result = connector.run(
        config={"events": events},
        since=since,
        limit=limit,
        dry_run=dry_run,
    )
    summary = result.to_dict()
    summary["ok"] = len(result.errors) == 0
    return summary
