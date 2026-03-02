"""Tests for charter.arbitration — multi-model arbitration and divergence detection."""

import json
import os

import pytest

from charter.arbitration import (
    REVERSIBILITY_LEVELS,
    classify_reversibility,
    _tokenize,
    detect_divergence,
    check_layer_b_requirement,
    _determine_recommendation,
    _get_adapter,
    arbitrate,
)
from charter.config import VALID_REQUIRES
from charter.identity import create_identity


# ---------------------------------------------------------------------------
# Fake adapter for mocking model calls
# ---------------------------------------------------------------------------

class FakeAdapter:
    name = "fake"

    def __init__(self, response):
        self._response = response

    def query(self, prompt, system=None):
        return self._response


# ---------------------------------------------------------------------------
# classify_reversibility
# ---------------------------------------------------------------------------

class TestClassifyReversibility:
    def test_single_word_irreversible_delete(self):
        assert classify_reversibility("delete the database") == "irreversible"

    def test_single_word_irreversible_publish(self):
        assert classify_reversibility("publish the report") == "irreversible"

    def test_multi_word_irreversible_deploy_to_production(self):
        assert classify_reversibility("deploy to production now") == "irreversible"

    def test_multi_word_irreversible_sign_contract(self):
        assert classify_reversibility("sign contract with vendor") == "irreversible"

    def test_multi_word_irreversible_submit_to_fda(self):
        assert classify_reversibility("submit to fda for review") == "irreversible"

    def test_single_word_low_reversibility_change(self):
        assert classify_reversibility("change the schema") == "low_reversibility"

    def test_single_word_low_reversibility_migrate(self):
        assert classify_reversibility("migrate to new server") == "low_reversibility"

    def test_multi_word_low_reversibility_update_pricing(self):
        assert classify_reversibility("update pricing for Q3") == "low_reversibility"

    def test_reversible_no_keywords(self):
        assert classify_reversibility("read the documentation") == "reversible"

    def test_reversible_generic_action(self):
        assert classify_reversibility("check the logs") == "reversible"

    def test_empty_string(self):
        assert classify_reversibility("") == "reversible"

    def test_none_input(self):
        assert classify_reversibility(None) == "reversible"

    def test_case_insensitive(self):
        assert classify_reversibility("DELETE everything") == "irreversible"

    def test_irreversible_takes_priority_over_low(self):
        # "delete" is irreversible, "change" is low; irreversible checked first
        assert classify_reversibility("delete and change") == "irreversible"


# ---------------------------------------------------------------------------
# _tokenize
# ---------------------------------------------------------------------------

class TestTokenize:
    def test_normal_text(self):
        tokens = _tokenize("Hello World")
        assert tokens == {"hello", "world"}

    def test_punctuation_stripped(self):
        tokens = _tokenize("Hello, World! How's it going?")
        assert "hello" in tokens
        assert "world" in tokens
        assert "how" in tokens
        assert "s" in tokens
        # No punctuation characters should survive
        for t in tokens:
            assert t.isalnum(), f"Token '{t}' contains non-alnum characters"

    def test_empty_string(self):
        assert _tokenize("") == set()

    def test_none_input(self):
        assert _tokenize(None) == set()

    def test_mixed_case(self):
        tokens = _tokenize("FOO Bar baz")
        assert tokens == {"foo", "bar", "baz"}


# ---------------------------------------------------------------------------
# detect_divergence
# ---------------------------------------------------------------------------

class TestDetectDivergence:
    def test_identical_responses_zero(self):
        responses = {
            "model_a": "the sky is blue",
            "model_b": "the sky is blue",
        }
        assert detect_divergence(responses) == 0.0

    def test_completely_different_high_score(self):
        responses = {
            "model_a": "alpha bravo charlie",
            "model_b": "delta echo foxtrot",
        }
        score = detect_divergence(responses)
        assert score == 1.0

    def test_partial_overlap(self):
        responses = {
            "model_a": "the quick brown fox",
            "model_b": "the slow brown dog",
        }
        score = detect_divergence(responses)
        assert 0.0 < score < 1.0

    def test_single_response_returns_zero(self):
        responses = {"model_a": "only one model answered"}
        assert detect_divergence(responses) == 0.0

    def test_none_responses_filtered(self):
        responses = {
            "model_a": "some answer",
            "model_b": None,
        }
        # Only one valid response after filtering
        assert detect_divergence(responses) == 0.0

    def test_all_none_returns_zero(self):
        responses = {"model_a": None, "model_b": None}
        assert detect_divergence(responses) == 0.0

    def test_empty_dict_returns_zero(self):
        assert detect_divergence({}) == 0.0

    def test_three_models_average(self):
        responses = {
            "model_a": "the cat sat on the mat",
            "model_b": "the cat sat on the mat",
            "model_c": "xyz xyz xyz xyz xyz xyz",
        }
        score = detect_divergence(responses)
        # Two pairs agree (a-b=0), two pairs diverge (a-c, b-c high)
        assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# check_layer_b_requirement
