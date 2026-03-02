"""Tests for charter.federation — federated governance (Italian coop model)."""

import json
import os

import pytest
import yaml

from charter.federation import (
    FederationNode,
    Federation,
    _base_url_from_sse,
    _default_config_path,
    _http_get_json,
    _timestamp_now,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_federation_config(path, nodes=None, name="Test Federation"):
    """Write a federation.yaml at the given path."""
    data = {
        "federation": {
            "name": name,
            "nodes": nodes or [],
        }
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _make_node_entry(node_id="aa" * 32, sse_url="http://localhost:8375/sse", alias="test-node"):
    """Return a single node entry dict for federation config."""
    return {
        "node_id": node_id,
        "sse_url": sse_url,
        "alias": alias,
    }


# ---------------------------------------------------------------------------
# _base_url_from_sse
# ---------------------------------------------------------------------------

class TestBaseUrlFromSse:
    def test_strips_sse_suffix(self):
        assert _base_url_from_sse("http://localhost:8375/sse") == "http://localhost:8375"

    def test_strips_sse_with_ip(self):
        assert _base_url_from_sse("http://100.95.120.54:8375/sse") == "http://100.95.120.54:8375"

    def test_no_sse_suffix_unchanged(self):
        assert _base_url_from_sse("http://localhost:8375") == "http://localhost:8375"

    def test_strips_trailing_slash(self):
        assert _base_url_from_sse("http://localhost:8375/") == "http://localhost:8375"


# ---------------------------------------------------------------------------
# _timestamp_now
# ---------------------------------------------------------------------------

class TestTimestampNow:
    def test_returns_iso_format(self):
        ts = _timestamp_now()
        assert ts.endswith("Z")
        assert "T" in ts

    def test_is_string(self):
        assert isinstance(_timestamp_now(), str)


# ---------------------------------------------------------------------------
# FederationNode
# ---------------------------------------------------------------------------

class TestFederationNode:
    def test_constructor_defaults(self):
        node = FederationNode("aa" * 32, "http://localhost:8375/sse")
        assert node.node_id == "aa" * 32
        assert node.sse_url == "http://localhost:8375/sse"
        assert node.alias.startswith("node-")
        assert node.reachable is False
        assert node.last_status is None
        assert node.last_checked is None

    def test_constructor_with_alias(self):
        node = FederationNode("bb" * 32, "http://localhost:8375/sse", alias="prod-1")
        assert node.alias == "prod-1"

    def test_base_url(self):
        node = FederationNode("aa" * 32, "http://localhost:8375/sse")
        assert node._base_url() == "http://localhost:8375"

    def test_to_dict_minimal(self):
        node = FederationNode("aa" * 32, "http://localhost:8375/sse")
        d = node.to_dict()
        assert d["node_id"] == "aa" * 32
        assert d["sse_url"] == "http://localhost:8375/sse"
        assert "alias" not in d  # default alias is auto-generated, not saved

    def test_to_dict_with_custom_alias(self):
        node = FederationNode("aa" * 32, "http://localhost:8375/sse", alias="prod-1")
        d = node.to_dict()
        assert d["alias"] == "prod-1"

    def test_repr_unreachable(self):
        node = FederationNode("aa" * 32, "http://localhost:8375/sse", alias="test")
        r = repr(node)
        assert "test" in r
        assert "unreachable" in r

    def test_repr_reachable(self):
        node = FederationNode("aa" * 32, "http://localhost:8375/sse", alias="test")
        node.reachable = True
        r = repr(node)
        assert "reachable" in r

    def test_check_health_unreachable(self):
        """Connecting to a non-existent host should return False."""
        node = FederationNode("aa" * 32, "http://127.0.0.1:19999/sse")
        result = node.check_health()
        assert result is False
        assert node.reachable is False
        assert node.last_checked is not None

    def test_get_status_unreachable(self):
        node = FederationNode("aa" * 32, "http://127.0.0.1:19999/sse")
        status = node.get_status()
        assert status is None

    def test_get_chain_summary_unreachable(self):
        node = FederationNode("aa" * 32, "http://127.0.0.1:19999/sse")
        summary = node.get_chain_summary()
        assert summary is None


# ---------------------------------------------------------------------------
# Federation — config loading and saving
# ---------------------------------------------------------------------------

class TestFederationConfig:
    def test_empty_config(self, tmp_path):
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)
        assert fed.nodes == []
        assert fed.name == "Charter Federation"

    def test_loads_nodes(self, tmp_path):
        config_path = str(tmp_path / "federation.yaml")
        nodes = [
            _make_node_entry("aa" * 32, "http://host1:8375/sse", "node-a"),
            _make_node_entry("bb" * 32, "http://host2:8375/sse", "node-b"),
        ]
        _make_federation_config(config_path, nodes=nodes, name="Test Fed")

        fed = Federation(config_path=config_path)
        assert len(fed.nodes) == 2
        assert fed.nodes[0].alias == "node-a"
        assert fed.nodes[1].alias == "node-b"
        assert fed.name == "Test Fed"

    def test_skips_malformed_entries(self, tmp_path):
        config_path = str(tmp_path / "federation.yaml")
        nodes = [
            _make_node_entry("aa" * 32, "http://host1:8375/sse", "valid"),
            {"node_id": "cc" * 32},  # missing sse_url
            {"sse_url": "http://host3:8375/sse"},  # missing node_id
        ]
        _make_federation_config(config_path, nodes=nodes)

        fed = Federation(config_path=config_path)
        assert len(fed.nodes) == 1
        assert fed.nodes[0].alias == "valid"

    def test_save_config_creates_file(self, tmp_path):
        config_path = str(tmp_path / "sub" / "federation.yaml")
        fed = Federation(config_path=config_path)
        fed.name = "Saved Fed"
        fed.nodes.append(FederationNode("dd" * 32, "http://host:8375/sse", "saved"))
        fed._save_config()

        assert os.path.isfile(config_path)
        with open(config_path) as f:
            data = yaml.safe_load(f)
        assert data["federation"]["name"] == "Saved Fed"
        assert len(data["federation"]["nodes"]) == 1
        assert data["federation"]["nodes"][0]["alias"] == "saved"

    def test_handles_corrupt_yaml(self, tmp_path):
        config_path = str(tmp_path / "federation.yaml")
        with open(config_path, "w") as f:
            f.write("{{{{invalid yaml")

        fed = Federation(config_path=config_path)
        assert fed.nodes == []

    def test_handles_empty_file(self, tmp_path):
        config_path = str(tmp_path / "federation.yaml")
        with open(config_path, "w") as f:
            f.write("")

        fed = Federation(config_path=config_path)
        assert fed.nodes == []


# ---------------------------------------------------------------------------
# Federation — add_node / remove_node
# ---------------------------------------------------------------------------

class TestFederationMutations:
    def test_add_node(self, tmp_path, charter_home):
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)

        node = fed.add_node("ee" * 32, "http://host:8375/sse", alias="new-node")
        assert node.node_id == "ee" * 32
        assert node.alias == "new-node"
        assert len(fed.nodes) == 1

        # Config persisted
        fed2 = Federation(config_path=config_path)
        assert len(fed2.nodes) == 1
        assert fed2.nodes[0].node_id == "ee" * 32

    def test_add_duplicate_raises(self, tmp_path, charter_home):
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)
        fed.add_node("ff" * 32, "http://host:8375/sse")

        with pytest.raises(ValueError, match="already in federation"):
            fed.add_node("ff" * 32, "http://host2:8375/sse")

    def test_remove_node(self, tmp_path, charter_home):
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)
        fed.add_node("gg" * 32, "http://host:8375/sse")

        removed = fed.remove_node("gg" * 32)
        assert removed is True
        assert len(fed.nodes) == 0

        # Config persisted
        fed2 = Federation(config_path=config_path)
        assert len(fed2.nodes) == 0

    def test_remove_nonexistent_returns_false(self, tmp_path, charter_home):
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)

        removed = fed.remove_node("hh" * 32)
        assert removed is False

    def test_get_node_found(self, tmp_path, charter_home):
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)
        fed.add_node("ii" * 32, "http://host:8375/sse", alias="target")

        node = fed.get_node("ii" * 32)
        assert node is not None
        assert node.alias == "target"

    def test_get_node_not_found(self, tmp_path):
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)
        assert fed.get_node("jj" * 32) is None


