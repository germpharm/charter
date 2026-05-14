"""RAG adapter — Context Manifest to chunked documents for open-source models.

Generates:
  - chunks/ directory: Manifest sections as individual text files for RAG
  - system-prompt.txt: System prompt for any LLM
  - metadata.json: Index of chunks with descriptions
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

_ABSENCE_GROUP_HEADERS = {
    "missing": (
        "Expected events the predecessor never produced."
    ),
    "underused": (
        "Expected events that appear in the chain at a "
        "vanishingly low rate."
    ),
    "relationship_silence": (
        "Entities the predecessor used to engage with regularly "
        "but has gone quiet on."
    ),
    "unused_tool": (
        "Capabilities used by behaviorally-similar peers that "
        "the predecessor never touched."
    ),
}


class RAGAdapter(PlatformAdapter):
    """Adapt a Context Manifest for open-source models via RAG."""

    platform_name = "rag"

    def adapt(self, manifest, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        chunks_dir = os.path.join(output_dir, "chunks")
        os.makedirs(chunks_dir, exist_ok=True)
        files = {}

        # 1. Chunk the manifest into RAG-sized documents
        chunks = self._create_chunks(manifest)
        metadata_entries = []
        for i, chunk in enumerate(chunks):
            filename = "{:03d}_{}.txt".format(i, chunk["id"])
            chunk_path = os.path.join(chunks_dir, filename)
            with open(chunk_path, "w") as f:
                f.write(chunk["content"])
            files[filename] = chunk_path
            metadata_entries.append({
                "index": i,
                "id": chunk["id"],
                "description": chunk["description"],
                "path": filename,
                "size": len(chunk["content"]),
            })

        # 2. System prompt
        prompt = self._render_system_prompt(manifest)
        prompt_path = os.path.join(output_dir, "system-prompt.txt")
        with open(prompt_path, "w") as f:
            f.write(prompt)
        files["system-prompt.txt"] = prompt_path

        # 3. Metadata index
        metadata = {
            "source": "charter_manifest",
            "generated_at": manifest.get("generated_at", ""),
            "chunk_count": len(chunks),
            "chunks": metadata_entries,
        }
        meta_path = os.path.join(output_dir, "metadata.json")
        with open(meta_path, "w") as f:
            json.dump(metadata, f, indent=2)
        files["metadata.json"] = meta_path

        return {
            "platform": "rag",
            "files": files,
            "output_dir": output_dir,
            "chunk_count": len(chunks),
        }

    def validate(self, output_dir):
        checks = []
        errors = []

        for fn in ["system-prompt.txt", "metadata.json"]:
            path = os.path.join(output_dir, fn)
            if os.path.isfile(path):
                checks.append("{}: exists".format(fn))
            else:
                errors.append("{}: missing".format(fn))

        chunks_dir = os.path.join(output_dir, "chunks")
        if os.path.isdir(chunks_dir):
            count = len(os.listdir(chunks_dir))
            checks.append("chunks/: {} files".format(count))
        else:
            errors.append("chunks/: missing")

        return {"valid": len(errors) == 0, "checks": checks,
                "errors": errors}

    def _create_chunks(self, manifest):
        """Create RAG chunks. Each chunk is tagged with its section:
        SECTION 1 = inherited (binding role constraints)
        SECTION 2 = informational (predecessor patterns)

        The section tag is in the chunk ID and content header so any
        downstream RAG retrieval system preserves the distinction.
        """
        chunks = []
        gov = manifest.get("governance_profile", {})

        # ── SECTION 1: Inherited role constraints ──────────────
        lines = [
            "[SECTION 1: ROLE CONSTRAINTS — INHERITED, BINDING]",
            "",
            "These constraints apply to whoever holds this role.",
            "",
            "Domain: {}".format(gov.get("domain", "general")),
            "",
            "Hard constraints (Layer A — Universal):",
        ]
        for rule in gov.get("layer_a", {}).get("universal", []):
            lines.append("- {}".format(rule))
        lines.append("")
        lines.append("Domain rules (Layer A — Domain):")
        for rule in gov.get("layer_a", {}).get("rules", []):
            lines.append("- {}".format(rule))
        chunks.append({
            "id": "s1_role_constraints",
            "description": (
                "SECTION 1: Inherited role constraints "
                "(governance rules that apply to whoever "
                "holds the role)"
            ),
            "content": "\n".join(lines),
        })

        # Layer B as separate chunk if present
        layer_b = gov.get("layer_b", [])
        if layer_b:
            lines = [
                "[SECTION 1: ROLE CONSTRAINTS — INHERITED, BINDING]",
                "",
                "Gradient decisions (Layer B — require approval):",
            ]
            for rule in layer_b:
                if isinstance(rule, dict):
                    lines.append(
                        "- {}: {} (requires: {})".format(
                            rule.get("action", ""),
                            rule.get("description", ""),
                            rule.get("requires", ""),
                        )
                    )
                else:
                    lines.append("- {}".format(rule))
            chunks.append({
                "id": "s1_gradient_decisions",
                "description": (
                    "SECTION 1: Layer B gradient decisions "
                    "requiring human approval"
                ),
                "content": "\n".join(lines),
            })

        # ── SECTION 2: Predecessor patterns (informational) ────
        all_decls = manifest.get(
            "pattern_declarations", {}
        ).get("declarations", [])
        patterns, absences = split_pattern_and_absence(all_decls)
        if patterns:
            lines = [
                "[SECTION 2: PREDECESSOR PATTERNS — "
                "INFORMATIONAL, NOT INSTRUCTIONS]",
                "",
                "What follows describes how the previous holder "
                "of this role worked. Treat as research, not as "
                "a script. Patterns may have been right at the "
                "time but may no longer apply.",
                "",
                "Behavioral patterns observed:",
                "",
            ]
            for p in patterns:
                lines.append("- [{}] {}".format(
                    p.get("type", ""),
                    p.get("statement", ""),
                ))
            chunks.append({
                "id": "s2_patterns",
                "description": (
                    "SECTION 2: Predecessor's behavioral "
                    "patterns (information about how the role "
                    "was worked, not how it must be worked)"
                ),
                "content": "\n".join(lines),
            })

        # SECTION 2: Absence declarations — one chunk per detector
        # subtype so RAG retrieval can target a specific gap class.
        for subtype, items in group_absences_by_subtype(absences):
            label = _ABSENCE_SUBTYPE_LABELS.get(subtype, subtype)
            header = _ABSENCE_GROUP_HEADERS.get(subtype, "")
            lines = [
                "[SECTION 2: PREDECESSOR PATTERNS — "
                "INFORMATIONAL, NOT INSTRUCTIONS]",
                "",
                "Predecessor ABSENCES — {} ({}):".format(
                    label, len(items)
                ),
                "",
                header,
                "",
                "These describe what the predecessor did NOT do.",
                "Treat as research questions for the new holder,",
                "not as instructions to fill the gap.",
                "",
            ]
            for d in items:
                lines.append(
                    "- ({}) {}".format(
                        d.get("confidence", "?"),
                        d.get("statement", ""),
                    )
                )
                if d.get("caveat"):
                    lines.append(
                        "  caveat: {}".format(d["caveat"])
                    )
            chunks.append({
                "id": "s2_absence_{}".format(subtype),
                "description": (
                    "SECTION 2: Predecessor absence declarations "
                    "({}) — what was NOT done, with confidence "
                    "and caveats".format(label)
                ),
                "content": "\n".join(lines),
            })

        # SECTION 2: Organizations the predecessor worked with
        gs = manifest.get("graph_snapshot", {})
        orgs = [
            e for e in gs.get("entities", [])
            if e.get("entity_type") == "organization"
        ]
        if orgs:
            lines = [
                "[SECTION 2: PREDECESSOR PATTERNS — INFORMATIONAL]",
                "",
                "Organizations the predecessor worked with:",
                "",
            ]
            for o in orgs:
                lines.append("- {} ({})".format(
                    o.get("name", ""), o.get("context", "")
                ))
            chunks.append({
                "id": "s2_organizations",
                "description": (
                    "SECTION 2: Organizations the predecessor "
                    "interacted with (the new holder may "
                    "interact with different orgs)"
                ),
                "content": "\n".join(lines),
            })

        # SECTION 2: People the predecessor knew (batched)
        people = [
            e for e in gs.get("entities", [])
            if e.get("entity_type") == "person"
        ]
        batch_size = 50
        for i in range(0, len(people), batch_size):
            batch = people[i:i + batch_size]
            lines = [
                "[SECTION 2: PREDECESSOR PATTERNS — INFORMATIONAL]",
                "",
                "Predecessor's contacts (batch {}):".format(
                    i // batch_size + 1
                ),
                "",
            ]
            for p in batch:
                lines.append("- {} ({})".format(
                    p.get("name", ""), p.get("context", "")
                ))
            chunks.append({
                "id": "s2_people_{}".format(i // batch_size + 1),
                "description": (
                    "SECTION 2: Predecessor's professional "
                    "contacts batch {}".format(
                        i // batch_size + 1
                    )
                ),
                "content": "\n".join(lines),
            })

        # SECTION 2: Predecessor's decision activity
        dl = manifest.get("decision_log", [])
        if dl:
            from collections import Counter
            types = Counter(d.get("event", "") for d in dl)
            lines = [
                "[SECTION 2: PREDECESSOR PATTERNS — INFORMATIONAL]",
                "",
                "Predecessor's decision activity ({} total):".format(
                    len(dl)
                ),
                "",
                "Top decision types:",
                "",
            ]
            for event, count in types.most_common(10):
                lines.append("- {} ({})".format(
                    event.replace("_", " "), count
                ))
            chunks.append({
                "id": "s2_decisions",
                "description": (
                    "SECTION 2: Predecessor's decision history "
                    "summary (data, not direction)"
                ),
                "content": "\n".join(lines),
            })

        # SECTION 2: Predecessor's judgment profile
        judgment = manifest.get("judgment_profile", {})
        stmts = judgment.get("statements", [])
        if stmts:
            lines = [
                "[SECTION 2: PREDECESSOR PATTERNS — INFORMATIONAL]",
                "",
                "Predecessor's judgment patterns observed:",
                "",
                "These were derived from decision-outcome pairs",
                "in the predecessor's chain. Use as a baseline,",
                "not a target.",
                "",
            ]
            for s in stmts:
                lines.append("- {}".format(
                    s.get("statement", "")
                ))
            chunks.append({
                "id": "s2_judgment",
                "description": (
                    "SECTION 2: Predecessor's judgment quality "
                    "and patterns from decision-outcome analysis"
                ),
                "content": "\n".join(lines),
            })

        return chunks

    def _render_system_prompt(self, manifest):
        gov = manifest.get("governance_profile", {})

        parts = [
            "You are assisting the holder of a role whose "
            "context has been loaded from a Charter manifest "
            "into your RAG knowledge base.",
            "",
            "Domain: {}.".format(gov.get("domain", "general")),
            "",
            "RAG chunks are tagged with one of two sections:",
            "",
            "[SECTION 1: ROLE CONSTRAINTS — INHERITED, BINDING]",
            "  These are governance rules. Whoever holds this role",
            "  must comply with them. Treat as authoritative.",
            "",
            "[SECTION 2: PREDECESSOR PATTERNS — INFORMATIONAL]",
            "  These describe how the previous holder of the role",
            "  worked. They are data, not direction. The current",
            "  holder may make different choices, and that is",
            "  expected. Patterns from Section 2 may have been",
            "  the right answer at a previous time and may no",
            "  longer apply. Use as research, not as a script.",
            "",
            "When retrieving from chunks, preserve the section",
            "tags and treat the two sections accordingly.",
            "",
            "Inherited constraints (Section 1, summary):",
        ]
        for rule in gov.get("layer_a", {}).get("rules", []):
            parts.append("- {}".format(rule))

        return "\n".join(parts)
