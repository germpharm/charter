"""Shared test fixtures for Charter tests."""

import json
import os
import pytest
import yaml


@pytest.fixture
def charter_home(tmp_path, monkeypatch):
    """Redirect all Charter identity/context/network dirs to a temp directory."""
    charter_dir = tmp_path / ".charter"
    charter_dir.mkdir()

    monkeypatch.setattr("charter.identity.get_identity_dir", lambda: str(charter_dir))
    monkeypatch.setattr("charter.identity.get_identity_path",
                        lambda: str(charter_dir / "identity.json"))
    monkeypatch.setattr("charter.identity.get_chain_path",
                        lambda: str(charter_dir / "chain.jsonl"))

    return charter_dir


@pytest.fixture
def charter_home_with_context(charter_home, monkeypatch):
    """Charter home with context directories patched too."""
    contexts_dir = charter_home / "contexts"
    contexts_dir.mkdir()

    monkeypatch.setattr("charter.context.get_contexts_dir", lambda: str(contexts_dir))

    return charter_home


@pytest.fixture
def charter_home_with_network(charter_home, monkeypatch):
    """Charter home with network directories patched too."""
    network_dir = charter_home / "network"
    network_dir.mkdir()

    monkeypatch.setattr("charter.network.get_network_dir", lambda: str(network_dir))
    monkeypatch.setattr("charter.network.get_node_manifest_path",
                        lambda: str(network_dir / "node.json"))
    monkeypatch.setattr("charter.network.get_connections_path",
                        lambda: str(network_dir / "connections.jsonl"))
    monkeypatch.setattr("charter.network.get_contributions_path",
                        lambda: str(network_dir / "contributions.jsonl"))

    return charter_home


@pytest.fixture
def sample_config():
    """Return a valid charter config dict."""
    return {
        "domain": "general",
        "version": "1.0",
        "identity": {
            "public_id": "abc123",
            "alias": "test-node",
        },
        "governance": {
            "layer_a": {
                "description": "Hard constraints.",
                "universal": [
                    "Never violate applicable law",
                    "Never fabricate data, citations, or evidence",
                    "Never conceal the audit trail",
                    "Never impersonate a real person",
                ],
                "rules": [
                    "Never send external communications without approval",
                    "Never access financial accounts without authorization",
                ],
            },
            "layer_b": {
                "description": "Gradient decisions.",
                "rules": [
                    {
                        "action": "financial_transaction",
                        "threshold": "always",
                        "requires": "human_approval",
                        "description": "All spending requires human approval",
                    },
                ],
            },
            "layer_c": {
                "description": "Self-audit.",
                "frequency": "weekly",
                "report_includes": ["decisions_made", "rules_applied"],
            },
            "kill_triggers": [
                {
                    "trigger": "ethics_decline",
                    "description": "Ethics compliance declining",
                },
            ],
        },
    }


@pytest.fixture
def config_file(tmp_path, sample_config):
    """Write a charter.yaml file and return its path."""
    config_path = tmp_path / "charter.yaml"
    with open(config_path, "w") as f:
        yaml.dump(sample_config, f, default_flow_style=False)
    return str(config_path)
