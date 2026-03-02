"""SIEM Integration for Charter governance.

Exports Charter hash chain events in formats that security teams can ingest
into enterprise SIEM platforms:

    CEF (Common Event Format)  — Splunk, ArcSight, QRadar
    Structured JSON            — Datadog, Elastic, custom collectors
    RFC 5424 Syslog            — rsyslog, syslog-ng, any RFC 5424 receiver

The chain is stored as JSONL at ~/.charter/chain.jsonl.  Each entry is a
signed JSON object with: index, timestamp, event, data, previous_hash,
hash, signer, signature.

Usage:
    charter siem export --format cef
    charter siem export --format json --from 100 --to 200
    charter siem stream --format syslog
    charter siem status
"""

import json
import os
import platform
import socket
import time

from charter import __version__
from charter.identity import get_chain_path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_FORMATS = ("cef", "json", "syslog")

_HOSTNAME = socket.gethostname()

# CEF severity mapping (0-10 scale, 10 = most severe)
_CEF_SEVERITY = {
    "kill_trigger_fired": 10,
    "chain_integrity_failure": 9,
    "layer_0_violation_blocked": 9,
    "arbitration_divergence_detected": 7,
    "redteam_scenario_failed": 7,
    "identity_verified": 3,
}
_CEF_SEVERITY_DEFAULT = 5

# Datadog status mapping
_DATADOG_STATUS = {
    "kill_trigger_fired": "error",
    "chain_integrity_failure": "error",
    "layer_0_violation_blocked": "error",
    "arbitration_divergence_detected": "warn",
    "redteam_scenario_failed": "warn",
}
_DATADOG_STATUS_DEFAULT = "info"

# Syslog severity mapping (RFC 5424 severity codes)
#   0=emergency, 1=alert, 2=critical, 3=error, 4=warning,
#   5=notice, 6=informational, 7=debug
_SYSLOG_SEVERITY = {
    "kill_trigger_fired": 2,         # critical
    "chain_integrity_failure": 3,    # error
    "layer_0_violation_blocked": 3,  # error
    "arbitration_divergence_detected": 4,  # warning
    "redteam_scenario_failed": 4,    # warning
}
_SYSLOG_SEVERITY_DEFAULT = 6  # informational

# RFC 5424 facility: local0 = 16
_SYSLOG_FACILITY = 16


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_severity_cef(event):
    """Return CEF severity (0-10) for the given event type."""
    return _CEF_SEVERITY.get(event, _CEF_SEVERITY_DEFAULT)


def _get_status_datadog(event):
    """Return Datadog status string for the given event type."""
    return _DATADOG_STATUS.get(event, _DATADOG_STATUS_DEFAULT)


def _get_priority_syslog(event):
    """Return RFC 5424 priority value (facility * 8 + severity)."""
    severity = _SYSLOG_SEVERITY.get(event, _SYSLOG_SEVERITY_DEFAULT)
    return _SYSLOG_FACILITY * 8 + severity


def _escape_cef_value(value):
    """Escape special characters for CEF extension values.

    CEF requires that backslashes, equals signs, and newlines
    are escaped in extension values.
    """
    if not isinstance(value, str):
        value = str(value)
    value = value.replace("\\", "\\\\")
    value = value.replace("=", "\\=")
    value = value.replace("\n", "\\n")
    return value


def _load_chain_entries(chain_path=None):
    """Load all chain entries from the JSONL file.

    Returns a list of dicts. Returns an empty list if the file
    does not exist or is empty.
    """
    path = chain_path or get_chain_path()
    if not os.path.isfile(path):
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def _filter_entries(entries, from_index=None, to_index=None):
    """Filter entries by index range (inclusive on both ends)."""
    result = entries
    if from_index is not None:
        result = [e for e in result if e.get("index", 0) >= from_index]
    if to_index is not None:
        result = [e for e in result if e.get("index", 0) <= to_index]
    return result


# ---------------------------------------------------------------------------
# Format functions — pure, no side effects
# ---------------------------------------------------------------------------

