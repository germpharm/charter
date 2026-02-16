"""Tests for charter.network — node creation, connections, contributions."""

import json
import os

import pytest

from charter.identity import create_identity
from charter.network import (
    create_node,
    load_node,
    add_expertise,
    add_data_source,
    add_connection,
    add_formation_contributor,
    record_contribution,
)


class TestCreateNode:
    def test_creates_node(self, charter_home_with_network):
        create_identity()
        node = create_node()
        assert node is not None
        assert node["connections"] == 0
        assert node["contributions"] == 0

    def test_creates_with_expertise(self, charter_home_with_network):
        create_identity()
        node = create_node(expertise=[{"domain": "pharmacy", "description": "clinical"}])
        assert len(node["expertise"]) == 1
        assert node["expertise"][0]["domain"] == "pharmacy"

    def test_node_persists(self, charter_home_with_network):
        create_identity()
        create_node()
        loaded = load_node()
        assert loaded is not None

    def test_requires_identity(self, charter_home_with_network):
        with pytest.raises(RuntimeError, match="No identity"):
            create_node()


class TestExpertise:
    def test_add_expertise(self, charter_home_with_network):
        create_identity()
        create_node()
        entry = add_expertise("telepharmacy", "remote pharmacy operations")
        assert entry["domain"] == "telepharmacy"

        node = load_node()
        assert len(node["expertise"]) == 1

    def test_multiple_expertise(self, charter_home_with_network):
        create_identity()
        create_node()
        add_expertise("pharmacy")
        add_expertise("governance")
        node = load_node()
        assert len(node["expertise"]) == 2


class TestDataSources:
    def test_add_data_source(self, charter_home_with_network):
        create_identity()
        create_node()
        entry = add_data_source("My Store", "shopify")
        assert entry["name"] == "My Store"
        assert entry["type"] == "shopify"
        assert entry["status"] == "registered"

    def test_multiple_sources(self, charter_home_with_network):
        create_identity()
        create_node()
        add_data_source("Store", "shopify")
        add_data_source("Books", "quickbooks")
        node = load_node()
        assert len(node["data_sources"]) == 2


class TestConnections:
    def test_add_connection(self, charter_home_with_network):
        create_identity()
        create_node()
        conn = add_connection("peer123", peer_alias="Alice", relationship="colleague")
        assert conn["peer_id"] == "peer123"

        node = load_node()
        assert node["connections"] == 1

    def test_connections_logged(self, charter_home_with_network):
        create_identity()
        create_node()
        add_connection("peer1")
        add_connection("peer2")

        net_dir = str(charter_home_with_network / "network")
        conn_path = os.path.join(net_dir, "connections.jsonl")
        with open(conn_path) as f:
            lines = [line for line in f if line.strip()]
        assert len(lines) == 2


class TestFormation:
    def test_add_formation_contributor(self, charter_home_with_network):
        create_identity()
        create_node()
        entry = add_formation_contributor("Mentor", "knowledge", "taught me everything")
        assert entry["name"] == "Mentor"
        assert entry["contribution_type"] == "knowledge"

        node = load_node()
        assert len(node["formation_contributors"]) == 1

    def test_contribution_types(self, charter_home_with_network):
        create_identity()
        create_node()
        types = ["capital", "belief", "challenge", "knowledge", "time", "love"]
        for t in types:
            add_formation_contributor(f"Person-{t}", t)
        node = load_node()
        assert len(node["formation_contributors"]) == 6


class TestContributions:
    def test_record_contribution(self, charter_home_with_network):
        create_identity()
        create_node()
        entry = record_contribution("Built governance", "governance")
        assert entry["title"] == "Built governance"
        assert entry["type"] == "governance"

        node = load_node()
        assert node["contributions"] == 1

    def test_contributions_logged(self, charter_home_with_network):
        create_identity()
        create_node()
        record_contribution("Item 1", "knowledge")
        record_contribution("Item 2", "data")

        net_dir = str(charter_home_with_network / "network")
        contrib_path = os.path.join(net_dir, "contributions.jsonl")
        with open(contrib_path) as f:
            lines = [line for line in f if line.strip()]
        assert len(lines) == 2
