"""Tests for the web dashboard."""

import json
import os

import pytest
import yaml

from charter.identity import create_identity, append_to_chain
from charter.web.app import create_app


@pytest.fixture
def app(charter_home, tmp_path, sample_config, monkeypatch):
    """Create a Flask test app with mocked state."""
    # Write config file
    config_path = tmp_path / "charter.yaml"
    with open(config_path, "w") as f:
        yaml.dump(sample_config, f)
    monkeypatch.setattr("charter.web.app.load_config", lambda: sample_config)

    # Create identity
    create_identity(alias="test-node")

    app = create_app(daemon=None)
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    """Flask test client."""
    return app.test_client()


class TestDashboardPage:
    """Tests for the main dashboard."""

    def test_dashboard_loads(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"Governance Dashboard" in response.data

    def test_dashboard_shows_identity(self, client):
        response = client.get("/")
        assert b"test-node" in response.data

    def test_dashboard_shows_chain_status(self, client):
        response = client.get("/")
        assert b"Hash Chain" in response.data


class TestIdentityPage:
    """Tests for the identity page."""

    def test_identity_loads(self, client):
        response = client.get("/identity")
        assert response.status_code == 200
        assert b"Identity" in response.data

    def test_identity_shows_alias(self, client):
        response = client.get("/identity")
        assert b"test-node" in response.data

    def test_identity_shows_public_id(self, client):
        response = client.get("/identity")
        assert b"Public ID" in response.data


class TestAuditPage:
    """Tests for the audit trail page."""

    def test_audit_loads(self, client):
        response = client.get("/audit")
        assert response.status_code == 200
        assert b"Audit Trail" in response.data

    def test_audit_shows_events(self, client, charter_home):
        append_to_chain("test_event", {"key": "value"})
        response = client.get("/audit")
        assert b"test_event" in response.data


class TestGovernancePage:
    """Tests for the governance configuration page."""

    def test_governance_loads(self, client):
        response = client.get("/governance")
        assert response.status_code == 200
        assert b"Governance Configuration" in response.data

    def test_governance_shows_layer_a(self, client):
        response = client.get("/governance")
        assert b"Layer A" in response.data
        assert b"Never violate applicable law" in response.data

    def test_governance_shows_universal_floor(self, client):
        response = client.get("/governance")
        assert b"Universal Accountability Floor" in response.data

    def test_governance_shows_layer_b(self, client):
        response = client.get("/governance")
        assert b"Layer B" in response.data
        assert b"financial_transaction" in response.data


class TestNetworkPage:
    """Tests for the network page."""

    def test_network_loads(self, client):
        response = client.get("/network")
        assert response.status_code == 200
        assert b"Network" in response.data


class TestAPIEndpoints:
    """Tests for the JSON API."""

    def test_api_status(self, client):
        response = client.get("/api/status")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "identity" in data
        assert "chain" in data
        assert data["identity"]["alias"] == "test-node"

    def test_api_detect(self, client):
        response = client.get("/api/detect")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "total" in data
        assert "tools" in data

    def test_api_chain(self, client):
        response = client.get("/api/chain")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "total" in data
        assert "entries" in data

    def test_api_chain_pagination(self, client, charter_home):
        for i in range(5):
            append_to_chain(f"event_{i}", {"i": i})
        response = client.get("/api/chain?limit=2&offset=0")
        data = json.loads(response.data)
        assert len(data["entries"]) == 2
        assert data["total"] > 2
