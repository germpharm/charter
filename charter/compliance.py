"""Charter compliance mapping — map governance layers to regulatory frameworks.

Maps Charter's three-layer governance model (Layer A hard constraints,
Layer B gradient decisions, Layer C self-audit) plus kill triggers and
hash chain to established regulatory compliance frameworks such as
SOX, HIPAA, and FERPA.

Generates coverage reports showing which regulatory controls are
addressed by existing Charter governance rules, which have partial
coverage, and which represent gaps requiring additional configuration.

Usage:
    charter compliance map --standard hipaa
    charter compliance report --standard sox
    charter compliance gap --standard ferpa
    charter compliance standards
"""

import json
import os
import sys
import time

import yaml

from charter.config import load_config


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates", "compliance")


# ---------------------------------------------------------------------------
# ComplianceMapper
# ---------------------------------------------------------------------------

class ComplianceMapper:
    """Map Charter governance to regulatory compliance frameworks.

    Loads a Charter governance config and a compliance standard template,
    then evaluates each regulatory control against the governance rules
    to determine coverage status.

    Attributes:
        config: The Charter governance config dict.
        standard: The compliance standard name (e.g., "hipaa").
        standard_data: The loaded compliance template dict.
    """

    def __init__(self, config=None, standard=None):
        """Initialize with charter config and compliance standard.

        Args:
            config: Charter governance config dict (from charter.yaml).
                If None, loads via charter.config.load_config().
            standard: Compliance standard name ("sox", "hipaa", "ferpa").
        """
        self.config = config or load_config()
        self.standard = standard
        self.standard_data = None

        if self.standard:
            self.standard_data = self.load_standard(self.standard)

    def load_standard(self, standard_name):
        """Load a compliance template YAML from the templates directory.

        Args:
            standard_name: Name of the standard (e.g., "hipaa").
                Corresponds to templates/compliance/<name>.yaml.

        Returns:
            The standard dict parsed from YAML, or None if not found.
        """
        path = os.path.join(TEMPLATES_DIR, f"{standard_name}.yaml")
        if not os.path.isfile(path):
            return None
        with open(path) as f:
            data = yaml.safe_load(f)
        self.standard = standard_name
        self.standard_data = data
        return data

    def map_to_standard(self):
        """Map current governance config against the loaded compliance standard.

        Evaluates each control defined in the compliance template against
        the Charter governance layers, kill triggers, and hash chain.

        Returns:
            Dict with mapping results including coverage statistics
            and per-control status. Returns None if config or standard
            is not loaded.
        """
        if not self.config or not self.standard_data:
            return None

        gov = self.config.get("governance", {})
        controls = self.standard_data.get("controls", [])
        mappings = []

        for control in controls:
            mapping = self._evaluate_control(control, gov)
            mappings.append(mapping)

        total = len(mappings)
        covered = sum(1 for m in mappings if m["status"] == "covered")
        partial = sum(1 for m in mappings if m["status"] == "partial")
        gap = sum(1 for m in mappings if m["status"] == "gap")
        coverage_pct = round((covered / total) * 100, 1) if total > 0 else 0.0

        return {
            "standard": self.standard,
            "standard_name": self.standard_data.get("name", self.standard),
            "total_controls": total,
            "covered_controls": covered,
            "partial_controls": partial,
            "gap_controls": gap,
            "coverage_percentage": coverage_pct,
            "mappings": mappings,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        }

    def gap_analysis(self):
        """Return only controls with status 'gap' or 'partial'.

        Runs map_to_standard() and filters to controls that are not
        fully covered, providing a focused view of compliance gaps.

        Returns:
            List of control mapping dicts with status 'gap' or 'partial'.
            Returns empty list if mapping fails.
        """
        result = self.map_to_standard()
        if not result:
            return []
        return [m for m in result["mappings"] if m["status"] in ("gap", "partial")]

    def generate_report(self, format="markdown"):
        """Generate a formatted compliance report.

        Args:
            format: Output format. Currently only "markdown" is supported.

        Returns:
            Formatted report string. Returns empty string if mapping fails.
        """
        result = self.map_to_standard()
        if not result:
            return ""

        if format == "markdown":
            return self._format_markdown(result)
        return ""

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _evaluate_control(self, control, gov):
        """Evaluate a single compliance control against governance config.

        Args:
            control: Control dict from the compliance template.
            gov: The governance section of the charter config.

        Returns:
            Mapping dict with control details and coverage status.
        """
        match_spec = control.get("match", {})
        match_type = match_spec.get("type", "")
        keywords = match_spec.get("keywords", [])
        action = match_spec.get("action")

        charter_rules = []
        charter_coverage = None

        if match_type == "layer_a":
            layer_a = gov.get("layer_a", {})
            rules = layer_a.get("rules", [])
            universal = layer_a.get("universal", [])
            all_rules = rules + universal
            matched = self._match_layer_a(all_rules, keywords)
            if matched:
                charter_coverage = "layer_a"
                charter_rules = matched

        elif match_type == "layer_b":
            layer_b = gov.get("layer_b", {})
            rules = layer_b.get("rules", [])
            matched = self._match_layer_b(rules, action=action, keywords=keywords)
            if matched:
                charter_coverage = "layer_b"
                charter_rules = [self._format_layer_b_rule(r) for r in matched]

        elif match_type == "layer_c":
            layer_c = gov.get("layer_c", {})
            if self._match_layer_c(layer_c, keywords):
                charter_coverage = "layer_c"
                frequency = layer_c.get("frequency", "unset")
                includes = layer_c.get("report_includes", [])
                charter_rules = [f"Audit frequency: {frequency}"]
                # Check if any report_includes keywords match
                for inc in includes:
                    for kw in keywords:
                        if kw.lower() in inc.lower():
                            charter_rules.append(f"Report includes: {inc}")
                            break

        elif match_type == "kill_triggers":
            triggers = gov.get("kill_triggers", [])
            matched = self._match_kill_triggers(triggers, keywords)
            if matched:
                charter_coverage = "kill_triggers"
                charter_rules = [self._format_trigger(t) for t in matched]

        elif match_type == "chain":
            # Hash chain existence provides audit trail coverage
            charter_coverage = "chain"
            charter_rules = ["Hash chain provides immutable audit trail"]

        # Also check across layers for partial coverage if primary didn't match
        if not charter_coverage:
            # Try all layers as fallback for partial matches
            partial_rules = self._cross_layer_search(gov, keywords)
            if partial_rules:
                charter_coverage = partial_rules[0][0]  # layer name
                charter_rules = [r for _, r in partial_rules]

        status = self._determine_status(charter_rules, charter_coverage, match_type)

        return {
            "control_id": control.get("id", ""),
            "control_name": control.get("name", ""),
            "description": control.get("description", ""),
            "charter_coverage": charter_coverage,
            "charter_rules": charter_rules,
            "status": status,
            "notes": self._build_notes(charter_coverage, charter_rules, control),
            "recommendation": control.get("recommendation", ""),
        }

    def _match_layer_a(self, rules, keywords):
        """Match Layer A rules (strings) against keywords.

        Args:
            rules: List of Layer A rule strings.
            keywords: List of keywords to search for.

        Returns:
            List of matching rule strings.
        """
        matched = []
        for rule in rules:
            if not isinstance(rule, str):
                continue
            rule_lower = rule.lower()
            for kw in keywords:
                if kw.lower() in rule_lower:
                    matched.append(rule)
                    break
        return matched

    def _match_layer_b(self, rules, action=None, keywords=None):
        """Match Layer B rules (dicts) against action name or keywords.

        Args:
            rules: List of Layer B rule dicts.
            action: Specific action name to match (e.g., "data_access").
            keywords: List of keywords to search in action/description.

        Returns:
            List of matching Layer B rule dicts.
        """
        matched = []
        keywords = keywords or []
        for rule in rules:
            if not isinstance(rule, dict):
                continue

            # Direct action match
            if action and rule.get("action", "").lower() == action.lower():
                matched.append(rule)
                continue

            # Keyword match against action and description
            rule_action = rule.get("action", "").lower()
            rule_desc = rule.get("description", "").lower()
            rule_text = f"{rule_action} {rule_desc}"
            for kw in keywords:
                if kw.lower() in rule_text:
                    matched.append(rule)
                    break

        return matched

    def _match_layer_c(self, config, keywords):
        """Check if Layer C audit config matches keywords.

        Args:
            config: Layer C config dict.
            keywords: List of keywords to search for.

        Returns:
            True if Layer C configuration matches any keyword.
        """
        if not config:
            return False

        # Check frequency, description, and report_includes
        text_parts = [
            config.get("description", ""),
            config.get("frequency", ""),
        ]
        text_parts.extend(config.get("report_includes", []))
        full_text = " ".join(str(p) for p in text_parts).lower()

        for kw in keywords:
            if kw.lower() in full_text:
                return True
        return False

    def _match_kill_triggers(self, triggers, keywords):
        """Match kill triggers against keywords.

        Args:
            triggers: List of kill trigger dicts or strings.
            keywords: List of keywords to search for.

        Returns:
            List of matching trigger entries.
        """
        matched = []
        for trigger in triggers:
            if isinstance(trigger, dict):
                trigger_text = f"{trigger.get('trigger', '')} {trigger.get('description', '')}"
            else:
                trigger_text = str(trigger)

            trigger_lower = trigger_text.lower()
            for kw in keywords:
                if kw.lower() in trigger_lower:
                    matched.append(trigger)
                    break
        return matched

    def _cross_layer_search(self, gov, keywords):
        """Search across all governance layers for keyword matches.

        Used as a fallback when the primary match type doesn't find
        coverage. This can identify partial coverage in unexpected layers.

        Args:
            gov: The governance config dict.
            keywords: Keywords to search for.

        Returns:
            List of (layer_name, rule_description) tuples.
        """
        results = []

        # Check Layer A
        layer_a = gov.get("layer_a", {})
        all_a_rules = layer_a.get("rules", []) + layer_a.get("universal", [])
        for rule in all_a_rules:
            if not isinstance(rule, str):
                continue
            for kw in keywords:
                if kw.lower() in rule.lower():
                    results.append(("layer_a", rule))
                    break

        # Check Layer B
        layer_b = gov.get("layer_b", {})
        for rule in layer_b.get("rules", []):
            if not isinstance(rule, dict):
                continue
            rule_text = f"{rule.get('action', '')} {rule.get('description', '')}"
            for kw in keywords:
                if kw.lower() in rule_text.lower():
                    results.append(("layer_b", self._format_layer_b_rule(rule)))
                    break

        # Check kill triggers
        for trigger in gov.get("kill_triggers", []):
            if isinstance(trigger, dict):
                trigger_text = f"{trigger.get('trigger', '')} {trigger.get('description', '')}"
            else:
                trigger_text = str(trigger)
            for kw in keywords:
                if kw.lower() in trigger_text.lower():
                    results.append(("kill_triggers", self._format_trigger(trigger)))
                    break

        return results

    def _determine_status(self, matches, coverage, expected_type):
        """Determine coverage status based on matches.

        Args:
            matches: List of matched rules/descriptions.
            coverage: The governance layer that matched (or None).
            expected_type: The match type expected by the control.

        Returns:
            "covered" if matches found in expected layer,
            "partial" if matches found in a different layer,
            "gap" if no matches found.
        """
        if not matches or coverage is None:
            return "gap"

        # If the coverage matches the expected type, it's fully covered
        if coverage == expected_type:
            return "covered"

        # Chain type is always covered if present (it's a structural feature)
        if expected_type == "chain" and coverage == "chain":
            return "covered"

        # If coverage was found but in a different layer, it's partial
        return "partial"

    def _format_layer_b_rule(self, rule):
        """Format a Layer B rule dict as a readable string.

        Args:
            rule: Layer B rule dict with action/threshold/requires.

        Returns:
            Formatted string.
        """
        action = rule.get("action", "unknown")
        requires = rule.get("requires", "unknown")
        threshold = rule.get("threshold", "")
        if threshold:
            return f"{action} (threshold: {threshold}) requires {requires}"
        return f"{action} requires {requires}"

    def _format_trigger(self, trigger):
        """Format a kill trigger as a readable string.

        Args:
            trigger: Kill trigger dict or string.

        Returns:
            Formatted string.
        """
        if isinstance(trigger, dict):
            name = trigger.get("trigger", "unknown")
            desc = trigger.get("description", "")
            return f"Kill trigger: {name} — {desc}" if desc else f"Kill trigger: {name}"
        return f"Kill trigger: {trigger}"

    def _build_notes(self, coverage, rules, control):
        """Build explanatory notes for a control mapping.

        Args:
            coverage: The governance layer providing coverage.
            rules: List of matched rule strings.
            control: The control dict from the template.

        Returns:
            Human-readable notes string.
        """
        if not coverage:
            return f"No Charter governance rule currently covers this control. {control.get('recommendation', '')}"

        layer_names = {
            "layer_a": "Layer A (hard constraints)",
            "layer_b": "Layer B (gradient decisions)",
            "layer_c": "Layer C (self-audit)",
            "kill_triggers": "kill triggers",
            "chain": "hash chain audit trail",
        }
        layer_label = layer_names.get(coverage, coverage)

        if len(rules) == 1:
            return f"Covered by {layer_label}: {rules[0]}"
        return f"Covered by {layer_label} with {len(rules)} matching rule(s)"

    def _format_markdown(self, result):
        """Format mapping result as a Markdown compliance report.

        Args:
            result: The mapping result dict from map_to_standard().

        Returns:
            Markdown-formatted report string.
        """
        lines = []
        standard_display = result["standard_name"]
        lines.append(f"# Charter Compliance Report -- {standard_display}")
        lines.append("")
        lines.append(f"**Generated:** {result['timestamp']}")
        lines.append(
            f"**Coverage:** {result['covered_controls']}/{result['total_controls']} "
            f"controls ({result['coverage_percentage']}%)"
        )
        if result["partial_controls"] > 0:
            lines.append(f"**Partial:** {result['partial_controls']} control(s) with indirect coverage")
        lines.append(f"**Gaps:** {result['gap_controls']} control(s) require attention")
        lines.append("")

        # Covered Controls
        covered = [m for m in result["mappings"] if m["status"] == "covered"]
        if covered:
            lines.append("## Covered Controls")
            lines.append("")
            lines.append("| Control | Name | Charter Layer | Rules |")
            lines.append("|---------|------|---------------|-------|")
            for m in covered:
                layer = m["charter_coverage"] or ""
                rules_str = "; ".join(m["charter_rules"][:2])
                if len(m["charter_rules"]) > 2:
                    rules_str += f" (+{len(m['charter_rules']) - 2} more)"
                lines.append(f"| {m['control_id']} | {m['control_name']} | {layer} | {rules_str} |")
            lines.append("")

        # Partial Controls
        partial = [m for m in result["mappings"] if m["status"] == "partial"]
        if partial:
            lines.append("## Partial Coverage")
            lines.append("")
            lines.append("| Control | Name | Charter Layer | Notes |")
            lines.append("|---------|------|---------------|-------|")
            for m in partial:
                layer = m["charter_coverage"] or ""
                lines.append(f"| {m['control_id']} | {m['control_name']} | {layer} | {m['notes']} |")
            lines.append("")

        # Gaps
        gaps = [m for m in result["mappings"] if m["status"] == "gap"]
        if gaps:
            lines.append("## Gaps")
            lines.append("")
            lines.append("| Control | Name | Description | Recommendation |")
            lines.append("|---------|------|-------------|----------------|")
            for m in gaps:
                lines.append(
                    f"| {m['control_id']} | {m['control_name']} | "
                    f"{m['description']} | {m['recommendation']} |"
                )
            lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        lines.append(
            f"Charter governance provides **{result['coverage_percentage']}%** coverage "
            f"of {standard_display} controls."
        )
        if gaps:
            lines.append(
                f"**{len(gaps)} gap(s)** remain. Review the recommendations above "
                f"to close compliance gaps."
            )
        if partial:
            lines.append(
                f"**{len(partial)} control(s)** have indirect coverage through "
                f"related governance rules."
            )
        if not gaps and not partial:
            lines.append("All controls are fully covered by existing governance rules.")
        lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Standalone helpers