# ---------------------------------------------------------------------------

class TestCheckLayerBRequirement:
    def test_matching_rule_returns_true(self):
        config = {
            "governance": {
                "layer_b": {
                    "rules": [
                        {
                            "action": "financial_transaction",
                            "threshold": "always",
                            "requires": "multi_model_check",
                        },
                    ],
                },
            },
        }
        assert check_layer_b_requirement(config, "financial_transaction") is True

    def test_non_matching_action_returns_false(self):
        config = {
            "governance": {
                "layer_b": {
                    "rules": [
                        {
                            "action": "financial_transaction",
                            "threshold": "always",
                            "requires": "multi_model_check",
                        },
                    ],
                },
            },
        }
        assert check_layer_b_requirement(config, "data_access") is False

    def test_non_matching_requires_returns_false(self):
        config = {
            "governance": {
                "layer_b": {
                    "rules": [
                        {
                            "action": "financial_transaction",
                            "threshold": "always",
                            "requires": "human_approval",
                        },
                    ],
                },
            },
        }
        assert check_layer_b_requirement(config, "financial_transaction") is False

    def test_empty_config_returns_false(self):
        assert check_layer_b_requirement({}, "financial_transaction") is False

    def test_none_config_returns_false(self):
        assert check_layer_b_requirement(None, "financial_transaction") is False

    def test_missing_governance_section_returns_false(self):
        config = {"domain": "general"}
        assert check_layer_b_requirement(config, "financial_transaction") is False

    def test_missing_layer_b_returns_false(self):
        config = {"governance": {}}
        assert check_layer_b_requirement(config, "financial_transaction") is False

    def test_empty_rules_list_returns_false(self):
        config = {"governance": {"layer_b": {"rules": []}}}
        assert check_layer_b_requirement(config, "financial_transaction") is False


# ---------------------------------------------------------------------------
# _determine_recommendation
# ---------------------------------------------------------------------------

class TestDetermineRecommendation:
    # Irreversible cases
    def test_irreversible_zero_responses(self):
        assert _determine_recommendation("irreversible", 0.0, 0) == "human_decision_required"

    def test_irreversible_single_response(self):
        assert _determine_recommendation("irreversible", 0.0, 1) == "human_decision_required"

    def test_irreversible_low_divergence_proceed(self):
        assert _determine_recommendation("irreversible", 0.1, 2) == "proceed"

    def test_irreversible_high_divergence(self):
        assert _determine_recommendation("irreversible", 0.5, 2) == "human_decision_required"

    def test_irreversible_borderline_divergence(self):
        # divergence > 0.3 triggers human_decision_required
        assert _determine_recommendation("irreversible", 0.31, 2) == "human_decision_required"

    def test_irreversible_at_threshold(self):
        # divergence exactly at 0.3 should not exceed threshold
        assert _determine_recommendation("irreversible", 0.3, 2) == "proceed"

    # Low reversibility cases
    def test_low_reversibility_low_divergence(self):
        assert _determine_recommendation("low_reversibility", 0.1, 2) == "proceed"

    def test_low_reversibility_medium_divergence(self):
        assert _determine_recommendation("low_reversibility", 0.4, 2) == "review_divergence"

    def test_low_reversibility_high_divergence(self):
        assert _determine_recommendation("low_reversibility", 0.6, 2) == "review_divergence"

    # Reversible cases
    def test_reversible_low_divergence(self):
        assert _determine_recommendation("reversible", 0.1, 2) == "proceed"

    def test_reversible_high_divergence(self):
        assert _determine_recommendation("reversible", 0.6, 2) == "review_divergence"

    def test_reversible_at_threshold(self):
        # divergence exactly at 0.5 should not exceed threshold
        assert _determine_recommendation("reversible", 0.5, 2) == "proceed"


# ---------------------------------------------------------------------------
# arbitrate (integration — mocked adapters)
# ---------------------------------------------------------------------------

