"""Tests for charter.redteam — adversarial testing of Charter governance."""

import json
import os

import yaml

from charter.identity import create_identity, append_to_chain
from charter.redteam import (
    BATTERY_CATEGORIES,
    RedTeamScenario,
    RedTeamRunner,
    _get_builtin_scenarios,
    _build_context,
    generate_from_threats,
    generate_report,
    _summarize_result,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestBatteryCategories:
    def test_has_six_categories(self):
        assert len(BATTERY_CATEGORIES) == 6

    def test_expected_categories_present(self):
        expected = [
            "constraint_escape",
            "gradient_manipulation",
            "chain_tampering",
            "threshold_erosion",
            "identity_spoofing",
            "audit_evasion",
        ]
        assert BATTERY_CATEGORIES == expected

    def test_all_strings(self):
        for cat in BATTERY_CATEGORIES:
            assert isinstance(cat, str)


# ---------------------------------------------------------------------------
# RedTeamScenario
# ---------------------------------------------------------------------------


class TestRedTeamScenario:
    def test_construction(self):
        scenario = RedTeamScenario(
            name="test_scenario",
            category="constraint_escape",
            description="A test scenario",
            attack_fn=lambda ctx: {"attacked": True},
            verify_fn=lambda ctx, result: True,
        )
        assert scenario.name == "test_scenario"
        assert scenario.category == "constraint_escape"
        assert scenario.description == "A test scenario"
        assert callable(scenario.attack_fn)
        assert callable(scenario.verify_fn)

    def test_attack_fn_called(self):
        called = {"attack": False, "verify": False}

        def attack(ctx):
            called["attack"] = True
            return {"data": "payload"}

        def verify(ctx, result):
            called["verify"] = True
            return result["data"] == "payload"

        scenario = RedTeamScenario(
            name="call_test",
            category="audit_evasion",
            description="Test function calls",
            attack_fn=attack,
            verify_fn=verify,
        )
        ctx = {}
        result = scenario.attack_fn(ctx)
        assert called["attack"]
        assert result == {"data": "payload"}

        passed = scenario.verify_fn(ctx, result)
        assert called["verify"]
        assert passed is True

    def test_failing_verify(self):
        scenario = RedTeamScenario(
            name="fail_test",
            category="chain_tampering",
            description="Verify returns False",
            attack_fn=lambda ctx: {"breached": True},
            verify_fn=lambda ctx, result: False,
        )
        result = scenario.attack_fn({})
        assert scenario.verify_fn({}, result) is False


# ---------------------------------------------------------------------------
# Built-in scenario registry
# ---------------------------------------------------------------------------


class TestBuiltinScenarios:
    def test_builtin_count(self):
        scenarios = _get_builtin_scenarios()
        assert len(scenarios) == 12

    def test_all_are_redteam_scenarios(self):
        for s in _get_builtin_scenarios():
            assert isinstance(s, RedTeamScenario)

    def test_all_categories_covered(self):
        scenarios = _get_builtin_scenarios()
        categories = {s.category for s in scenarios}
        for cat in BATTERY_CATEGORIES:
            assert cat in categories, f"Category {cat} not covered by any scenario"

    def test_unique_names(self):
        scenarios = _get_builtin_scenarios()
        names = [s.name for s in scenarios]
        assert len(names) == len(set(names)), "Duplicate scenario names found"

    def test_all_have_descriptions(self):
        for s in _get_builtin_scenarios():
            assert s.description, f"Scenario {s.name} has no description"

    def test_all_have_callables(self):
        for s in _get_builtin_scenarios():
            assert callable(s.attack_fn), f"{s.name}: attack_fn not callable"
            assert callable(s.verify_fn), f"{s.name}: verify_fn not callable"


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


class TestBuildContext:
    def test_builds_with_config_and_chain(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="ctx-test")
        append_to_chain("test_event", {"detail": "context_test"})
        chain_path = str(charter_home / "chain.jsonl")

        ctx = _build_context(config_path=config_file, chain_path=chain_path)
        assert ctx["config"] is not None
        assert ctx["config_path"] == config_file
        assert ctx["config_copy"] is not None
        assert ctx["identity"] is not None
        assert len(ctx["chain_entries"]) >= 2  # genesis + 1
        assert len(ctx["chain_copy"]) == len(ctx["chain_entries"])

    def test_builds_without_config(self, charter_home, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        create_identity(alias="no-config")
        chain_path = str(charter_home / "chain.jsonl")

        ctx = _build_context(config_path=None, chain_path=chain_path)
        # No charter.yaml in tmp_path => config is None
        assert ctx["config"] is None
        assert ctx["config_copy"] is None
        assert ctx["identity"] is not None


# ---------------------------------------------------------------------------
# RedTeamRunner
# ---------------------------------------------------------------------------


class TestRedTeamRunner:
    def test_init_defaults(self):
        runner = RedTeamRunner()
        assert runner.config_path is None
        assert runner.chain_path is None
        assert runner._context is None

    def test_init_with_paths(self, config_file, charter_home):
        chain_path = str(charter_home / "chain.jsonl")
        runner = RedTeamRunner(config_path=config_file, chain_path=chain_path)
        assert runner.config_path == config_file
        assert runner.chain_path == chain_path

    def test_run_scenario_passing(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="runner-pass")

        scenario = RedTeamScenario(
            name="always_pass",
            category="constraint_escape",
            description="Always passes",
            attack_fn=lambda ctx: {"ok": True},
            verify_fn=lambda ctx, result: True,
        )
        runner = RedTeamRunner(config_path=config_file,
                               chain_path=str(charter_home / "chain.jsonl"))
        result = runner.run_scenario(scenario)
        assert result is not None
        assert result["passed"] is True
        assert result["scenario"] == "always_pass"
        assert result["category"] == "constraint_escape"

    def test_run_scenario_failing(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="runner-fail")

        scenario = RedTeamScenario(
            name="always_fail",
            category="chain_tampering",
            description="Always fails",
            attack_fn=lambda ctx: {"breached": True},
            verify_fn=lambda ctx, result: False,
        )
        runner = RedTeamRunner(config_path=config_file,
                               chain_path=str(charter_home / "chain.jsonl"))
        result = runner.run_scenario(scenario)
        assert result is not None
        assert result["passed"] is False

    def test_run_scenario_exception(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="runner-exc")

        def exploding_attack(ctx):
            raise RuntimeError("boom")

        scenario = RedTeamScenario(
            name="error_scenario",
            category="audit_evasion",
            description="Raises exception",
            attack_fn=exploding_attack,
            verify_fn=lambda ctx, result: True,
        )
        runner = RedTeamRunner(config_path=config_file,
                               chain_path=str(charter_home / "chain.jsonl"))
        result = runner.run_scenario(scenario)
        assert result is not None
        assert result["passed"] is False
        assert "boom" in result["details"]

    def test_run_scenario_returns_none_on_none_attack(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="runner-none")

        scenario = RedTeamScenario(
            name="none_attack",
            category="constraint_escape",
            description="Attack returns None",
            attack_fn=lambda ctx: None,
            verify_fn=lambda ctx, result: True,
        )
        runner = RedTeamRunner(config_path=config_file,
                               chain_path=str(charter_home / "chain.jsonl"))
        result = runner.run_scenario(scenario)
        assert result is None

    def test_run_battery_all(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="battery-all")
        append_to_chain("setup_event", {"detail": "battery test"})

        runner = RedTeamRunner(config_path=config_file,
                               chain_path=str(charter_home / "chain.jsonl"))
        results = runner.run_battery()
        assert results is not None
        assert "passed" in results
        assert "failed" in results
        assert "total" in results
        assert "results" in results
        assert "duration_ms" in results
        assert results["total"] == results["passed"] + results["failed"]
        assert results["total"] > 0
        assert len(results["results"]) == results["total"]

    def test_run_battery_filtered_by_category(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="battery-filter")
        append_to_chain("setup_event", {"detail": "filter test"})

        runner = RedTeamRunner(config_path=config_file,
                               chain_path=str(charter_home / "chain.jsonl"))
        results = runner.run_battery(categories=["constraint_escape"])
        assert results is not None
        for r in results["results"]:
            assert r["category"] == "constraint_escape"
        # There are 2 constraint_escape scenarios
        assert results["total"] == 2

    def test_run_battery_multiple_categories(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="battery-multi")
        append_to_chain("setup_event", {"detail": "multi-category test"})

        runner = RedTeamRunner(config_path=config_file,
                               chain_path=str(charter_home / "chain.jsonl"))
        results = runner.run_battery(categories=["constraint_escape", "identity_spoofing"])
        assert results is not None
        cats = {r["category"] for r in results["results"]}
        assert cats.issubset({"constraint_escape", "identity_spoofing"})

    def test_run_battery_returns_none_for_empty_category(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="battery-empty")

        runner = RedTeamRunner(config_path=config_file,
                               chain_path=str(charter_home / "chain.jsonl"))
        results = runner.run_battery(categories=["nonexistent_category"])
        assert results is None

    def test_context_is_cached(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="cache-test")

        runner = RedTeamRunner(config_path=config_file,
                               chain_path=str(charter_home / "chain.jsonl"))
        ctx1 = runner._get_context()
        ctx2 = runner._get_context()
        assert ctx1 is ctx2


# ---------------------------------------------------------------------------
# Built-in scenarios integration
# ---------------------------------------------------------------------------


class TestBuiltinScenariosIntegration:
    """Run each built-in scenario against a real charter_home + config_file setup."""

    def test_all_builtins_run_without_error(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="builtin-int")
        # Add extra chain entries so link/gap/timestamp scenarios have data
        append_to_chain("event_1", {"detail": "first"})
        append_to_chain("event_2", {"detail": "second"})
        append_to_chain("event_3", {"detail": "third"})

        runner = RedTeamRunner(config_path=config_file,
                               chain_path=str(charter_home / "chain.jsonl"))
        results = runner.run_battery()
        assert results is not None
        assert results["total"] > 0
        # Every result dict has the expected keys
        for r in results["results"]:
            assert "passed" in r
            assert "scenario" in r
            assert "category" in r
            assert "details" in r

    def test_all_builtins_pass_on_clean_setup(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="builtin-clean")
        append_to_chain("setup_1", {"a": 1})
        append_to_chain("setup_2", {"b": 2})
        append_to_chain("setup_3", {"c": 3})

        runner = RedTeamRunner(config_path=config_file,
                               chain_path=str(charter_home / "chain.jsonl"))
        results = runner.run_battery()
        assert results is not None
        # On a clean setup with intact chain and config, all defenses should hold
        assert results["failed"] == 0, (
            f"{results['failed']} scenario(s) failed: "
            + ", ".join(r["scenario"] for r in results["results"] if not r["passed"])
        )


# ---------------------------------------------------------------------------
# generate_from_threats
# ---------------------------------------------------------------------------


class TestGenerateFromThreats:
    def test_parses_yaml_threat_file(self, tmp_path, config_file, charter_home, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        threats_yaml = {
            "threats": [
                {
                    "name": "test threat one",
                    "category": "constraint_escape",
                    "description": "Try to bypass rules",
                    "attack_pattern": "data_exfiltration",
                    "expected_block": "layer_a",
                },
                {
                    "name": "test threat two",
                    "category": "audit_evasion",
                    "description": "Suppress audit logs",
                    "attack_pattern": "log_suppression",
                    "expected_block": "layer_c",
                },
            ]
        }
        threats_path = tmp_path / "threats.yaml"
        with open(threats_path, "w") as f:
            yaml.dump(threats_yaml, f, default_flow_style=False)

        scenarios = generate_from_threats(str(threats_path))
        assert scenarios is not None
        assert len(scenarios) == 2
        assert scenarios[0].name == "threat_test_threat_one"
        assert scenarios[0].category == "constraint_escape"
        assert scenarios[1].name == "threat_test_threat_two"
        assert scenarios[1].category == "audit_evasion"

    def test_parses_json_threat_file(self, tmp_path):
        threats_data = {
            "threats": [
                {
                    "name": "json threat",
                    "category": "chain_tampering",
                    "description": "Tamper with chain from JSON",
                    "attack_pattern": "hash_collision",
                    "expected_block": "layer_a",
                }
            ]
        }
        threats_path = tmp_path / "threats.json"
        with open(threats_path, "w") as f:
            json.dump(threats_data, f)

        scenarios = generate_from_threats(str(threats_path))
        assert scenarios is not None
        assert len(scenarios) == 1
        assert scenarios[0].name == "threat_json_threat"

    def test_generated_scenarios_are_runnable(self, tmp_path, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="threat-run")

        threats_yaml = {
            "threats": [
                {
                    "name": "runnable threat",
                    "category": "constraint_escape",
                    "description": "Test running a generated scenario",
                    "attack_pattern": "",
                    "expected_block": "layer_a",
                }
            ]
        }
        threats_path = tmp_path / "threats_run.yaml"
        with open(threats_path, "w") as f:
            yaml.dump(threats_yaml, f, default_flow_style=False)

        scenarios = generate_from_threats(str(threats_path))
        assert scenarios is not None

        runner = RedTeamRunner(config_path=config_file,
                               chain_path=str(charter_home / "chain.jsonl"))
        result = runner.run_scenario(scenarios[0])
        assert result is not None
        assert "passed" in result

    def test_returns_none_for_missing_file(self):
        result = generate_from_threats("/nonexistent/path/threats.yaml")
        assert result is None

    def test_returns_none_for_empty_threats(self, tmp_path):
        threats_path = tmp_path / "empty.yaml"
        with open(threats_path, "w") as f:
            yaml.dump({"threats": []}, f)

        result = generate_from_threats(str(threats_path))
        assert result is None

    def test_returns_none_for_invalid_yaml(self, tmp_path):
        threats_path = tmp_path / "bad.yaml"
        threats_path.write_text(": : : not valid yaml or json : : :\x00\x01")

        result = generate_from_threats(str(threats_path))
        assert result is None

    def test_name_sanitization(self, tmp_path):
        threats_yaml = {
            "threats": [
                {
                    "name": "PHI Extraction - Attempt",
                    "category": "constraint_escape",
                    "description": "Test name sanitization",
                    "expected_block": "layer_a",
                }
            ]
        }
        threats_path = tmp_path / "sanitize.yaml"
        with open(threats_path, "w") as f:
            yaml.dump(threats_yaml, f, default_flow_style=False)

        scenarios = generate_from_threats(str(threats_path))
        assert scenarios is not None
        # Spaces become underscores, hyphens become underscores
        assert scenarios[0].name == "threat_phi_extraction___attempt"


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def _make_results(self, passed_count, failed_count):
        """Helper to build a results dict matching run_battery output."""
        results_list = []
        for i in range(passed_count):
            results_list.append({
                "passed": True,
                "scenario": f"pass_scenario_{i}",
                "category": BATTERY_CATEGORIES[i % len(BATTERY_CATEGORIES)],
                "details": "defense held",
            })
        for i in range(failed_count):
            results_list.append({
                "passed": False,
                "scenario": f"fail_scenario_{i}",
                "category": BATTERY_CATEGORIES[i % len(BATTERY_CATEGORIES)],
                "details": "DEFENSE BREACHED",
            })
        return {
            "passed": passed_count,
            "failed": failed_count,
            "total": passed_count + failed_count,
            "results": results_list,
            "duration_ms": 42,
        }

    def test_returns_none_for_none_input(self):
        assert generate_report(None) is None

    def test_returns_none_for_empty_dict(self):
        assert generate_report({}) is None

    def test_produces_markdown_string(self):
        results = self._make_results(6, 0)
        report = generate_report(results)
        assert report is not None
        assert isinstance(report, str)
        assert "# Charter Red Team Report" in report

    def test_shows_passed_count(self):
        results = self._make_results(10, 0)
        report = generate_report(results)
        assert "10/10" in report
        assert "ALL DEFENSES HELD" in report

    def test_shows_failed_count(self):
        results = self._make_results(3, 2)
        report = generate_report(results)
        assert "3/5" in report
        assert "2/5" in report
        assert "DEFENSES BREACHED" in report

    def test_includes_category_breakdown(self):
        results = self._make_results(6, 0)
        report = generate_report(results)
        assert "## Category Breakdown" in report

    def test_includes_failed_details(self):
        results = self._make_results(0, 1)
        report = generate_report(results)
        assert "## Failed Scenarios" in report
        assert "fail_scenario_0" in report

    def test_includes_recommendations_when_failures(self):
        results = self._make_results(2, 1)
        report = generate_report(results)
        assert "## Recommendations" in report

    def test_includes_all_clear_when_all_pass(self):
        results = self._make_results(5, 0)
        report = generate_report(results)
        assert "All defenses held" in report

    def test_includes_duration(self):
        results = self._make_results(1, 0)
        report = generate_report(results)
        assert "42ms" in report


# ---------------------------------------------------------------------------
# _summarize_result helper
# ---------------------------------------------------------------------------


class TestSummarizeResult:
    def test_skipped_result(self):
        summary = _summarize_result({"skipped": True, "reason": "no config"}, True)
        assert "Skipped" in summary
        assert "no config" in summary

    def test_defense_held(self):
        summary = _summarize_result({"ok": True}, True)
        assert "defense held" in summary

    def test_defense_breached(self):
        summary = _summarize_result({"ok": True}, False)
        assert "DEFENSE BREACHED" in summary

    def test_includes_hash_fields(self):
        result = {
            "original_hash": "a" * 64,
            "tampered_hash": "b" * 64,
        }
        summary = _summarize_result(result, True)
        assert "original_hash=" in summary
        assert "tampered_hash=" in summary

    def test_includes_boolean_fields(self):
        result = {"signatures_differ": True, "sigs_match": False}
        summary = _summarize_result(result, True)
        assert "signatures_differ=True" in summary
        assert "sigs_match=False" in summary


# ---------------------------------------------------------------------------
# Full integration: battery against initialized environment
# ---------------------------------------------------------------------------


class TestFullIntegration:
    def test_full_battery_with_identity_and_config(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="full-integration")
        # Build a chain with enough entries for all scenarios
        for i in range(5):
            append_to_chain(f"integration_event_{i}", {"step": i, "value": i * 10})

        runner = RedTeamRunner(
            config_path=config_file,
            chain_path=str(charter_home / "chain.jsonl"),
        )
        results = runner.run_battery()
        assert results is not None
        assert results["total"] > 0
        assert results["duration_ms"] >= 0

        # Generate a report from those results
        report = generate_report(results)
        assert report is not None
        assert "# Charter Red Team Report" in report
        assert "## Summary" in report
        assert "## Category Breakdown" in report

    def test_full_battery_then_category_filter(self, charter_home, config_file, monkeypatch):
        monkeypatch.chdir(os.path.dirname(config_file))
        create_identity(alias="filter-int")
        append_to_chain("setup", {"x": 1})
        append_to_chain("setup2", {"x": 2})
        append_to_chain("setup3", {"x": 3})

        runner = RedTeamRunner(
            config_path=config_file,
            chain_path=str(charter_home / "chain.jsonl"),
        )

        full = runner.run_battery()
        # Reset context for filtered run
        runner._context = None
        filtered = runner.run_battery(categories=["identity_spoofing"])

        assert full["total"] > filtered["total"]
        assert filtered["total"] == 2  # 2 identity_spoofing scenarios