def format_entry_cef(entry):
    """Format a chain entry as a CEF string for Splunk / ArcSight.

    Format:
        CEF:0|Charter|Governance|<version>|<event>|<event>|<severity>|<extensions>

    Extensions include: rt (timestamp), src (signer), msg (JSON data),
    cs1/cs1Label (chain hash), cn1/cn1Label (chain index).
    """
    event = entry.get("event", "unknown")
    severity = _get_severity_cef(event)
    timestamp = entry.get("timestamp", "")
    signer = entry.get("signer", "")
    data = entry.get("data", {})
    chain_hash = entry.get("hash", "")
    index = entry.get("index", 0)

    # Serialize data as compact JSON for the msg extension
    msg = json.dumps(data, separators=(",", ":"))

    extensions = (
        f"rt={_escape_cef_value(timestamp)} "
        f"src={_escape_cef_value(signer)} "
        f"msg={_escape_cef_value(msg)} "
        f"cs1={_escape_cef_value(chain_hash)} "
        f"cs1Label=ChainHash "
        f"cn1={index} "
        f"cn1Label=ChainIndex"
    )

    return f"CEF:0|Charter|Governance|{__version__}|{event}|{event}|{severity}|{extensions}"


def format_entry_datadog(entry):
    """Format a chain entry as structured JSON for Datadog.

    Returns a JSON string with ddsource, ddtags, hostname, service,
    status, message, and a charter sub-object with the full entry data.
    """
    event = entry.get("event", "unknown")
    status = _get_status_datadog(event)
    index = entry.get("index", 0)

    dd_obj = {
        "ddsource": "charter",
        "ddtags": "env:production,service:governance",
        "hostname": _HOSTNAME,
        "service": "charter-governance",
        "status": status,
        "message": f"Charter event: {event} (index {index})",
        "charter": {
            "index": index,
            "event": event,
            "hash": entry.get("hash", ""),
            "signer": entry.get("signer", ""),
            "data": entry.get("data", {}),
        },
    }

    return json.dumps(dd_obj, separators=(",", ":"))


def format_entry_syslog(entry):
    """Format a chain entry as an RFC 5424 syslog message.

    Format:
        <priority>1 timestamp hostname charter - msgid - [structured_data] message

    Priority = facility * 8 + severity (facility 16 = local0).
    """
    event = entry.get("event", "unknown")
    priority = _get_priority_syslog(event)
    timestamp = entry.get("timestamp", "")
    index = entry.get("index", 0)
    chain_hash = entry.get("hash", "")
    signer = entry.get("signer", "")
    data = entry.get("data", {})

    # RFC 5424 MSGID — use the event name
    msgid = event

    # Structured data element (SD-ID = charter@0)
    # SD parameters cannot contain ] " or \, so we escape them minimally
    data_str = json.dumps(data, separators=(",", ":"))
    data_str = data_str.replace("\\", "\\\\").replace('"', '\\"').replace("]", "\\]")
    structured_data = (
        f'[charter@0 index="{index}" hash="{chain_hash}" '
        f'signer="{signer}" data="{data_str}"]'
    )

    message = f"Charter governance event: {event}"

    return f"<{priority}>1 {timestamp} {_HOSTNAME} charter - {msgid} - {structured_data} {message}"


# ---------------------------------------------------------------------------
# Format dispatch
# ---------------------------------------------------------------------------

FORMAT_FUNCTIONS = {
    "cef": format_entry_cef,
    "json": format_entry_datadog,
    "syslog": format_entry_syslog,
}


# ---------------------------------------------------------------------------
# Export and streaming
# ---------------------------------------------------------------------------

def export_chain(format_name, chain_path=None, from_index=None, to_index=None):
    """Export chain entries in the specified format.

    Args:
        format_name: One of "cef", "json", "syslog".
        chain_path:  Path to chain.jsonl (default: ~/.charter/chain.jsonl).
        from_index:  Start index (inclusive). None means from beginning.
        to_index:    End index (inclusive). None means to end.

    Returns:
        A list of formatted strings, one per chain entry.

    Raises:
        ValueError: If format_name is not supported.
    """
    if format_name not in FORMAT_FUNCTIONS:
        raise ValueError(
            f"Unsupported format: {format_name}. "
            f"Supported: {', '.join(SUPPORTED_FORMATS)}"
        )

    fmt_fn = FORMAT_FUNCTIONS[format_name]
    entries = _load_chain_entries(chain_path)
    entries = _filter_entries(entries, from_index, to_index)

    return [fmt_fn(entry) for entry in entries]