class TestArbitrate:
    def _patch_adapter(self, monkeypatch, response_map):
        """Replace _get_adapter so each model name returns a FakeAdapter."""

        def fake_get_adapter(name):
            if name in response_map:
                return FakeAdapter(response_map[name])
            return None

        monkeypatch.setattr("charter.arbitration._get_adapter", fake_get_adapter)

    def test_basic_arbitration(self, charter_home, monkeypatch):
        create_identity()
        self._patch_adapter(monkeypatch, {
            "local": "The action is safe and advisable.",
            "anthropic": "The action is safe and advisable.",
        })

        result = arbitrate(
            "Should we read the docs?",
            models=["local", "anthropic"],
        )

        assert result is not None
        assert result["reversibility"] == "reversible"
        assert result["recommended_action"] == "proceed"
        assert result["divergence_score"] == 0.0
        assert result["agreement"] is True
        assert "local" in result["models_consulted"]
        assert "anthropic" in result["models_consulted"]
        assert result["models_failed"] == []

    def test_chain_events_recorded(self, charter_home, monkeypatch):
        create_identity()
        self._patch_adapter(monkeypatch, {"local": "Looks good."})

        arbitrate("check the logs", models=["local"])

        chain_path = str(charter_home / "chain.jsonl")
        with open(chain_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        events = [e["event"] for e in entries]
        assert "arbitration_requested" in events
        assert "arbitration_completed" in events

    def test_divergence_event_logged(self, charter_home, monkeypatch):
        create_identity()
        self._patch_adapter(monkeypatch, {
            "local": "alpha bravo charlie",
            "anthropic": "delta echo foxtrot",
        })

        result = arbitrate(
            "check something",
            models=["local", "anthropic"],
        )

        assert result["divergence_score"] > 0.3

        chain_path = str(charter_home / "chain.jsonl")
        with open(chain_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        events = [e["event"] for e in entries]
        assert "arbitration_divergence_detected" in events

    def test_explicit_reversibility_override(self, charter_home, monkeypatch):
        create_identity()
        self._patch_adapter(monkeypatch, {
            "local": "Proceed with caution.",
            "anthropic": "Proceed with caution.",
        })

        result = arbitrate(
            "read a file",
            models=["local", "anthropic"],
            reversibility="irreversible",
        )

        assert result["reversibility"] == "irreversible"
        assert result["recommended_action"] == "proceed"

    def test_explicit_models_list(self, charter_home, monkeypatch):
        create_identity()
        self._patch_adapter(monkeypatch, {
            "local": "Answer from local model.",
        })

        result = arbitrate("check something", models=["local"])

        assert result["models_consulted"] == ["local"]
        assert "local" in result["responses"]

    def test_failed_model_tracked(self, charter_home, monkeypatch):
        create_identity()
        self._patch_adapter(monkeypatch, {
            "local": "Answer from local.",
            "anthropic": None,
        })

        result = arbitrate(
            "check something",
            models=["local", "anthropic"],
        )

        assert "local" in result["models_consulted"]
        assert "anthropic" in result["models_failed"]

    def test_none_question_returns_none(self, charter_home, monkeypatch):
        create_identity()
        assert arbitrate(None) is None

    def test_empty_question_returns_none(self, charter_home, monkeypatch):
        create_identity()
        assert arbitrate("") is None

    def test_invalid_reversibility_override_defaults_to_reversible(
        self, charter_home, monkeypatch
    ):
        create_identity()
        self._patch_adapter(monkeypatch, {"local": "ok"})

        result = arbitrate(
            "do something",
            models=["local"],
            reversibility="not_a_real_level",
        )

        assert result["reversibility"] == "reversible"

    def test_irreversible_keyword_auto_classified(self, charter_home, monkeypatch):
        create_identity()
        self._patch_adapter(monkeypatch, {
            "local": "Risky move.",
            "anthropic": "Risky move.",
        })

        result = arbitrate(
            "delete the production database",
            models=["local", "anthropic"],
        )

        assert result["reversibility"] == "irreversible"

    def test_question_hash_present(self, charter_home, monkeypatch):
        create_identity()
        self._patch_adapter(monkeypatch, {"local": "ok"})

        result = arbitrate("test question", models=["local"])
        assert "question_hash" in result
        assert len(result["question_hash"]) == 16

    def test_timestamp_present(self, charter_home, monkeypatch):
        create_identity()
        self._patch_adapter(monkeypatch, {"local": "ok"})

        result = arbitrate("test question", models=["local"])
        assert "timestamp" in result
        assert "T" in result["timestamp"]


# ---------------------------------------------------------------------------
# VALID_REQUIRES includes multi_model_check
# ---------------------------------------------------------------------------

class TestConfigIntegration:
    def test_multi_model_check_in_valid_requires(self):
        assert "multi_model_check" in VALID_REQUIRES
