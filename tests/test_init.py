"""Tests for charter.init_cmd — domain templates and initialization."""

import os

from charter.init_cmd import load_template, DOMAINS


class TestLoadTemplate:
    def test_loads_all_domains(self):
        for domain in DOMAINS:
            template = load_template(domain)
            assert template is not None
            assert "governance" in template
            assert "layer_a" in template["governance"]
            assert "layer_b" in template["governance"]
            assert "layer_c" in template["governance"]

    def test_healthcare_has_hipaa_rules(self):
        template = load_template("healthcare")
        rules = template["governance"]["layer_a"]["rules"]
        hipaa_related = [r for r in rules if "patient" in r.lower() or "health" in r.lower()]
        assert len(hipaa_related) > 0

    def test_default_fallback(self):
        template = load_template("nonexistent_domain")
        assert template is not None
        assert template["domain"] == "general"

    def test_all_templates_have_kill_triggers(self):
        for domain in DOMAINS:
            template = load_template(domain)
            assert "kill_triggers" in template["governance"]
            assert len(template["governance"]["kill_triggers"]) > 0

    def test_layer_a_rules_are_strings(self):
        for domain in DOMAINS:
            template = load_template(domain)
            for rule in template["governance"]["layer_a"]["rules"]:
                assert isinstance(rule, str)

    def test_layer_b_rules_are_dicts(self):
        for domain in DOMAINS:
            template = load_template(domain)
            for rule in template["governance"]["layer_b"]["rules"]:
                assert isinstance(rule, dict)
                assert "action" in rule