def stream_chain(format_name, output_fn=None, chain_path=None, poll_interval=1.0):
    """Tail the chain file and yield new entries in the specified format.

    This is a blocking generator that polls the chain file for new lines.
    Use it in a daemon context or via ``charter siem stream``.

    Args:
        format_name:    One of "cef", "json", "syslog".
        output_fn:      Optional callback; if provided, each formatted entry
                        is passed to output_fn instead of being yielded.
        chain_path:     Path to chain.jsonl (default: ~/.charter/chain.jsonl).
        poll_interval:  Seconds between polls (default: 1.0).

    Yields:
        Formatted strings (one per new chain entry) if output_fn is None.
    """
    if format_name not in FORMAT_FUNCTIONS:
        raise ValueError(
            f"Unsupported format: {format_name}. "
            f"Supported: {', '.join(SUPPORTED_FORMATS)}"
        )

    fmt_fn = FORMAT_FUNCTIONS[format_name]
    path = chain_path or get_chain_path()

    # Start by reading current file size so we only emit new entries
    if os.path.isfile(path):
        with open(path) as f:
            f.seek(0, 2)  # seek to end
            file_pos = f.tell()
    else:
        file_pos = 0

    while True:
        if not os.path.isfile(path):
            time.sleep(poll_interval)
            continue

        current_size = os.path.getsize(path)
        if current_size > file_pos:
            with open(path) as f:
                f.seek(file_pos)
                new_data = f.read()
                file_pos = f.tell()

            for line in new_data.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                formatted = fmt_fn(entry)
                if output_fn is not None:
                    output_fn(formatted)
                else:
                    yield formatted

        time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_siem(args):
    """CLI entry point for ``charter siem``.

    Dispatches based on args.action:
        export  — export chain entries in the given format
        stream  — tail chain and print new entries in real time
        status  — show chain stats and available formats
    """
    action = getattr(args, "action", "status")

    if action == "export":
        fmt = getattr(args, "format", "cef") or "cef"
        from_idx = getattr(args, "from_index", None)
        to_idx = getattr(args, "to_index", None)

        try:
            lines = export_chain(fmt, from_index=from_idx, to_index=to_idx)
        except ValueError as exc:
            print(f"Error: {exc}")
            return

        for line in lines:
            print(line)

        if not lines:
            print(f"No chain entries found.")

    elif action == "stream":
        fmt = getattr(args, "format", "cef") or "cef"

        print(f"Streaming chain events as {fmt.upper()} (Ctrl+C to stop)...")
        try:
            for line in stream_chain(fmt):
                print(line, flush=True)
        except KeyboardInterrupt:
            print("\nStream stopped.")

    elif action == "status":
        chain_path = get_chain_path()
        entries = _load_chain_entries(chain_path)

        print("Charter SIEM Integration Status")
        print("=" * 40)
        print()
        print(f"  Chain path:        {chain_path}")
        print(f"  Chain exists:      {'yes' if os.path.isfile(chain_path) else 'no'}")
        print(f"  Total entries:     {len(entries)}")

        if entries:
            first_ts = entries[0].get("timestamp", "unknown")
            last_ts = entries[-1].get("timestamp", "unknown")
            print(f"  First timestamp:   {first_ts}")
            print(f"  Last timestamp:    {last_ts}")

            # Count events by type
            event_counts = {}
            for entry in entries:
                evt = entry.get("event", "unknown")
                event_counts[evt] = event_counts.get(evt, 0) + 1
            print()
            print("  Event types:")
            for evt, count in sorted(event_counts.items(), key=lambda x: -x[1]):
                print(f"    {evt}: {count}")

        print()
        print(f"  Supported formats: {', '.join(SUPPORTED_FORMATS)}")
        print(f"  Hostname:          {_HOSTNAME}")
        print(f"  Charter version:   {__version__}")

    else:
        print(f"Unknown action: {action}")
        print(f"Usage: charter siem [export|stream|status]")