# ---------------------------------------------------------------------------
# Federation — get_all_status (offline)
# ---------------------------------------------------------------------------

class TestFederationStatus:
    def test_empty_federation(self, tmp_path, charter_home):
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)

        result = fed.get_all_status()
        assert result["total_nodes"] == 0
        assert result["nodes_reachable"] == 0
        assert result["nodes_unreachable"] == 0
        assert result["nodes"] == []
        assert "timestamp" in result
        assert "aggregate" in result

    def test_unreachable_node_status(self, tmp_path, charter_home):
        config_path = str(tmp_path / "federation.yaml")
        nodes = [_make_node_entry("kk" * 32, "http://127.0.0.1:19999/sse", "down-node")]
        _make_federation_config(config_path, nodes=nodes)

        fed = Federation(config_path=config_path)
        result = fed.get_all_status()

        assert result["total_nodes"] == 1
        assert result["nodes_reachable"] == 0
        assert result["nodes_unreachable"] == 1
        assert result["nodes"][0]["reachable"] is False
        assert result["aggregate"]["all_chains_intact"] is False

    def test_multiple_unreachable_nodes(self, tmp_path, charter_home):
        config_path = str(tmp_path / "federation.yaml")
        nodes = [
            _make_node_entry("ll" * 32, "http://127.0.0.1:19998/sse", "node-1"),
            _make_node_entry("mm" * 32, "http://127.0.0.1:19997/sse", "node-2"),
        ]
        _make_federation_config(config_path, nodes=nodes)

        fed = Federation(config_path=config_path)
        result = fed.get_all_status()

        assert result["total_nodes"] == 2
        assert result["nodes_unreachable"] == 2
        assert len(result["nodes"]) == 2

    def test_aggregate_fields_present(self, tmp_path, charter_home):
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)
        result = fed.get_all_status()

        agg = result["aggregate"]
        assert "total_chain_entries" in agg
        assert "all_chains_intact" in agg
        assert "domains" in agg
        assert "versions" in agg


