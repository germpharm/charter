"""CLI handler for `charter connectors` subcommand.

Handles list, info, and run actions for the connectors subsystem.
"""

import json
import os
from typing import Any, Dict, Optional

from charter.connectors import (
    get_connector, list_connectors, CONNECTORS,
)


def _build_config_from_args(args) -> Dict[str, Any]:
    """Build a config dict from CLI args.

    Supports two modes:
      - --config can be a JSON string OR a path to a JSON file
      - Shortcut args (--account, --query, --resource, --input-file)
        get merged into the config

    Shortcut args override --config values for the same key.
    """
    config: Dict[str, Any] = {}

    if getattr(args, "config", None):
        config_arg = args.config
        # If it looks like a file path, load it
        if os.path.isfile(config_arg):
            try:
                with open(config_arg) as f:
                    config = json.load(f)
            except json.JSONDecodeError as e:
                print("Error: --config file is not valid JSON: {}".format(e))
                return None
        else:
            # Treat as inline JSON
            try:
                config = json.loads(config_arg)
            except json.JSONDecodeError:
                print(
                    "Error: --config is neither a file path nor "
                    "valid JSON"
                )
                return None

    if not isinstance(config, dict):
        config = {}

    # Apply shortcut args
    if getattr(args, "account", None):
        config["account"] = args.account
    if getattr(args, "query", None):
        config["query"] = args.query
    if getattr(args, "resource", None):
        config["resource"] = args.resource
    if getattr(args, "input_file", None):
        config["input_file"] = args.input_file
    if getattr(args, "handle", None):
        config["handle"] = args.handle
    if getattr(args, "chat", None):
        config["chat"] = args.chat
    if getattr(args, "until", None):
        config["until"] = args.until
    if getattr(args, "verbose", False):
        config["verbose"] = True
    if getattr(args, "json_payload", None):
        try:
            payload = json.loads(args.json_payload)
        except json.JSONDecodeError as e:
            print("Error: --json-payload is not valid JSON: {}".format(e))
            return None
        if isinstance(payload, dict) and "events" in payload:
            config["events"] = payload["events"]
        elif isinstance(payload, list):
            config["events"] = payload
        else:
            print(
                "Error: --json-payload must be a JSON array of events "
                "or an object with an 'events' key"
            )
            return None

    return config


def run_connectors(args):
    """Dispatch handler for `charter connectors` subcommand."""
    action = args.action

    if action == "list":
        connectors = list_connectors()
        if not connectors:
            print("No connectors registered.")
            return

        print("Charter Connectors")
        print("=" * 50)
        for c in connectors:
            print()
            print("  {} (v{})".format(c["name"], c.get("version", "?")))
            if c.get("error"):
                print("    error: {}".format(c["error"]))
                continue
            print("    {}".format(c.get("description", "")))
            print("    requires_auth: {}".format(
                c.get("requires_auth", False)
            ))

    elif action == "info":
        name = getattr(args, "connector", None)
        if not name:
            print("Error: --connector required for info action")
            return

        try:
            connector = get_connector(name)
        except ValueError as e:
            print("Error: {}".format(e))
            return

        info = connector.info()
        print("Connector: {}".format(info["name"]))
        print("=" * 50)
        print("  Version:       {}".format(info["version"]))
        print("  Requires auth: {}".format(info["requires_auth"]))
        print()
        print("  Description:")
        print("    {}".format(info["description"]))
        print()
        print("  Config schema:")
        for field, spec in info.get("config_schema", {}).items():
            required = "required" if spec.get("required") else "optional"
            print("    {} ({}, {}):".format(
                field, spec.get("type", "any"), required
            ))
            print("      {}".format(spec.get("description", "")))

    elif action == "run":
        name = getattr(args, "connector", None)
        if not name:
            print("Error: --connector required for run action")
            print("       Available: {}".format(
                ", ".join(sorted(CONNECTORS.keys())) or "none"
            ))
            return

        try:
            connector = get_connector(name)
        except ValueError as e:
            print("Error: {}".format(e))
            return

        config = _build_config_from_args(args)
        if config is None:
            return

        since = getattr(args, "since", None)
        limit = getattr(args, "limit", None)
        dry_run = getattr(args, "dry_run", False)

        print("Running connector: {}".format(name))
        if config:
            # Don't print sensitive fields
            display_config = {
                k: v for k, v in config.items()
                if "token" not in k.lower() and "secret" not in k.lower()
            }
            print("  Config: {}".format(json.dumps(display_config)))
        if since:
            print("  Since:  {}".format(since))
        if limit:
            print("  Limit:  {}".format(limit))
        if dry_run:
            print("  Mode:   DRY RUN (no chain writes)")
        print()

        result = connector.run(
            config=config, since=since, limit=limit, dry_run=dry_run,
        )

        summary = result.to_dict()
        print("Connector run complete.")
        print("=" * 50)
        print("  Connector:        {}".format(summary["connector_name"]))
        print("  Events recorded:  {}".format(summary["events_recorded"]))
        print("  Entities added:   {}".format(summary["entities_added"]))
        if summary["relationships_added"]:
            print("  Relationships:    {}".format(
                summary["relationships_added"]
            ))
        print("  Started:          {}".format(summary["started_at"]))
        print("  Finished:         {}".format(summary["finished_at"]))
        if summary["metadata"]:
            print()
            print("  Metadata:")
            for k, v in summary["metadata"].items():
                print("    {}: {}".format(k, v))
        if summary["errors"]:
            print()
            print("  Errors ({}):".format(summary["error_count"]))
            for e in summary["errors"][:5]:
                print("    [!!] {}".format(e))
            if summary["error_count"] > 5:
                print("    ... and {} more".format(
                    summary["error_count"] - 5
                ))

    else:
        print("Usage: charter connectors <action>")
        print()
        print("  list   List all registered connectors")
        print("  info   Show details for a specific connector")
        print("  run    Run a connector to ingest data")
