"""Tests for charter.siem — SIEM integration (CEF, Datadog JSON, Syslog)."""

import json
import os

import pytest

from charter.identity import create_identity, append_to_chain
from charter.siem import (
    SUPPORTED_FORMATS,
    format_entry_cef,
    format_entry_datadog,
    format_entry_syslog,
    export_chain,
    _get_severity_cef,
    _get_status_datadog,
    _get_priority_syslog,
    _filter_entries,
    _load_chain_entries,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(event="identity_created", index=0, **overrides):
    """Build a minimal chain entry dict for testing."""
    entry = {
        "index": index,
        "timestamp": "2026-03-01T00:00:00Z",
        "event": event,
        "data": {"public_id": "abc123", "alias": "test-node"},
        "previous_hash": "0" * 64,
        "hash": "a" * 64,
        "signer": "abc123",
    }
    entry.update(overrides)
    return entry


# ---------------------------------------------------------------------------
# TestConstants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_supported_formats_count(self):
        assert len(SUPPORTED_FORMATS) == 3

    def test_supported_formats_members(self):
        assert "cef" in SUPPORTED_FORMATS
        assert "json" in SUPPORTED_FORMATS
        assert "syslog" in SUPPORTED_FORMATS

    def test_supported_formats_is_tuple(self):
        assert isinstance(SUPPORTED_FORMATS, tuple)


# ---------------------------------------------------------------------------
# TestSeverityMapping
# ---------------------------------------------------------------------------

class TestSeverityMapping:
    """CEF severity, Datadog status, and Syslog priority mappings."""

    # -- CEF severity (0-10 scale) --

    def test_cef_kill_trigger(self):
        assert _get_severity_cef("kill_trigger_fired") == 10

    def test_cef_chain_integrity_failure(self):
        assert _get_severity_cef("chain_integrity_failure") == 9

    def test_cef_identity_verified(self):
        assert _get_severity_cef("identity_verified") == 3

    def test_cef_default(self):
        assert _get_severity_cef("some_unknown_event") == 5

    # -- Datadog status --

    def test_datadog_kill_trigger(self):
        assert _get_status_datadog("kill_trigger_fired") == "error"

    def test_datadog_chain_integrity_failure(self):
        assert _get_status_datadog("chain_integrity_failure") == "error"

    def test_datadog_arbitration_divergence(self):
        assert _get_status_datadog("arbitration_divergence_detected") == "warn"

    def test_datadog_identity_verified(self):
        assert _get_status_datadog("identity_verified") == "info"

    def test_datadog_default(self):
        assert _get_status_datadog("some_unknown_event") == "info"

    # -- Syslog priority (facility 16 * 8 + severity) --

    def test_syslog_kill_trigger(self):
        # facility=16, severity=2 (critical) => 16*8+2 = 130
        assert _get_priority_syslog("kill_trigger_fired") == 130

    def test_syslog_chain_integrity_failure(self):
        # facility=16, severity=3 (error) => 131
        assert _get_priority_syslog("chain_integrity_failure") == 131

    def test_syslog_default(self):
        # facility=16, severity=6 (informational) => 134
        assert _get_priority_syslog("some_unknown_event") == 134


# ---------------------------------------------------------------------------
# TestFormatCEF
# ---------------------------------------------------------------------------

class TestFormatCEF:
    def test_produces_cef_string(self):
        entry = _make_entry()
        result = format_entry_cef(entry)
        assert result.startswith("CEF:0|Charter|Governance|")

    def test_contains_version(self):
        from charter import __version__
        entry = _make_entry()
        result = format_entry_cef(entry)
        assert f"|{__version__}|" in result

    def test_contains_event_name(self):
        entry = _make_entry(event="identity_created")
        result = format_entry_cef(entry)
        # event appears twice: as device event class ID and as name
        assert "|identity_created|identity_created|" in result

    def test_contains_severity(self):
        entry = _make_entry(event="kill_trigger_fired")
        result = format_entry_cef(entry)
        assert "|10|" in result

    def test_contains_rt_extension(self):
        entry = _make_entry(timestamp="2026-03-01T00:00:00Z")
        result = format_entry_cef(entry)
        assert "rt=2026-03-01T00:00:00Z" in result

    def test_contains_src_extension(self):
        entry = _make_entry(signer="abc123")
        result = format_entry_cef(entry)
        assert "src=abc123" in result

    def test_contains_cs1_chain_hash(self):
        entry = _make_entry()
        result = format_entry_cef(entry)
        assert f"cs1={'a' * 64}" in result
        assert "cs1Label=ChainHash" in result

    def test_contains_cn1_chain_index(self):
        entry = _make_entry(index=42)
        result = format_entry_cef(entry)
        assert "cn1=42" in result
        assert "cn1Label=ChainIndex" in result

    def test_msg_contains_data_json(self):
        entry = _make_entry()
        result = format_entry_cef(entry)
        assert "msg=" in result
        # Data is serialized as compact JSON (no spaces)
        assert "public_id" in result

    def test_default_severity_for_normal_event(self):
        entry = _make_entry(event="identity_created")
        result = format_entry_cef(entry)
        assert "|5|" in result


# ---------------------------------------------------------------------------
# TestFormatDatadog
# ---------------------------------------------------------------------------

class TestFormatDatadog:
    def test_produces_valid_json(self):
        entry = _make_entry()
        result = format_entry_datadog(entry)
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_has_ddsource(self):
        entry = _make_entry()
        parsed = json.loads(format_entry_datadog(entry))
        assert parsed["ddsource"] == "charter"

    def test_has_ddtags(self):
        entry = _make_entry()
        parsed = json.loads(format_entry_datadog(entry))
        assert "ddtags" in parsed
        assert "env:production" in parsed["ddtags"]

    def test_has_hostname(self):
        entry = _make_entry()
        parsed = json.loads(format_entry_datadog(entry))
        assert "hostname" in parsed
        assert len(parsed["hostname"]) > 0

    def test_has_service(self):
        entry = _make_entry()
        parsed = json.loads(format_entry_datadog(entry))
        assert parsed["service"] == "charter-governance"

    def test_status_info_for_normal_event(self):
        entry = _make_entry(event="identity_created")
        parsed = json.loads(format_entry_datadog(entry))
        assert parsed["status"] == "info"

    def test_status_error_for_kill_trigger(self):
        entry = _make_entry(event="kill_trigger_fired")
        parsed = json.loads(format_entry_datadog(entry))
        assert parsed["status"] == "error"

    def test_has_message(self):
        entry = _make_entry(event="identity_created", index=7)
        parsed = json.loads(format_entry_datadog(entry))
        assert "identity_created" in parsed["message"]
        assert "7" in parsed["message"]

    def test_has_charter_sub_object(self):
        entry = _make_entry(event="identity_created", index=0)
        parsed = json.loads(format_entry_datadog(entry))
        charter_obj = parsed["charter"]
        assert charter_obj["index"] == 0
        assert charter_obj["event"] == "identity_created"
        assert charter_obj["hash"] == "a" * 64
        assert charter_obj["signer"] == "abc123"
        assert isinstance(charter_obj["data"], dict)

    def test_charter_data_matches_entry(self):
        data = {"custom_key": "custom_value"}
        entry = _make_entry(data=data)
        parsed = json.loads(format_entry_datadog(entry))
        assert parsed["charter"]["data"] == data


# ---------------------------------------------------------------------------
# TestFormatSyslog
# ---------------------------------------------------------------------------

class TestFormatSyslog:
    def test_produces_rfc5424_ish_string(self):
        entry = _make_entry()
        result = format_entry_syslog(entry)
        # RFC 5424: <priority>1 timestamp hostname app ...
        assert result.startswith("<")
        assert ">1 " in result

    def test_contains_priority(self):
        entry = _make_entry(event="kill_trigger_fired")
        result = format_entry_syslog(entry)
        # priority = 16*8+2 = 130
        assert result.startswith("<130>")

    def test_default_priority(self):
        entry = _make_entry(event="identity_created")
        result = format_entry_syslog(entry)
        # priority = 16*8+6 = 134
        assert result.startswith("<134>")

    def test_contains_hostname(self):
        import socket
        hostname = socket.gethostname()
        entry = _make_entry()
        result = format_entry_syslog(entry)
        assert hostname in result

    def test_contains_charter_app_name(self):
        entry = _make_entry()
        result = format_entry_syslog(entry)
        assert " charter " in result

    def test_contains_structured_data(self):
        entry = _make_entry()
        result = format_entry_syslog(entry)
        assert "[charter@0 " in result
        assert 'index="0"' in result
        assert f'hash="{"a" * 64}"' in result
        assert 'signer="abc123"' in result

    def test_contains_event_message(self):
        entry = _make_entry(event="identity_created")
        result = format_entry_syslog(entry)
        assert "Charter governance event: identity_created" in result

    def test_contains_timestamp(self):
        entry = _make_entry(timestamp="2026-03-01T00:00:00Z")
        result = format_entry_syslog(entry)
        assert "2026-03-01T00:00:00Z" in result


# ---------------------------------------------------------------------------
# TestExportChain
# ---------------------------------------------------------------------------

class TestExportChain:
    def test_exports_all_entries(self, charter_home):
        create_identity(alias="test-node")
        append_to_chain("test_event_1", {"detail": "first"})
        append_to_chain("test_event_2", {"detail": "second"})

        lines = export_chain("cef")
        # genesis + 2 appended = 3
        assert len(lines) == 3

    def test_exports_json_format(self, charter_home):
        create_identity(alias="test-node")
        lines = export_chain("json")
        assert len(lines) == 1
        parsed = json.loads(lines[0])
        assert parsed["ddsource"] == "charter"

    def test_exports_syslog_format(self, charter_home):
        create_identity(alias="test-node")
        lines = export_chain("syslog")
        assert len(lines) == 1
        assert lines[0].startswith("<")

    def test_filter_from_index(self, charter_home):
        create_identity(alias="test-node")
        append_to_chain("evt_1", {})
        append_to_chain("evt_2", {})

        lines = export_chain("cef", from_index=1)
        assert len(lines) == 2  # index 1 and 2

    def test_filter_to_index(self, charter_home):
        create_identity(alias="test-node")
        append_to_chain("evt_1", {})
        append_to_chain("evt_2", {})

        lines = export_chain("cef", to_index=1)
        assert len(lines) == 2  # index 0 and 1

    def test_filter_from_and_to_index(self, charter_home):
        create_identity(alias="test-node")
        append_to_chain("evt_1", {})
        append_to_chain("evt_2", {})
        append_to_chain("evt_3", {})

        lines = export_chain("cef", from_index=1, to_index=2)
        assert len(lines) == 2  # index 1 and 2

    def test_raises_for_unsupported_format(self, charter_home):
        create_identity(alias="test-node")
        with pytest.raises(ValueError, match="Unsupported format"):
            export_chain("xml")

    def test_empty_chain_returns_empty(self, charter_home):
        # No identity created, chain file does not exist
        lines = export_chain("cef")
        assert lines == []

    def test_export_with_explicit_chain_path(self, charter_home, tmp_path):
        # Write a chain file at a custom path
        custom_path = str(tmp_path / "custom_chain.jsonl")
        entry = _make_entry()
        with open(custom_path, "w") as f:
            f.write(json.dumps(entry) + "\n")

        lines = export_chain("cef", chain_path=custom_path)
        assert len(lines) == 1
        assert "identity_created" in lines[0]


# ---------------------------------------------------------------------------
# TestFilterEntries
# ---------------------------------------------------------------------------

class TestFilterEntries:
    def test_no_filter(self):
        entries = [_make_entry(index=i) for i in range(5)]
        assert len(_filter_entries(entries)) == 5

    def test_from_index(self):
        entries = [_make_entry(index=i) for i in range(5)]
        result = _filter_entries(entries, from_index=3)
        assert len(result) == 2
        assert all(e["index"] >= 3 for e in result)

    def test_to_index(self):
        entries = [_make_entry(index=i) for i in range(5)]
        result = _filter_entries(entries, to_index=2)
        assert len(result) == 3
        assert all(e["index"] <= 2 for e in result)

    def test_from_and_to(self):
        entries = [_make_entry(index=i) for i in range(10)]
        result = _filter_entries(entries, from_index=3, to_index=6)
        assert len(result) == 4
        assert [e["index"] for e in result] == [3, 4, 5, 6]
