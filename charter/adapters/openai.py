"""OpenAI/GPT adapter — Context Manifest to custom instructions + memory.

Generates:
  - custom-instructions.txt: GPT custom instructions from governance + patterns
  - memory-entries.json: Memory entries for GPT's memory feature
  - project-context.md: Decision history and relationship context
"""

import json
import os

from charter.adapters import (
    PlatformAdapter,
    render_absence_declarations_markdown,
    split_pattern_and_absence,
)


class OpenAIAdapter(PlatformAdapter):
    """Adapt a Context Manifest for OpenAI GPT (ChatGPT, API)."""

    platform_name = "openai"

    def adapt(self, manifest, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        files = {}

        # 1. Custom instructions (1500 char limit for "About me")
        instructions = self._render_instructions(manifest)
        inst_path = os.path.join(
            output_dir, "custom-instructions.txt"
        )
        with open(inst_path, "w") as f:
            f.write(instructions)
        files["custom-instructions.txt"] = inst_path

        # 2. Memory entries
        memory = self._render_memory(manifest)
        mem_path = os.path.join(output_dir, "memory-entries.json")
        with open(mem_path, "w") as f:
            json.dump(memory, f, indent=2)
        files["memory-entries.json"] = mem_path

        # 3. Project context
        context = self._render_context(manifest)
        ctx_path = os.path.join(output_dir, "project-context.md")
        with open(ctx_path, "w") as f:
            f.write(context)
        files["project-context.md"] = ctx_path

        return {
            "platform": "openai",
            "files": files,
            "output_dir": output_dir,
        }

    def validate(self, output_dir):
        checks = []
        errors = []
        for fn in ["custom-instructions.txt",
                   "memory-entries.json", "project-context.md"]:
            path = os.path.join(output_dir, fn)
            if os.path.isfile(path):
                checks.append("{}: exists".format(fn))
            else:
                errors.append("{}: missing".format(fn))
        return {"valid": len(errors) == 0, "checks": checks,
                "errors": errors}

    def _render_instructions(self, manifest):
        """Render custom instructions with two distinct parts:
        1. Inherited role constraints (binding)
        2. Predecessor patterns (informational)
        """
        parts = []
        gov = manifest.get("governance_profile", {})

        # Section 1: Inherited constraints (binding)
        domain = gov.get("domain", "")
        if domain and domain != "general":
            parts.append("Role domain: {}.".format(domain))

        rules = gov.get("layer_a", {}).get("rules", [])
        if rules:
            parts.append(
                "INHERITED RULES (must comply): " + "; ".join(
                    str(r)[:80] for r in rules[:5]
                )
            )

        # Section 2: Predecessor patterns (informational)
        all_decls = manifest.get(
            "pattern_declarations", {}
        ).get("declarations", [])
        patterns, absences = split_pattern_and_absence(all_decls)
        if patterns:
            parts.append(
                "PREDECESSOR PATTERNS (information, not "
                "instructions; examine and decide what to "
                "inherit): " + "; ".join(
                    p.get("statement", "")[:80]
                    for p in patterns[:3]
                )
            )
        if absences:
            # Cap at the top 3 absences by stable subtype order so
            # the 1500-char custom-instructions budget is preserved.
            top = absences[:3]
            parts.append(
                "PREDECESSOR ABSENCES (information, not "
                "instructions; the predecessor did NOT do these "
                "and the new holder may want to): " + "; ".join(
                    "[{}/{}] {}".format(
                        d.get("subtype", "absence"),
                        d.get("confidence", "?"),
                        d.get("statement", "")[:80],
                    )
                    for d in top
                )
            )

        return "\n".join(parts)

    def _render_memory(self, manifest):
        entries = []
        gs = manifest.get("graph_snapshot", {})

        # Key people
        people = [
            e for e in gs.get("entities", [])
            if e.get("entity_type") == "person"
        ][:20]
        for p in people:
            entries.append({
                "content": "Know {} ({})".format(
                    p.get("name", ""),
                    p.get("context", ""),
                ),
            })

        # Key orgs
        orgs = [
            e for e in gs.get("entities", [])
            if e.get("entity_type") == "organization"
        ][:10]
        for o in orgs:
            entries.append({
                "content": "Work with {}".format(
                    o.get("name", "")
                ),
            })

        # Patterns as memories
        all_decls = manifest.get(
            "pattern_declarations", {}
        ).get("declarations", [])
        patterns, absences = split_pattern_and_absence(all_decls)
        for p in patterns[:5]:
            entries.append({
                "content": p.get("statement", ""),
            })
        for d in absences[:5]:
            entries.append({
                "content": "ABSENCE [{}/{}]: {}".format(
                    d.get("subtype", "absence"),
                    d.get("confidence", "?"),
                    d.get("statement", ""),
                ),
                "caveat": d.get("caveat", ""),
            })

        return {"entries": entries, "count": len(entries)}

    def _render_context(self, manifest):
        lines = []
        lines.append("# Professional Context")
        lines.append("")

        dl = manifest.get("decision_log", [])
        if dl:
            lines.append("## {} Decisions Recorded".format(len(dl)))
            lines.append("")
            for d in dl[:10]:
                lines.append("- [{}] {} ({})".format(
                    d.get("timestamp", "")[:10],
                    d.get("event", "").replace("_", " "),
                    d.get("actor", ""),
                ))
            if len(dl) > 10:
                lines.append("- ... and {} more".format(
                    len(dl) - 10
                ))
            lines.append("")

        # Absence section (Section 2 — informational)
        all_decls = manifest.get(
            "pattern_declarations", {}
        ).get("declarations", [])
        _, absences = split_pattern_and_absence(all_decls)
        absence_lines = render_absence_declarations_markdown(absences)
        if absence_lines:
            lines.extend(absence_lines)

        gs = manifest.get("graph_snapshot", {}).get("stats", {})
        lines.append("## Network")
        lines.append("")
        lines.append("- {} entities".format(
            gs.get("entity_count", 0)
        ))
        lines.append("- {} relationships".format(
            gs.get("relationship_count", 0)
        ))
        lines.append("- {} interactions".format(
            gs.get("interaction_count", 0)
        ))

        return "\n".join(lines)