# ---------------------------------------------------------------------------

def get_available_standards():
    """List available compliance standard template names.

    Scans the templates/compliance/ directory for YAML files and
    returns their names (without extension).

    Returns:
        List of standard name strings (e.g., ["ferpa", "hipaa", "sox"]).
    """
    if not os.path.isdir(TEMPLATES_DIR):
        return []
    standards = []
    for fname in sorted(os.listdir(TEMPLATES_DIR)):
        if fname.endswith((".yaml", ".yml")):
            standards.append(os.path.splitext(fname)[0])
    return standards


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_compliance(args):
    """CLI entry point for charter compliance commands.

    Dispatches based on args.action:
        map       - Run map_to_standard, print summary
        report    - Run generate_report, print full report
        gap       - Run gap_analysis, print gaps only
        standards - List available compliance standards

    Args:
        args: argparse.Namespace with action, standard, format, config.
    """
    if args.action == "standards":
        standards = get_available_standards()
        if not standards:
            print("No compliance templates found.")
            print(f"Expected location: {TEMPLATES_DIR}")
            return
        print("Available compliance standards:")
        for s in standards:
            # Load each to get the display name
            path = os.path.join(TEMPLATES_DIR, f"{s}.yaml")
            with open(path) as f:
                data = yaml.safe_load(f)
            name = data.get("name", s)
            desc = data.get("description", "")
            print(f"  {s:12s}  {name}")
            if desc:
                print(f"  {' ' * 12}  {desc}")
        return

    # All other actions require a standard
    standard = getattr(args, "standard", None)
    if not standard:
        print("Error: --standard is required. Use 'charter compliance standards' to list options.",
              file=sys.stderr)
        sys.exit(1)

    config_path = getattr(args, "config", None)
    config = load_config(config_path)
    if not config:
        print("No charter.yaml found. Run 'charter init' first.", file=sys.stderr)
        sys.exit(1)

    mapper = ComplianceMapper(config=config, standard=standard)
    if not mapper.standard_data:
        available = get_available_standards()
        print(f"Error: Unknown standard '{standard}'.", file=sys.stderr)
        if available:
            print(f"Available: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)

    if args.action == "map":
        result = mapper.map_to_standard()
        if not result:
            print("Error: Could not generate compliance mapping.", file=sys.stderr)
            sys.exit(1)

        print(f"Charter Compliance Mapping -- {result['standard_name']}")
        print(f"  Total controls:   {result['total_controls']}")
        print(f"  Covered:          {result['covered_controls']}")
        print(f"  Partial:          {result['partial_controls']}")
        print(f"  Gaps:             {result['gap_controls']}")
        print(f"  Coverage:         {result['coverage_percentage']}%")
        print()

        # Brief listing
        for m in result["mappings"]:
            status_icon = {"covered": "[OK]", "partial": "[~~]", "gap": "[  ]"}.get(
                m["status"], "[??]"
            )
            print(f"  {status_icon} {m['control_id']:20s} {m['control_name']}")

    elif args.action == "report":
        fmt = getattr(args, "format", "markdown") or "markdown"
        report = mapper.generate_report(format=fmt)
        if not report:
            print("Error: Could not generate compliance report.", file=sys.stderr)
            sys.exit(1)

        output_path = getattr(args, "output", None)
        if output_path:
            with open(output_path, "w") as f:
                f.write(report)
            print(f"Report saved to: {os.path.abspath(output_path)}")
        else:
            print(report)

    elif args.action == "gap":
        gaps = mapper.gap_analysis()
        if not gaps:
            print(f"No compliance gaps found for {standard}. Full coverage achieved.")
            return

        print(f"Charter Compliance Gaps -- {standard.upper()}")
        print(f"  {len(gaps)} control(s) require attention")
        print()
        for m in gaps:
            status_label = "GAP" if m["status"] == "gap" else "PARTIAL"
            print(f"  [{status_label}] {m['control_id']}: {m['control_name']}")
            print(f"         {m['description']}")
            if m["recommendation"]:
                print(f"         Recommendation: {m['recommendation']}")
            print()
