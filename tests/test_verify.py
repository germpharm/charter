"""Tests for charter.verify — identity verification via external providers."""

import json
import os

from charter.verify import (
    configure_persona,
    configure_idme,
    load_verify_config,
    save_verify_config,
)


class TestConfigurePersona:
    def test_saves_persona_config(self, charter_home, monkeypatch):
        monkeypatch.setattr(
            "charter.verify.get_verify_config_path",
            lambda: str(charter_home / "verify_config.json"),
        )
        result = configure_persona("persona_sandbox_test123", "tmpl_abc", "sandbox")
        assert result["api_key"] == "persona_sandbox_test123"
        assert result["template_id"] == "tmpl_abc"
        assert result["environment"] == "sandbox"

        # Verify it persists
        config = load_verify_config()
        assert config["persona"]["api_key"] == "persona_sandbox_test123"

    def test_overwrites_existing(self, charter_home, monkeypatch):
        monkeypatch.setattr(
            "charter.verify.get_verify_config_path",
            lambda: str(charter_home / "verify_config.json"),
        )
        configure_persona("key1")
        configure_persona("key2")
        config = load_verify_config()
        assert config["persona"]["api_key"] == "key2"


class TestConfigureIdme:
    def test_saves_idme_config(self, charter_home, monkeypatch):
        monkeypatch.setattr(
            "charter.verify.get_verify_config_path",
            lambda: str(charter_home / "verify_config.json"),
        )
        result = configure_idme("client123", "secret456", environment="sandbox")
        assert result["client_id"] == "client123"
        assert result["client_secret"] == "secret456"

        config = load_verify_config()
        assert config["id_me"]["client_id"] == "client123"


class TestMultipleProviders:
    def test_both_providers_coexist(self, charter_home, monkeypatch):
        monkeypatch.setattr(
            "charter.verify.get_verify_config_path",
            lambda: str(charter_home / "verify_config.json"),
        )
        configure_persona("persona_key")
        configure_idme("idme_client", "idme_secret")

        config = load_verify_config()
        assert "persona" in config
        assert "id_me" in config
        assert config["persona"]["api_key"] == "persona_key"
        assert config["id_me"]["client_id"] == "idme_client"


class TestLoadVerifyConfig:
    def test_returns_none_when_missing(self, charter_home, monkeypatch):
        monkeypatch.setattr(
            "charter.verify.get_verify_config_path",
            lambda: str(charter_home / "nonexistent.json"),
        )
        assert load_verify_config() is None
