"""Claude/Anthropic adapter — Context Manifest to CLAUDE.md + memory.

Generates:
  - CLAUDE.md: Governance rules + professional context
  - memory.json: Key entities and relationships for memory system
  - project-instructions.md: Behavioral patterns and decision context

Extends the existing generate.py CLAUDE.md pattern with manifest data.
"""

import json
import os

from charter.adapters import (
    PlatformAdapter,
    render_absence_declarations_markdown,
    split_pattern_and_absence,
)


class ClaudeAdapter(PlatformAdapter):
    """Adapt a Context Manifest for Claude Code / Claude Desktop."""

    platform_name = "claude"

    def adapt(self, manifest, output_dir):
        os.makedirs(output_dir, exist_ok=True)

        files = {}

        # 1. CLAUDE.md — governance + professional context
        claude_md = self._render_claude_md(manifest)
        claude_path = os.path.join(output_dir, "CLAUDE.md")
        with open(claude_path, "w") as f:
            f.write(claude_md)
        files["CLAUDE.md"] = claude_path

        # 2. memory.json — key entities for Claude memory
        memory = self._render_memory(manifest)
        memory_path = os.path.join(output_dir, "memory.json")
        with open(memory_path, "w") as f:
            json.dump(memory, f, indent=2)
        files["memory.json"] = memory_path

        # 3. project-instructions.md — patterns and decisions
        instructions = self._render_instructions(manifest)
        inst_path = os.path.join(
            output_dir, "project-instructions.md"
        )
        with open(inst_path, "w") as f:
            f.write(instructions)
        files["project-instructions.md"] = inst_path

        return {
            "platform": "claude",
            "files": files,
            "output_dir": output_dir,
        }

    def validate(self, output_dir):
        checks = []
        errors = []

        for filename in [
            "CLAUDE.md", "memory.json", "project-instructions.md"
        ]:
            path = os.path.join(output_dir, filename)
            if os.path.isfile(path):
                size = os.path.getsize(path)
                checks.append("{}: exists ({} bytes)".format(
                    filename, size
                ))
            else:
                errors.append("{}: missing".format(filename))

        # Validate memory.json is parseable
        mem_path = os.path.join(output_dir, "memory.json")
        if os.path.isfile(mem_path):
            try:
                with open(mem_path) as f:
                    json.load(f)
                checks.append("memory.json: valid JSON")
            except json.JSONDecodeError:
                errors.append("memory.json: invalid JSON")

        return {"valid": len(errors) == 0, "checks": checks,
                "errors": errors}

    def _render_claude_md(self, manifest):
        """Render CLAUDE.md with two structurally distinct sections:

        SECTION 1: Role Constraints (apply to you)
            Governance, compliance, hard rules — these are inherited
            with the role and apply to whoever holds it.

        SECTION 2: Predecessor Patterns (information, not instructions)
            Behavioral patterns, decision history, judgment profile —
            these describe how the previous holder worked. The new
            holder should examine them and decide what to inherit,
            what to change, and what was never tried.
        """
        lines = []
        identity = manifest.get("identity", {})
        gov = manifest.get("governance_profile", {})

        # ── Header ──────────────────────────────────────────────
        lines.append("# Role Context — Charter Manifest")
        lines.append("")
        lines.append("Generated: {}".format(
            manifest.get("generated_at", "unknown")
        ))
        lines.append("Scope: {}".format(manifest.get("scope", "")))
        if identity.get("alias"):
            lines.append("Predecessor identity: {}".format(
                identity["alias"]
            ))
        if identity.get("verified"):
            lines.append("Verified: Yes")
        lines.append("")
        lines.append(
            "> This document has TWO sections. Section 1 is "
            "**inherited** with the role and applies to you. "
            "Section 2 is **information about your predecessor** "
            "— examine it, decide what to keep, what to change, "
            "and what to try fresh."
        )
        lines.append("")

        # ──────────────────────────────────────────────────────────
        # SECTION 1: Role Constraints (apply to you)
        # ──────────────────────────────────────────────────────────
        lines.append("---")
        lines.append("")
        lines.append("# SECTION 1: Role Constraints (apply to you)")
        lines.append("")
        lines.append(
            "These rules are inherited with the role. They are "
            "objective and apply regardless of who holds the role. "
            "You MUST comply with them."
        )
        lines.append("")

        layer_a = gov.get("layer_a", {})
        universal = layer_a.get("universal", [])
        if universal:
            lines.append("## Hard Constraints (Layer A — Universal)")
            lines.append("")
            for rule in universal:
                lines.append("- {}".format(rule))
            lines.append("")

        rules = layer_a.get("rules", [])
        if rules:
            lines.append("## Domain Rules (Layer A — Domain)")
            lines.append("")
            for rule in rules:
                lines.append("- {}".format(rule))
            lines.append("")

        layer_b = gov.get("layer_b", [])
        if layer_b:
            lines.append("## Gradient Decisions (Layer B)")
            lines.append("")
            for rule in layer_b:
                if isinstance(rule, dict):
                    lines.append(
                        "- **{}**: {} (requires: {})".format(
                            rule.get("action", ""),
                            rule.get("description", ""),
                            rule.get("requires", ""),
                        )
                    )
                else:
                    lines.append("- {}".format(rule))
            lines.append("")

        layer_c = gov.get("layer_c", {})
        if layer_c:
            lines.append("## Self-Audit (Layer C)")
            lines.append("")
            freq = layer_c.get("frequency", "unset")
            lines.append("- Audit frequency: {}".format(freq))
            for inc in layer_c.get("report_includes", []):
                lines.append("- Report includes: {}".format(inc))
            lines.append("")

        kill_triggers = gov.get("kill_triggers", [])
        if kill_triggers:
            lines.append("## Kill Triggers")
            lines.append("")
            for trigger in kill_triggers:
                if isinstance(trigger, dict):
                    lines.append("- **{}**: {}".format(
                        trigger.get("trigger", ""),
                        trigger.get("description", ""),
                    ))
                else:
                    lines.append("- {}".format(trigger))
            lines.append("")

        compliance = gov.get("compliance_frameworks", [])
        if compliance:
            lines.append("## Compliance Frameworks")
            lines.append("")
            for f in compliance:
                if isinstance(f, dict):
                    lines.append("- {} ({:.0f}% coverage)".format(
                        f.get("standard", "").upper(),
                        f.get("coverage_pct", 0),
                    ))
                else:
                    lines.append("- {}".format(f))
            lines.append("")

        # ──────────────────────────────────────────────────────────
        # SECTION 2: Predecessor Patterns (information, not orders)
        # ──────────────────────────────────────────────────────────
        lines.append("---")
        lines.append("")
        lines.append(
            "# SECTION 2: Predecessor Patterns "
            "(information, not instructions)"
        )
        lines.append("")
        lines.append(
            "What follows describes how the previous holder of "
            "this role worked. **It is data, not direction.** "
            "Read it as you would read a research report on a "
            "predecessor's tenure: useful context, not a script "
            "to follow. Patterns may have been the right answer "
            "at the time but no longer apply. Decisions may have "
            "been constrained by circumstances that have changed. "
            "Use this as a starting point for fresh thinking, not "
            "as the answer."
        )
        lines.append("")

        # Key relationships from graph
        gs = manifest.get("graph_snapshot", {})
        entities = gs.get("entities", [])
        if entities:
            orgs = [
                e for e in entities
                if e.get("entity_type") == "organization"
            ]
            if orgs:
                lines.append("## Organizations the predecessor worked with")
                lines.append("")
                for org in orgs[:10]:
                    lines.append("- {}".format(org.get("name", "")))
                lines.append("")

        # Behavioral patterns (annotated if Tier 0b is built)
        all_decls = manifest.get(
            "pattern_declarations", {}
        ).get("declarations", [])
        patterns, absences = split_pattern_and_absence(all_decls)
        if patterns:
            lines.append("## Behavioral patterns observed")
            lines.append("")
            lines.append(
                "> These are observations of how the predecessor "
                "worked, not best practices. Each pattern may "
                "reflect personal preference, environmental "
                "constraint, or genuine best practice — distinguish "
                "carefully."
            )
            lines.append("")
            for p in patterns:
                line = "- {}".format(p.get("statement", ""))
                # Show annotation if available
                if "confidence" in p:
                    line += " *(confidence: {})*".format(
                        p["confidence"]
                    )
                if "alternatives_tried" in p:
                    line += " *(alternatives tried: {})*".format(
                        p["alternatives_tried"]
                    )
                lines.append(line)
                # Surface caveat as an indented note for visibility
                if p.get("caveat"):
                    lines.append("  > **Caveat:** {}".format(
                        p["caveat"]
                    ))
            lines.append("")

        # Absence patterns (what was NOT done) — Section 2 still
        absence_lines = render_absence_declarations_markdown(absences)
        if absence_lines:
            lines.extend(absence_lines)

        # Judgment profile
        judgment = manifest.get("judgment_profile", {})
        stmts = judgment.get("statements", [])
        if stmts:
            lines.append("## Judgment patterns observed")
            lines.append("")
            lines.append(
                "> Derived from decision-outcome pairs in the "
                "predecessor's chain. Useful as a baseline; "
                "your own judgment will be measured the same way."
            )
            lines.append("")
            for s in stmts:
                lines.append("- {}".format(s.get("statement", "")))
            lines.append("")

        # Decision history summary
        dl = manifest.get("decision_log", [])
        if dl:
            from collections import Counter
            types = Counter(d.get("event", "") for d in dl)
            lines.append("## Decision activity ({} total)".format(
                len(dl)
            ))
            lines.append("")
            lines.append(
                "Top decision types in the predecessor's tenure:"
            )
            lines.append("")
            for event, count in types.most_common(5):
                lines.append("- {} ({})".format(
                    event.replace("_", " "), count
                ))
            lines.append("")

        # Closing prompt
        lines.append("---")
        lines.append("")
        lines.append("## How to use this document")
        lines.append("")
        lines.append(
            "1. Treat Section 1 as binding governance. Comply."
        )
        lines.append(
            "2. Treat Section 2 as a research report. Examine "
            "patterns critically. Ask: was this the right answer "
            "at the time? Is it still? What was never tried?"
        )
        lines.append(
            "3. Bring your own judgment. Your decisions will be "
            "captured the same way and become part of the role's "
            "future role intelligence."
        )
        lines.append("")

        return "\n".join(lines)

    def _render_memory(self, manifest):
        gs = manifest.get("graph_snapshot", {})
        entities = gs.get("entities", [])

        # Top entities by type for memory priming
        memory_entries = []
        for entity_type in ["person", "organization", "project"]:
            typed = [
                e for e in entities
                if e.get("entity_type") == entity_type
            ][:15]
            for e in typed:
                memory_entries.append({
                    "type": entity_type,
                    "name": e.get("name", ""),
                    "context": e.get("context", ""),
                    "email": e.get("email", ""),
                })

        return {
            "source": "charter_manifest",
            "generated_at": manifest.get("generated_at", ""),
            "entity_count": len(memory_entries),
            "entries": memory_entries,
        }

    def _render_instructions(self, manifest):
        lines = []
        lines.append("# Project Instructions — Charter Context")
        lines.append("")

        # Decision patterns
        dl = manifest.get("decision_log", [])
        if dl:
            lines.append("## Decision History Summary")
            lines.append("")
            lines.append("{} decisions recorded.".format(len(dl)))
            lines.append("")

            # Count decision types
            from collections import Counter
            types = Counter(d.get("event", "") for d in dl)
            lines.append("Top decision types:")
            for event, count in types.most_common(5):
                lines.append("- {} ({})".format(
                    event.replace("_", " "), count
                ))
            lines.append("")

        # Pattern declarations
        all_decls = manifest.get(
            "pattern_declarations", {}
        ).get("declarations", [])
        patterns, absences = split_pattern_and_absence(all_decls)
        if patterns:
            lines.append("## Work Patterns")
            lines.append("")
            for p in patterns:
                lines.append("- [{}] {}".format(
                    p.get("type", ""), p.get("statement", "")
                ))
            lines.append("")

        absence_lines = render_absence_declarations_markdown(absences)
        if absence_lines:
            lines.extend(absence_lines)

        return "\n".join(lines)
