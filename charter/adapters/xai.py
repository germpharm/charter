"""xAI/Grok adapter — Context Manifest to system prompt + priming.

Generates:
  - system-prompt.txt: Grok system prompt with governance + context
  - priming.json: First 3-5 messages to establish context
  - api-context.json: Structured context for xAI API calls
"""

import json
import os

from charter.adapters import (
    PlatformAdapter,
    group_absences_by_subtype,
    split_pattern_and_absence,
)

_ABSENCE_SUBTYPE_LABELS = {
    "missing": "missing-event",
    "underused": "underused-event",
    "relationship_silence": "relationship-silence",
    "unused_tool": "unused-tool",
}


class XAIAdapter(PlatformAdapter):
    """Adapt a Context Manifest for xAI Grok (API, voice)."""

    platform_name = "xai"

    def adapt(self, manifest, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        files = {}

        # 1. System prompt
        prompt = self._render_system_prompt(manifest)
        prompt_path = os.path.join(output_dir, "system-prompt.txt")
        with open(prompt_path, "w") as f:
            f.write(prompt)
        files["system-prompt.txt"] = prompt_path

        # 2. Priming messages
        priming = self._render_priming(manifest)
        prime_path = os.path.join(output_dir, "priming.json")
        with open(prime_path, "w") as f:
            json.dump(priming, f, indent=2)
        files["priming.json"] = prime_path

        # 3. API context
        api_ctx = self._render_api_context(manifest)
        api_path = os.path.join(output_dir, "api-context.json")
        with open(api_path, "w") as f:
            json.dump(api_ctx, f, indent=2)
        files["api-context.json"] = api_path

        return {
            "platform": "xai",
            "files": files,
            "output_dir": output_dir,
        }

    def validate(self, output_dir):
        checks = []
        errors = []
        for fn in ["system-prompt.txt", "priming.json",
                   "api-context.json"]:
            path = os.path.join(output_dir, fn)
            if os.path.isfile(path):
                checks.append("{}: exists".format(fn))
            else:
                errors.append("{}: missing".format(fn))
        return {"valid": len(errors) == 0, "checks": checks,
                "errors": errors}

    def _render_system_prompt(self, manifest):
        """Render system prompt with two distinct sections:
        1. Inherited role constraints (binding)
        2. Predecessor information (research, not orders)
        """
        parts = []
        gov = manifest.get("governance_profile", {})

        parts.append(
            "You are assisting the holder of a role whose context "
            "has been loaded from a Charter manifest."
        )
        parts.append("")

        # ── SECTION 1: Inherited (binding) ──────────────────
        parts.append("=== SECTION 1: ROLE CONSTRAINTS (BINDING) ===")
        parts.append("")

        domain = gov.get("domain", "general")
        parts.append("Role domain: {}".format(domain))
        parts.append("")

        rules = gov.get("layer_a", {}).get("universal", [])
        rules += gov.get("layer_a", {}).get("rules", [])
        if rules:
            parts.append(
                "These constraints are inherited with the role "
                "and apply to whoever holds it. You MUST comply."
            )
            for rule in rules:
                parts.append("- {}".format(rule))
            parts.append("")

        # ── SECTION 2: Predecessor (informational) ───────────
        parts.append(
            "=== SECTION 2: PREDECESSOR PATTERNS "
            "(INFORMATION, NOT INSTRUCTIONS) ==="
        )
        parts.append("")
        parts.append(
            "What follows describes how the previous holder of "
            "this role worked. Treat it as a research report, "
            "not as a script. The current holder may make "
            "different choices and that is expected."
        )
        parts.append("")

        all_decls = manifest.get(
            "pattern_declarations", {}
        ).get("declarations", [])
        patterns, absences = split_pattern_and_absence(all_decls)
        if patterns:
            parts.append("Predecessor's observed work patterns:")
            for p in patterns[:5]:
                parts.append("- {}".format(p.get("statement", "")))
            parts.append("")

        if absences:
            parts.append(
                "Predecessor ABSENCES (what was NOT done — "
                "informational only, NOT instructions):"
            )
            for subtype, items in group_absences_by_subtype(absences):
                label = _ABSENCE_SUBTYPE_LABELS.get(subtype, subtype)
                parts.append("[{}] ({})".format(label, len(items)))
                for d in items[:5]:
                    parts.append(
                        "- ({}) {}".format(
                            d.get("confidence", "?"),
                            d.get("statement", ""),
                        )
                    )
                    if d.get("caveat"):
                        parts.append(
                            "  caveat: {}".format(d["caveat"])
                        )
            parts.append("")

        gs = manifest.get("graph_snapshot", {})
        orgs = [
            e for e in gs.get("entities", [])
            if e.get("entity_type") == "organization"
        ][:5]
        if orgs:
            parts.append("Organizations the predecessor worked with:")
            for o in orgs:
                parts.append("- {}".format(o.get("name", "")))

        return "\n".join(parts)

    def _render_priming(self, manifest):
        """Generate priming messages to establish context fast."""
        messages = []
        identity = manifest.get("identity", {})
        gs = manifest.get("graph_snapshot", {}).get("stats", {})
        dl = manifest.get("decision_log", [])

        # Message 1: Identity and scope
        messages.append({
            "role": "user",
            "content": (
                "I'm {}. I work in {}. I have a Charter "
                "governance profile with {} recorded decisions, "
                "a network of {} entities, and {} tracked "
                "interactions. I'm bringing my professional "
                "context from a previous system.".format(
                    identity.get("alias", "a professional"),
                    manifest.get(
                        "governance_profile", {}
                    ).get("domain", "general"),
                    len(dl),
                    gs.get("entity_count", 0),
                    gs.get("interaction_count", 0),
                )
            ),
        })

        # Message 2: Key patterns
        all_decls = manifest.get(
            "pattern_declarations", {}
        ).get("declarations", [])
        patterns, absences = split_pattern_and_absence(all_decls)
        if patterns:
            pattern_text = " ".join(
                p.get("statement", "") for p in patterns[:3]
            )
            messages.append({
                "role": "user",
                "content": (
                    "Key things about how I work: {}".format(
                        pattern_text
                    )
                ),
            })
        if absences:
            absence_text = " ".join(
                d.get("statement", "") for d in absences[:3]
            )
            messages.append({
                "role": "user",
                "content": (
                    "Things the previous holder of this role did "
                    "NOT do (informational, not instructions): "
                    "{}".format(absence_text)
                ),
            })

        # Message 3: Governance constraints
        gov = manifest.get("governance_profile", {})
        rules = gov.get("layer_a", {}).get("rules", [])
        if rules:
            messages.append({
                "role": "user",
                "content": (
                    "Important constraints for our work: {}".format(
                        "; ".join(str(r)[:100] for r in rules[:5])
                    )
                ),
            })

        return {"messages": messages, "count": len(messages)}

    def _render_api_context(self, manifest):
        """Structured context for xAI API calls."""
        return {
            "identity": manifest.get("identity", {}),
            "domain": manifest.get(
                "governance_profile", {}
            ).get("domain", "general"),
            "entity_count": manifest.get(
                "graph_snapshot", {}
            ).get("stats", {}).get("entity_count", 0),
            "decision_count": len(
                manifest.get("decision_log", [])
            ),
            "constraints": manifest.get(
                "governance_profile", {}
            ).get("layer_a", {}).get("rules", []),
            "patterns": [
                p.get("statement", "")
                for p in split_pattern_and_absence(
                    manifest.get(
                        "pattern_declarations", {}
                    ).get("declarations", [])
                )[0][:5]
            ],
            "absences": [
                {
                    "subtype": d.get("subtype", "absence"),
                    "confidence": d.get("confidence", "?"),
                    "statement": d.get("statement", ""),
                    "caveat": d.get("caveat", ""),
                }
                for d in split_pattern_and_absence(
                    manifest.get(
                        "pattern_declarations", {}
                    ).get("declarations", [])
                )[1]
            ],
        }
