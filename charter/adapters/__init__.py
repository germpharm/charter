"""Platform adapters — translate Context Manifests for specific AI systems.

Each adapter is a stateless transform: manifest dict in, platform-specific
files out. No network calls, no side effects, easy to test.

The manifest is the universal format. Adapters are the disposable layer.
When platforms change their formats, update the adapter. The manifest
(your intelligence layer) stays yours.

Supported platforms:
  - Claude (Anthropic): CLAUDE.md + memory + project instructions
  - OpenAI (GPT): custom instructions + memory entries + project context
  - xAI (Grok): system prompt + conversation priming + API context
  - RAG (open source): chunked documents + system prompt + metadata
"""

from abc import ABC, abstractmethod


class PlatformAdapter(ABC):
    """Base class for platform adapters."""

    platform_name = "unknown"

    @abstractmethod
    def adapt(self, manifest, output_dir):
        """Convert a Context Manifest to platform-specific artifacts.

        Args:
            manifest: The Context Manifest dict.
            output_dir: Directory to write artifacts to.

        Returns:
            dict with file paths and metadata.
        """

    @abstractmethod
    def validate(self, output_dir):
        """Verify generated artifacts are well-formed.

        Args:
            output_dir: Directory containing generated artifacts.

        Returns:
            dict with valid (bool) and checks (list).
        """


_ABSENCE_SUBTYPE_LABELS = {
    "missing": "missing-event",
    "underused": "underused-event",
    "relationship_silence": "relationship-silence",
    "unused_tool": "unused-tool",
}

_ABSENCE_GROUP_HEADERS = {
    "missing": (
        "Expected events the predecessor never produced. The work "
        "may have happened off-chain, been delegated, or never "
        "happened at all."
    ),
    "underused": (
        "Expected events that appear in the chain but at a "
        "vanishingly low rate. Worth checking whether this is a "
        "deliberate trade-off or a blind spot."
    ),
    "relationship_silence": (
        "Entities the predecessor used to engage with regularly "
        "but has gone quiet on. Relationship may have ended "
        "naturally — verify before treating as a follow-up gap."
    ),
    "unused_tool": (
        "Capabilities used by behaviorally-similar peers that the "
        "predecessor never touched. Possible tool blind spot."
    ),
}


def split_pattern_and_absence(declarations):
    """Split a flat declaration list into (positive_patterns, absences)."""
    patterns = []
    absences = []
    for d in declarations or []:
        if d.get("type") == "absence":
            absences.append(d)
        else:
            patterns.append(d)
    return patterns, absences


def group_absences_by_subtype(absences):
    """Group absence declarations by subtype, in stable order."""
    order = ["missing", "underused", "relationship_silence", "unused_tool"]
    by_sub = {k: [] for k in order}
    for d in absences or []:
        sub = d.get("subtype", "missing")
        by_sub.setdefault(sub, []).append(d)
    return [(k, by_sub[k]) for k in by_sub if by_sub[k]]


def render_absence_declarations_markdown(absences):
    """Deterministic markdown renderer for absence declarations.

    Used by adapters that emit markdown (claude, openai project context).
    Returns a list of lines (no trailing newline) so callers can splice
    it into their own document structure.
    """
    if not absences:
        return []
    lines = []
    lines.append(
        "## Absence patterns observed "
        "(what the predecessor did NOT do)"
    )
    lines.append("")
    lines.append(
        "> These are NOT instructions. They surface gaps between "
        "expected and observed activity so the new holder can ask "
        "the right questions. Each absence carries a confidence "
        "level and a caveat — read both before acting on them."
    )
    lines.append("")
    for subtype, items in group_absences_by_subtype(absences):
        label = _ABSENCE_SUBTYPE_LABELS.get(subtype, subtype)
        lines.append("### {} ({})".format(label, len(items)))
        lines.append("")
        header = _ABSENCE_GROUP_HEADERS.get(subtype)
        if header:
            lines.append("> {}".format(header))
            lines.append("")
        for d in items:
            line = "- {}".format(d.get("statement", ""))
            if "confidence" in d:
                line += " *(confidence: {})*".format(d["confidence"])
            lines.append(line)
            if d.get("caveat"):
                lines.append(
                    "  > **Caveat:** {}".format(d["caveat"])
                )
        lines.append("")
    return lines


ADAPTERS = {}


def register_adapter(name, adapter_class):
    """Register a platform adapter."""
    ADAPTERS[name] = adapter_class


def get_adapter(platform):
    """Get an adapter by platform name."""
    if platform not in ADAPTERS:
        available = ", ".join(ADAPTERS.keys())
        raise ValueError(
            "Unknown platform: {}. Available: {}".format(
                platform, available
            )
        )
    return ADAPTERS[platform]()


def list_adapters():
    """List available platform adapters."""
    return list(ADAPTERS.keys())


# Auto-register adapters on import
def _auto_register():
    try:
        from charter.adapters.claude import ClaudeAdapter
        register_adapter("claude", ClaudeAdapter)
    except ImportError:
        pass
    try:
        from charter.adapters.openai import OpenAIAdapter
        register_adapter("openai", OpenAIAdapter)
    except ImportError:
        pass
    try:
        from charter.adapters.xai import XAIAdapter
        register_adapter("xai", XAIAdapter)
    except ImportError:
        pass
    try:
        from charter.adapters.rag import RAGAdapter
        register_adapter("rag", RAGAdapter)
    except ImportError:
        pass


_auto_register()