# ---------------------------------------------------------------------------
# Federation — get_event_stream (offline)
# ---------------------------------------------------------------------------

class TestFederationEvents:
    def test_empty_federation_events(self, tmp_path):
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)
        events = fed.get_event_stream()
        assert events == []

    def test_unreachable_node_returns_empty(self, tmp_path):
        config_path = str(tmp_path / "federation.yaml")
        nodes = [_make_node_entry("nn" * 32, "http://127.0.0.1:19999/sse", "down")]
        _make_federation_config(config_path, nodes=nodes)

        fed = Federation(config_path=config_path)
        events = fed.get_event_stream()
        assert events == []


# ---------------------------------------------------------------------------
# Federation — mocked network scenarios
# ---------------------------------------------------------------------------

class TestFederationMocked:
    """Test federation with mocked HTTP responses."""

    def test_status_with_reachable_node(self, tmp_path, charter_home, monkeypatch):
        config_path = str(tmp_path / "federation.yaml")
        nodes = [_make_node_entry("oo" * 32, "http://fakehost:8375/sse", "mock-node")]
        _make_federation_config(config_path, nodes=nodes)

        health_response = {
            "status": "ok",
            "charter": {
                "version": "3.0.0",
                "domain": "healthcare",
                "chain_length": 42,
                "chain_intact": True,
            }
        }
        chain_response = {
            "total": 42,
            "entries": [
                {"index": 41, "event": "audit_generated", "timestamp": "2026-03-01T12:00:00Z"},
                {"index": 40, "event": "stamp_created", "timestamp": "2026-03-01T11:00:00Z"},
            ],
        }

        call_count = {"n": 0}

        def mock_http_get_json(url, timeout=10):
            call_count["n"] += 1
            if "/health" in url:
                return health_response
            if "/api/chain" in url:
                return chain_response
            return None

        monkeypatch.setattr("charter.federation._http_get_json", mock_http_get_json)

        fed = Federation(config_path=config_path)
        result = fed.get_all_status()

        assert result["total_nodes"] == 1
        assert result["nodes_reachable"] == 1
        assert result["nodes"][0]["reachable"] is True
        assert result["nodes"][0]["chain_length"] == 42
        assert result["nodes"][0]["chain_intact"] is True
        assert result["aggregate"]["total_chain_entries"] == 42
        assert result["aggregate"]["all_chains_intact"] is True
        assert "healthcare" in result["aggregate"]["domains"]

    def test_event_stream_merges_and_sorts(self, tmp_path, monkeypatch):
        config_path = str(tmp_path / "federation.yaml")
        nodes = [
            _make_node_entry("pp" * 32, "http://host1:8375/sse", "node-a"),
            _make_node_entry("qq" * 32, "http://host2:8375/sse", "node-b"),
        ]
        _make_federation_config(config_path, nodes=nodes)

        chain_a = {
            "total": 3,
            "entries": [
                {"index": 2, "event": "event_a2", "timestamp": "2026-03-01T14:00:00Z"},
                {"index": 1, "event": "event_a1", "timestamp": "2026-03-01T10:00:00Z"},
            ],
        }
        chain_b = {
            "total": 5,
            "entries": [
                {"index": 4, "event": "event_b4", "timestamp": "2026-03-01T12:00:00Z"},
                {"index": 3, "event": "event_b3", "timestamp": "2026-03-01T11:00:00Z"},
            ],
        }

        def mock_http_get_json(url, timeout=10):
            if "/health" in url:
                return {"status": "ok"}
            if "host1" in url and "/api/chain" in url:
                return chain_a
            if "host2" in url and "/api/chain" in url:
                return chain_b
            return None

        monkeypatch.setattr("charter.federation._http_get_json", mock_http_get_json)

        fed = Federation(config_path=config_path)
        events = fed.get_event_stream(limit=50)

        # Should be merged and sorted newest-first
        assert len(events) == 4
        assert events[0]["event"] == "event_a2"  # 14:00
        assert events[1]["event"] == "event_b4"  # 12:00
        assert events[2]["event"] == "event_b3"  # 11:00
        assert events[3]["event"] == "event_a1"  # 10:00

        # Each event should be tagged with node info
        assert events[0]["node_alias"] == "node-a"
        assert events[1]["node_alias"] == "node-b"

    def test_event_stream_limit(self, tmp_path, monkeypatch):
        config_path = str(tmp_path / "federation.yaml")
        nodes = [_make_node_entry("rr" * 32, "http://host:8375/sse", "n")]
        _make_federation_config(config_path, nodes=nodes)

        chain = {
            "total": 10,
            "entries": [
                {"index": i, "event": f"evt_{i}", "timestamp": f"2026-03-01T{10+i:02d}:00:00Z"}
                for i in range(5)
            ],
        }

        def mock_http_get_json(url, timeout=10):
            if "/health" in url:
                return {"status": "ok"}
            if "/api/chain" in url:
                return chain
            return None

        monkeypatch.setattr("charter.federation._http_get_json", mock_http_get_json)

        fed = Federation(config_path=config_path)
        events = fed.get_event_stream(limit=3)
        assert len(events) == 3

    def test_mixed_reachable_unreachable(self, tmp_path, charter_home, monkeypatch):
        config_path = str(tmp_path / "federation.yaml")
        nodes = [
            _make_node_entry("ss" * 32, "http://uphost:8375/sse", "up"),
            _make_node_entry("tt" * 32, "http://downhost:8375/sse", "down"),
        ]
        _make_federation_config(config_path, nodes=nodes)

        def mock_http_get_json(url, timeout=10):
            if "uphost" in url and "/health" in url:
                return {"status": "ok", "charter": {"version": "3.0.0", "chain_length": 10, "chain_intact": True}}
            if "uphost" in url and "/api/chain" in url:
                return {"total": 10, "entries": []}
            # downhost returns None
            return None

        monkeypatch.setattr("charter.federation._http_get_json", mock_http_get_json)

        fed = Federation(config_path=config_path)
        result = fed.get_all_status()

        assert result["nodes_reachable"] == 1
        assert result["nodes_unreachable"] == 1
        assert result["aggregate"]["all_chains_intact"] is False  # unreachable → integrity unknown

    def test_node_discovery(self, tmp_path, monkeypatch):
        """Test _discover_node_id via add command."""
        from charter.federation import _discover_node_id

        discovered_id = "dd" * 32

        def mock_http_get_json(url, timeout=10):
            if "/health" in url:
                return {"status": "ok", "charter": {"public_id": discovered_id}}
            return None

        monkeypatch.setattr("charter.federation._http_get_json", mock_http_get_json)

        result = _discover_node_id("http://host:8375/sse")
        assert result == discovered_id

    def test_node_discovery_nested_identity(self, tmp_path, monkeypatch):
        from charter.federation import _discover_node_id

        discovered_id = "ee" * 32

        def mock_http_get_json(url, timeout=10):
            if "/health" in url:
                return {"status": "ok", "identity": {"public_id": discovered_id}}
            return None

        monkeypatch.setattr("charter.federation._http_get_json", mock_http_get_json)

        result = _discover_node_id("http://host:8375/sse")
        assert result == discovered_id

    def test_node_discovery_fails_gracefully(self, monkeypatch):
        from charter.federation import _discover_node_id

        def mock_http_get_json(url, timeout=10):
            return None

        monkeypatch.setattr("charter.federation._http_get_json", mock_http_get_json)

        result = _discover_node_id("http://unreachable:8375/sse")
        assert result is None


