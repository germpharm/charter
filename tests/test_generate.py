"""Tests for charter.generate — rendering governance instructions."""

from charter.generate import render_claude_md, render_system_prompt, render_raw


class TestRenderClaudeMd:
    def test_contains_layer_a(self, sample_config):
        output = render_claude_md(sample_config)
        assert "## Layer A: Hard Constraints" in output

    def test_contains_universal_floor(self, sample_config):
        output = render_claude_md(sample_config)
        assert "### Universal (accountability floor)" in output
        assert "Never violate applicable law" in output
        assert "Never fabricate data, citations, or evidence" in output
        assert "Never conceal the audit trail" in output
        assert "Never impersonate a real person" in output

    def test_contains_domain_rules(self, sample_config):
        output = render_claude_md(sample_config)
        assert "### Domain Rules" in output
        assert "Never send external communications without approval" in output

    def test_universal_before_domain(self, sample_config):
        output = render_claude_md(sample_config)
        universal_pos = output.index("### Universal")
        domain_pos = output.index("### Domain Rules")
        assert universal_pos < domain_pos

    def test_contains_layer_b(self, sample_config):
        output = render_claude_md(sample_config)
        assert "## Layer B: Gradient Decisions" in output
        assert "financial_transaction" in output
        assert "$100" in output

    def test_contains_layer_c(self, sample_config):
        output = render_claude_md(sample_config)
        assert "## Layer C: Self-Audit" in output
        assert "weekly" in output

    def test_contains_kill_triggers(self, sample_config):
        output = render_claude_md(sample_config)
        assert "## Kill Triggers" in output
        assert "ethics_decline" in output

    def test_no_kill_triggers_section_when_empty(self, sample_config):
        sample_config["governance"]["kill_triggers"] = []
        output = render_claude_md(sample_config)
        assert "## Kill Triggers" not in output

    def test_includes_domain(self, sample_config):
        output = render_claude_md(sample_config)
        assert "general" in output

    def test_includes_alias(self, sample_config):
        output = render_claude_md(sample_config)
        assert "test-node" in output


class TestRenderSystemPrompt:
    def test_contains_constraints(self, sample_config):
        output = render_system_prompt(sample_config)
        assert "HARD CONSTRAINTS" in output
        assert "Never violate applicable law" in output

    def test_system_prompt_has_universal_and_domain(self, sample_config):
        output = render_system_prompt(sample_config)
        assert "Universal (accountability floor)" in output
        assert "Domain rules:" in output

    def test_contains_approval_required(self, sample_config):
        output = render_system_prompt(sample_config)
        assert "APPROVAL REQUIRED" in output

    def test_contains_self_audit(self, sample_config):
        output = render_system_prompt(sample_config)
        assert "SELF-AUDIT" in output

    def test_contains_kill_triggers(self, sample_config):
        output = render_system_prompt(sample_config)
        assert "KILL TRIGGERS" in output


class TestRenderRaw:
    def test_returns_yaml(self, sample_config):
        output = render_raw(sample_config)
        assert "layer_a:" in output
        assert "layer_b:" in output
        assert "layer_c:" in output
