"""Attribution stamps for governed AI work products.

A stamp is a signed record that says: this work product was created
by node X, using AI tools Y, governed by charter Z. No stamp means
no governance provenance. No provenance means the work product is
rejected at the institutional ingestion gate.

Stamps can be embedded in git commit trailers, file headers, API
payloads, or saved as standalone JSON for verification.
"""

import hashlib
import json
import os
import time

from charter.config import load_config
from charter.identity import (
    append_to_chain,
    load_identity,
    sign_data,
)


STAMP_VERSION = "1.0"


def hash_charter(config):
    """SHA-256 hash of the charter governance rules.

    This fingerprints the exact rule set that governed the work.
    If the charter changes, the hash changes, so stamps reference
    a specific governance state.
    """
    gov = config.get("governance", {})
    raw = json.dumps(gov, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def create_stamp(tools=None, description=None, config_path=None):
    """Create an attribution stamp from current state.

    Args:
        tools: List of detected AI tools (from detector). If None,
               attempts live detection.
        description: Optional description of the work product.
        config_path: Path to charter.yaml. If None, searches up.

    Returns:
        dict with the stamp, or None if no identity exists.
    """
    identity = load_identity()
    if not identity:
        return None

    config = load_config(config_path)
    charter_h = hash_charter(config) if config else None

    # Detect tools if not provided
    if tools is None:
        try:
            from charter.daemon.detector import detect_ai_tools
            tools = detect_ai_tools()
        except ImportError:
            tools = []

    # Build the tool attestation list
    tool_attestations = []
    all_governed = True
    for t in tools:
        att = {
            "tool_id": t["tool_id"],
            "name": t["name"],
            "vendor": t["vendor"],
            "governed": t.get("governable", False),
        }
        tool_attestations.append(att)
        if not t.get("governable", False):
            all_governed = False

    # If no tools detected, governed is False (no provenance)
    if not tool_attestations:
        all_governed = False

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    stamp = {
        "version": STAMP_VERSION,
        "node": identity["public_id"],
        "alias": identity.get("alias", ""),
        "timestamp": now,
        "charter_hash": charter_h,
        "domain": config.get("domain", "unknown") if config else "unknown",
        "tools": tool_attestations,
        "governed": all_governed,
        "description": description or "",
    }

    # Record in chain and capture the chain reference
    chain_entry = append_to_chain("work_product_stamped", {
        "charter_hash": charter_h,
        "tools": [t["tool_id"] for t in tool_attestations],
        "governed": all_governed,
        "description": description or "",
    })

    if chain_entry:
        stamp["chain_index"] = chain_entry["index"]
        stamp["chain_hash"] = chain_entry["hash"]

    # Sign the stamp
    stamp["signature"] = sign_data(stamp, identity["private_seed"])

    return stamp


def verify_stamp(stamp):
    """Verify a stamp's integrity.

    Checks:
        1. Signature is present
        2. Required fields exist
        3. Governance status is clear

    Returns:
        dict with verified (bool), governed (bool), reasons (list).

    Note: Full chain verification requires access to the signer's
    chain. This function verifies the stamp's self-consistency.
    """
    reasons = []

    # Check required fields
    required = ["version", "node", "timestamp", "tools", "governed", "signature"]
    for field in required:
        if field not in stamp:
            reasons.append(f"missing field: {field}")

    if reasons:
        return {
            "verified": False,
            "governed": False,
            "reasons": reasons,
        }

    # Check governance
    governed = stamp.get("governed", False)
    if not governed:
        tools_list = stamp.get("tools", [])
        if not tools_list:
            reasons.append("no AI tools attested in stamp")
        else:
            ungoverned = [
                t["name"] for t in tools_list
                if not t.get("governed", False)
            ]
            if ungoverned:
                reasons.append(
                    f"ungoverned tools in stack: {', '.join(ungoverned)}"
                )

    # Check charter hash
    if not stamp.get("charter_hash"):
        reasons.append("no charter hash (work not governed by a charter)")

    return {
        "verified": len(reasons) == 0 or (governed and not reasons),
        "governed": governed,
        "reasons": reasons,
    }


def create_attestation(file_path, reason, reviewer_name=None):
    """Create a human attestation for an ungoverned work product.

    This is the dog wash. A human reviews work that was created
    outside governance and signs off on it. The human's identity
    becomes the accountability bridge.

    Args:
        file_path: Path to the file being attested.
        reason: Why the reviewer approves this for institutional use.
        reviewer_name: Optional reviewer name (uses identity alias if not set).

    Returns:
        dict with the attestation record, or None if no identity.
    """
    identity = load_identity()
    if not identity:
        return None

    # Hash the file content for integrity
    try:
        with open(file_path, "rb") as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return None

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    reviewer = reviewer_name or identity.get("alias", "unknown")

    attestation = {
        "version": STAMP_VERSION,
        "type": "attestation",
        "node": identity["public_id"],
        "alias": identity.get("alias", ""),
        "reviewer": reviewer,
        "timestamp": now,
        "file_path": os.path.basename(file_path),
        "file_hash": file_hash,
        "reason": reason,
        "governed": True,  # Attested by human review = governed
    }

    # Record in chain
    chain_entry = append_to_chain("work_product_attested", {
        "file": os.path.basename(file_path),
        "file_hash": file_hash,
        "reviewer": reviewer,
        "reason": reason,
    })

    if chain_entry:
        attestation["chain_index"] = chain_entry["index"]
        attestation["chain_hash"] = chain_entry["hash"]

    attestation["signature"] = sign_data(attestation, identity["private_seed"])

    return attestation


def accept_work_product(stamp):
    """Ingestion gate: decide whether to accept a work product.

    Three outcomes:
        1. No stamp, no AI declared -> ACCEPTED (human-only work, no gate needed)
        2. Stamp present, all tools governed -> ACCEPTED
        3. Stamp present, ungoverned tools -> REJECTED

    The gate only activates when AI is in the stack. Human-only work
    passes through without friction. This is deliberate: the governance
    layer governs AI, not humans.

    Args:
        stamp: Attribution stamp dict, None, or "human_only" string.

    Returns:
        (accepted: bool, reason: str)
    """
    # Human-only work: no AI involved, no gate needed
    if stamp is None or stamp == "human_only":
        return True, "human-only work product, no AI governance required"

    if not isinstance(stamp, dict):
        return False, "invalid stamp format"

    # Attested work products: human reviewed and approved
    if stamp.get("type") == "attestation":
        if stamp.get("governed") and stamp.get("reviewer") and stamp.get("signature"):
            reviewer = stamp.get("reviewer", "unknown")
            return True, f"attested by {reviewer}, human review is the governance bridge"
        return False, "attestation incomplete (missing reviewer or signature)"

    result = verify_stamp(stamp)

    if not result["governed"]:
        tool_names = ", ".join(t["name"] for t in stamp.get("tools", []))
        if tool_names:
            return False, (
                f"work product used ungoverned AI tools ({tool_names}). "
                f"all AI tools must operate under a charter for institutional use."
            )
        return False, (
            "no governed AI tools in attribution chain. "
            "institutional use requires governed provenance."
        )

    if not stamp.get("charter_hash"):
        return False, "no charter governance reference in stamp"

    return True, "stamp valid, all tools governed, charter referenced"


def stamp_to_trailer(stamp):
    """Compact one-line form for git commit trailers.

    Format: Charter-Stamp: v{version}:{node_short}:{tools}:{status}:{charter_short}

    Example:
        Charter-Stamp: v1.0:93921f61:claude_code:governed:a1b2c3d4
    """
    if not stamp:
        return ""

    node_short = stamp["node"][:8]
    tool_ids = "+".join(t["tool_id"] for t in stamp.get("tools", []))
    status = "governed" if stamp["governed"] else "ungoverned"
    charter_short = (stamp.get("charter_hash") or "none")[:8]

    return f"Charter-Stamp: v{stamp['version']}:{node_short}:{tool_ids}:{status}:{charter_short}"


def stamp_to_header(stamp, language="python"):
    """Embeddable attribution header for source files.

    Returns a comment block suitable for the given language.
    """
    if not stamp:
        return ""

    trailer = stamp_to_trailer(stamp)
    status = "GOVERNED" if stamp["governed"] else "UNGOVERNED"
    tool_list = ", ".join(t["name"] for t in stamp.get("tools", []))
    ts = stamp["timestamp"]

    content = [
        f"Attribution: {status}",
        f"Node: {stamp['alias']} ({stamp['node'][:16]}...)",
        f"Tools: {tool_list}",
        f"Charter: {(stamp.get('charter_hash') or 'none')[:16]}...",
        f"Time: {ts}",
        f"{trailer}",
    ]

    comment_styles = {
        "python": ("# ", "# ", "# "),
        "javascript": ("// ", "// ", "// "),
        "typescript": ("// ", "// ", "// "),
        "html": ("<!-- ", "  ", " -->"),
        "css": ("/* ", " * ", " */"),
        "yaml": ("# ", "# ", "# "),
        "sql": ("-- ", "-- ", "-- "),
        "rust": ("// ", "// ", "// "),
        "go": ("// ", "// ", "// "),
    }

    start, mid, end = comment_styles.get(language, ("# ", "# ", "# "))

    lines = [f"{start}--- Charter Attribution ---"]
    for line in content:
        lines.append(f"{mid}{line}")
    lines.append(f"{end}--- End Attribution ---")

    return "\n".join(lines)


def stamp_to_json(stamp, indent=2):
    """Full JSON form for standalone verification."""
    if not stamp:
        return "{}"
    return json.dumps(stamp, indent=indent, sort_keys=False)


def run_stamp(args):
    """CLI entry point for charter stamp."""
    stamp = create_stamp(description=getattr(args, "description", None))
    if not stamp:
        print("No identity found. Run 'charter init' first.")
        return

    status = "GOVERNED" if stamp["governed"] else "UNGOVERNED"
    print(f"Attribution Stamp: {status}")
    print(f"  Node:    {stamp['alias']} ({stamp['node'][:16]}...)")
    print(f"  Charter: {(stamp.get('charter_hash') or 'none')[:16]}...")
    print(f"  Tools:")
    for t in stamp["tools"]:
        gov_label = "governed" if t["governed"] else "ungoverned"
        print(f"    {t['name']} ({t['vendor']}) [{gov_label}]")
    if not stamp["tools"]:
        print("    (none detected)")
    print()

    fmt = getattr(args, "format", "trailer")

    if fmt == "trailer":
        print(stamp_to_trailer(stamp))
    elif fmt == "json":
        print(stamp_to_json(stamp))
    elif fmt == "header":
        lang = getattr(args, "language", "python")
        print(stamp_to_header(stamp, language=lang))
    else:
        print(stamp_to_trailer(stamp))

    # Show gate decision
    accepted, reason = accept_work_product(stamp)
    print()
    gate = "ACCEPTED" if accepted else "REJECTED"
    print(f"Ingestion Gate: {gate}")
    print(f"  {reason}")


def run_attest(args):
    """CLI entry point for charter attest.

    Workflow:
        1. Check if the file already has a governed stamp → no attestation needed
        2. Check if a charter.yaml governs this directory → suggest using stamp instead
        3. If neither, proceed with human attestation
    """
    file_path = getattr(args, "file", None)
    if not file_path:
        print("Usage: charter attest <file> --reason 'why this is acceptable'")
        return

    if not os.path.isfile(file_path):
        print(f"File not found: {file_path}")
        return

    # Step 1: Check for existing attestation
    att_path = file_path + ".attestation.json"
    if os.path.isfile(att_path):
        try:
            with open(att_path) as f:
                existing = json.load(f)
            accepted, reason = accept_work_product(existing)
            if accepted:
                print(f"Already attested.")
                print(f"  Reviewer: {existing.get('reviewer', '?')}")
                print(f"  Reason:   {existing.get('reason', '?')}")
                print(f"  Gate:     ACCEPTED ({reason})")
                return
        except (json.JSONDecodeError, KeyError):
            pass  # Corrupted attestation, proceed to re-attest

    # Step 2: Check if current environment is governed
    config = load_config()
    if config:
        charter_h = hash_charter(config)
        try:
            from charter.daemon.detector import detect_ai_tools
            tools = detect_ai_tools()
            governed_tools = [t for t in tools if t.get("governable")]
            ungoverned_tools = [t for t in tools if not t.get("governable")]

            if governed_tools and not ungoverned_tools:
                print(f"This environment is already governed.")
                print(f"  Charter: {charter_h[:16]}...")
                print(f"  Tools:   {', '.join(t['name'] for t in governed_tools)}")
                print(f"\n  Use 'charter stamp' instead. No attestation needed.")
                print(f"  Attestation is for work created outside governance.")
                return

            if ungoverned_tools:
                print(f"Governance check:")
                print(f"  Charter found: {config.get('domain', 'unknown')} domain")
                for t in ungoverned_tools:
                    print(f"  Warning: {t['name']} ({t['vendor']}) is ungoverned")
                print()
        except ImportError:
            pass

    # Step 3: Proceed with attestation
    reason = getattr(args, "reason", None) or "Reviewed and approved for institutional use"
    reviewer = getattr(args, "reviewer", None)

    attestation = create_attestation(file_path, reason, reviewer_name=reviewer)
    if not attestation:
        print("Could not create attestation. Check identity and file path.")
        return

    print(f"Attestation Created")
    print(f"  File:     {attestation['file_path']}")
    print(f"  Hash:     {attestation['file_hash'][:16]}...")
    print(f"  Reviewer: {attestation['reviewer']}")
    print(f"  Reason:   {attestation['reason']}")
    print(f"  Chain:    entry #{attestation.get('chain_index', '?')}")
    print()

    # Show gate decision
    accepted, gate_reason = accept_work_product(attestation)
    gate = "ACCEPTED" if accepted else "REJECTED"
    print(f"Ingestion Gate: {gate}")
    print(f"  {gate_reason}")

    # Save attestation as JSON alongside the file
    with open(att_path, "w") as f:
        json.dump(attestation, f, indent=2)
    print(f"\n  Attestation saved: {att_path}")


def run_verify(args):
    """CLI entry point for charter verify (verify a stamp)."""
    # Read stamp from file or stdin
    stamp_path = getattr(args, "stamp_file", None)
    if not stamp_path:
        print("Usage: charter verify <stamp.json>")
        return

    try:
        with open(stamp_path) as f:
            stamp = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading stamp: {e}")
        return

    result = verify_stamp(stamp)
    accepted, reason = accept_work_product(stamp)

    status = "GOVERNED" if result["governed"] else "UNGOVERNED"
    gate = "ACCEPTED" if accepted else "REJECTED"

    print(f"Stamp Verification: {status}")
    print(f"  Node:    {stamp.get('alias', '?')} ({stamp.get('node', '?')[:16]}...)")
    print(f"  Tools:   {len(stamp.get('tools', []))}")
    for t in stamp.get("tools", []):
        gov_label = "governed" if t.get("governed") else "ungoverned"
        print(f"    {t['name']} [{gov_label}]")
    print(f"  Charter: {(stamp.get('charter_hash') or 'none')[:16]}...")
    print()
    print(f"Ingestion Gate: {gate}")
    print(f"  {reason}")

    if result["reasons"]:
        print()
        print("Details:")
        for r in result["reasons"]:
            print(f"  - {r}")