# ---------------------------------------------------------------------------
# Federation — chain logging
# ---------------------------------------------------------------------------

class TestFederationChainLogging:
    def test_add_node_logs_to_chain(self, tmp_path, charter_home):
        from charter.identity import create_identity

        create_identity()
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)
        fed.add_node("uu" * 32, "http://host:8375/sse", alias="logged")

        chain_path = str(charter_home / "chain.jsonl")
        with open(chain_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        fed_events = [e for e in entries if e["event"] == "federation_node_added"]
        assert len(fed_events) == 1
        assert fed_events[0]["data"]["alias"] == "logged"

    def test_remove_node_logs_to_chain(self, tmp_path, charter_home):
        from charter.identity import create_identity

        create_identity()
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)
        fed.add_node("vv" * 32, "http://host:8375/sse")
        fed.remove_node("vv" * 32)

        chain_path = str(charter_home / "chain.jsonl")
        with open(chain_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        removed_events = [e for e in entries if e["event"] == "federation_node_removed"]
        assert len(removed_events) == 1

    def test_status_check_logs_to_chain(self, tmp_path, charter_home):
        from charter.identity import create_identity

        create_identity()
        config_path = str(tmp_path / "federation.yaml")
        fed = Federation(config_path=config_path)
        fed.get_all_status()

        chain_path = str(charter_home / "chain.jsonl")
        with open(chain_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        status_events = [e for e in entries if e["event"] == "federation_status_checked"]
        assert len(status_events) == 1


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

class TestRunFederation:
    def test_status_no_nodes(self, tmp_path, charter_home, capsys, monkeypatch):
        config_path = str(tmp_path / "federation.yaml")
        monkeypatch.setattr("charter.federation._default_config_path", lambda: config_path)

        from charter.federation import run_federation
        from types import SimpleNamespace

        args = SimpleNamespace(action="status")
        run_federation(args)

        output = capsys.readouterr().out
        assert "Charter Federation" in output
        assert "Total nodes: 0" in output

    def test_events_no_nodes(self, tmp_path, capsys, monkeypatch):
        config_path = str(tmp_path / "federation.yaml")
        monkeypatch.setattr("charter.federation._default_config_path", lambda: config_path)

        from charter.federation import run_federation
        from types import SimpleNamespace

        args = SimpleNamespace(action="events", limit=50)
        run_federation(args)

        output = capsys.readouterr().out
        assert "No nodes in federation" in output

    def test_add_without_url(self, tmp_path, capsys, monkeypatch):
        config_path = str(tmp_path / "federation.yaml")
        monkeypatch.setattr("charter.federation._default_config_path", lambda: config_path)

        from charter.federation import run_federation
        from types import SimpleNamespace

        args = SimpleNamespace(action="add", url=None, sse_url=None, alias=None, node_id=None)
        run_federation(args)

        output = capsys.readouterr().out
        assert "Error" in output or "--url" in output

    def test_remove_without_node_id(self, tmp_path, capsys, monkeypatch):
        config_path = str(tmp_path / "federation.yaml")
        monkeypatch.setattr("charter.federation._default_config_path", lambda: config_path)

        from charter.federation import run_federation
        from types import SimpleNamespace

        args = SimpleNamespace(action="remove", node_id=None)
        run_federation(args)

        output = capsys.readouterr().out
        assert "Error" in output or "--node-id" in output

    def test_default_action(self, tmp_path, capsys, monkeypatch):
        """No action or None should show usage."""
        config_path = str(tmp_path / "federation.yaml")
        monkeypatch.setattr("charter.federation._default_config_path", lambda: config_path)

        from charter.federation import run_federation
        from types import SimpleNamespace

        args = SimpleNamespace(action=None)
        run_federation(args)

        output = capsys.readouterr().out
        assert "Usage" in output or "status" in output


# ---------------------------------------------------------------------------
# _http_get_json
# ---------------------------------------------------------------------------

class TestHttpGetJson:
    def test_unreachable_returns_none(self):
        result = _http_get_json("http://127.0.0.1:19999/nonexistent", timeout=1)
        assert result is None

    def test_invalid_url_returns_none(self):
        result = _http_get_json("not-a-url", timeout=1)
        assert result is None


# ---------------------------------------------------------------------------
# _default_config_path
# ---------------------------------------------------------------------------

class TestDefaultConfigPath:
    def test_returns_path(self):
        path = _default_config_path()
        assert path.endswith("federation.yaml")
        assert ".charter" in path
