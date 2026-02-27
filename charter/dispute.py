"""Dispute examination tools for Charter hash chains.

Creates self-contained proof packages for dispute resolution.
A proof package contains everything needed to independently verify
a segment of the hash chain — the digital equivalent of a title
abstract with every deed, lien, and transfer documented.

The package is a mathematical proof. An examiner verifies it by
re-computing the hashes. If every hash checks out, the chain is
authentic. If any hash fails, that's the precise point of tampering.
No trust required — the math is the proof.

Inspection Protocol (six phases):
    Phase 1 — Discovery: Both parties export chain segments
    Phase 2 — Independent Verification: Technical examiner verifies
    Phase 3 — Alignment: Match exchange proofs, find common ground
    Phase 4 — Divergence Mapping: Identify where chains disagree
    Phase 5 — Governance Context Reconstruction: What rules were active
    Phase 6 — Adjudication: Human judgment on the evidence
"""

import hashlib
import json
import os
import time

from charter.identity import (
    get_chain_path,
    load_identity,
    hash_entry,
    sign_data,
)
from charter.config import hash_config, get_config_at_chain_index


def export_dispute_package(
    from_index: int,
    to_index: int,
    chain_path: str = None,
) -> dict | None:
    """Export a self-contained dispute proof package.

    The package contains everything needed for an independent examiner
    to verify the chain segment:
    - Chain entries for the disputed range
    - Merkle proofs for each entry (if batched)
    - HMAC-SHA256 signatures
    - Governance config hashes active during the period
    - RFC 3161 timestamp anchors within the range
    - Exchange proofs with counterparties (if any)

    Args:
        from_index: Starting chain entry index (inclusive).
        to_index: Ending chain entry index (inclusive).
        chain_path: Path to chain.jsonl (uses default if None).

    Returns:
        A self-contained proof package dict, or None on failure.
    """
    if chain_path is None:
        chain_path = get_chain_path()

    if not os.path.isfile(chain_path):
        return None

    identity = load_identity()
    if not identity:
        return None

    # Load the full chain
    with open(chain_path) as f:
        all_entries = [json.loads(line) for line in f if line.strip()]

    if not all_entries:
        return None

    # Extract the disputed range
    segment = [
        e for e in all_entries
        if from_index <= e.get("index", -1) <= to_index
    ]

    if not segment:
        return None

    # Include context entries: one entry before from_index (for hash link)
    # and one after to_index (to prove chain continues)
    context_before = None
    context_after = None
    for e in all_entries:
        idx = e.get("index", -1)
        if idx == from_index - 1:
            context_before = e
        if idx == to_index + 1:
            context_after = e

    # Collect governance config changes within and before the range
    config_snapshots = []
    for e in all_entries:
        if e.get("event") == "governance_config_changed":
            idx = e.get("index", -1)
            if idx <= to_index:
                config_snapshots.append({
                    "chain_index": idx,
                    "timestamp": e.get("timestamp"),
                    "config_hash": e.get("data", {}).get("config_hash"),
                    "previous_hash": e.get("data", {}).get("previous_hash"),
                    "domain": e.get("data", {}).get("domain"),
                    "layer_a_rules": e.get("data", {}).get("layer_a_rules"),
                    "layer_b_rules": e.get("data", {}).get("layer_b_rules"),
                    "kill_triggers": e.get("data", {}).get("kill_triggers"),
                })

    # Collect timestamp anchors within the range
    timestamp_anchors = []
    for e in segment:
        if e.get("event") == "timestamp_anchor":
            anchor_data = e.get("data", {})
            timestamp_anchors.append({
                "chain_index": e.get("index"),
                "timestamp": e.get("timestamp"),
                "tsa_url": anchor_data.get("tsa_url"),
                "tsa_timestamp": anchor_data.get("tsa_timestamp"),
                "chain_hash_anchored": anchor_data.get("chain_hash_anchored"),
                "response_b64": anchor_data.get("response_b64"),
                "query_b64": anchor_data.get("query_b64"),
            })

    # Also find the nearest anchors before and after the range
    nearest_anchor_before = None
    nearest_anchor_after = None
    for e in all_entries:
        if e.get("event") == "timestamp_anchor":
            idx = e.get("index", -1)
            if idx < from_index:
                nearest_anchor_before = {
                    "chain_index": idx,
                    "timestamp": e.get("timestamp"),
                    "tsa_timestamp": e.get("data", {}).get("tsa_timestamp"),
                    "chain_hash_anchored": e.get("data", {}).get("chain_hash_anchored"),
                }
            elif idx > to_index and nearest_anchor_after is None:
                nearest_anchor_after = {
                    "chain_index": idx,
                    "timestamp": e.get("timestamp"),
                    "tsa_timestamp": e.get("data", {}).get("tsa_timestamp"),
                    "chain_hash_anchored": e.get("data", {}).get("chain_hash_anchored"),
                }

    # Collect exchange proofs within the range
    exchange_proofs = []
    for e in segment:
        if e.get("event") in ("exchange_proof_created", "exchange_proof_received"):
            exchange_proofs.append({
                "chain_index": e.get("index"),
                "timestamp": e.get("timestamp"),
                "event": e.get("event"),
                "data": e.get("data"),
            })

    # Generate Merkle proofs for each entry in the segment
    merkle_proofs = {}
    try:
        from charter.merkle import generate_proof
        for e in segment:
            idx = e.get("index", -1)
            proof = generate_proof(idx)
            if proof:
                merkle_proofs[str(idx)] = proof
    except Exception:
        pass  # Merkle proofs are supplementary; proceed without them

    # Verify chain integrity within the segment
    integrity_checks = []
    for i in range(1, len(segment)):
        prev_hash = segment[i].get("previous_hash")
        expected = segment[i - 1].get("hash")
        is_valid = prev_hash == expected
        if not is_valid:
            integrity_checks.append({
                "index": segment[i].get("index"),
                "expected_previous": expected,
                "actual_previous": prev_hash,
                "status": "BREAK",
            })

    # Verify link from context_before to first segment entry
    boundary_check = None
    if context_before and segment:
        link_valid = segment[0].get("previous_hash") == context_before.get("hash")
        boundary_check = {
            "from_index": context_before.get("index"),
            "to_index": segment[0].get("index"),
            "valid": link_valid,
        }

    # Build the package
    package = {
        "type": "charter_dispute_package",
        "version": "1.0",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_node": identity["public_id"],
        "source_alias": identity.get("alias"),
        "range": {
            "from_index": from_index,
            "to_index": to_index,
            "entry_count": len(segment),
        },
        "chain_segment": segment,
        "context": {
            "entry_before": context_before,
            "entry_after": context_after,
            "boundary_link_valid": boundary_check,
        },
        "governance": {
            "config_snapshots": config_snapshots,
            "active_config_at_start": get_config_at_chain_index(from_index),
            "active_config_at_end": get_config_at_chain_index(to_index),
        },
        "timestamp_anchors": {
            "within_range": timestamp_anchors,
            "nearest_before": nearest_anchor_before,
            "nearest_after": nearest_anchor_after,
        },
        "merkle_proofs": merkle_proofs,
        "exchange_proofs": exchange_proofs,
        "integrity": {
            "chain_breaks_in_segment": integrity_checks,
            "segment_intact": len(integrity_checks) == 0,
        },
        "verification_instructions": {
            "step_1": (
                "For each entry in chain_segment, recompute the hash: "
                "SHA-256 of the JSON-serialized entry (all fields except 'hash', "
                "sorted keys, compact separators). Compare to the 'hash' field."
            ),
            "step_2": (
                "Verify the chain links: each entry's 'previous_hash' must equal "
                "the preceding entry's 'hash'. Any mismatch is a break."
            ),
            "step_3": (
                "Verify HMAC-SHA256 signatures if the source node's public_id "
                "is available for signature verification."
            ),
            "step_4": (
                "For entries with Merkle proofs, verify each proof path resolves "
                "to the stated merkle_root. Use: hash_pair(current, sibling) "
                "at each step, where position indicates sibling placement."
            ),
            "step_5": (
                "For RFC 3161 timestamp anchors, verify using: "
                "openssl ts -reply -in <response_file> -text "
                "The TSA timestamp provides independent time attestation."
            ),
            "step_6": (
                "Check governance config snapshots to determine which rules "
                "were active at each disputed entry."
            ),
        },
    }

    # Sign the entire package
    package["signature"] = sign_data(package, identity["private_seed"])

    return package


def verify_dispute_package(package: dict) -> dict:
    """Verify a dispute package's internal consistency.

    This is what an independent examiner runs. It checks:
    1. Chain hash integrity (every hash links correctly)
    2. Entry hash validity (recomputed hashes match)
    3. Merkle proof validity (where proofs exist)
    4. Boundary links (segment connects to surrounding context)

    Args:
        package: A dispute package dict.

    Returns:
        Comprehensive verification result.
    """
    if package.get("type") != "charter_dispute_package":
        return {"verified": False, "reason": "Not a Charter dispute package"}

    segment = package.get("chain_segment", [])
    if not segment:
        return {"verified": False, "reason": "Empty chain segment"}

    results = {
        "package_type": package.get("type"),
        "source_node": package.get("source_node"),
        "range": package.get("range"),
        "checks": {},
    }

    # Check 1: Verify each entry's hash
    hash_results = []
    for entry in segment:
        recomputed = hash_entry(entry)
        stored = entry.get("hash")
        valid = recomputed == stored
        if not valid:
            hash_results.append({
                "index": entry.get("index"),
                "status": "FAILED",
                "expected": recomputed,
                "got": stored,
            })
    results["checks"]["entry_hashes"] = {
        "total": len(segment),
        "valid": len(segment) - len(hash_results),
        "failures": hash_results,
        "passed": len(hash_results) == 0,
    }

    # Check 2: Verify chain links
    link_results = []
    for i in range(1, len(segment)):
        prev_hash = segment[i].get("previous_hash")
        expected = segment[i - 1].get("hash")
        if prev_hash != expected:
            link_results.append({
                "index": segment[i].get("index"),
                "status": "BREAK",
                "expected_previous": expected,
                "actual_previous": prev_hash,
            })
    results["checks"]["chain_links"] = {
        "total": len(segment) - 1,
        "valid": (len(segment) - 1) - len(link_results),
        "breaks": link_results,
        "passed": len(link_results) == 0,
    }

    # Check 3: Verify boundary links
    context = package.get("context", {})
    entry_before = context.get("entry_before")
    if entry_before and segment:
        boundary_valid = segment[0].get("previous_hash") == entry_before.get("hash")
        results["checks"]["boundary_link_before"] = {
            "from_index": entry_before.get("index"),
            "to_index": segment[0].get("index"),
            "passed": boundary_valid,
        }

    entry_after = context.get("entry_after")
    if entry_after and segment:
        boundary_valid = entry_after.get("previous_hash") == segment[-1].get("hash")
        results["checks"]["boundary_link_after"] = {
            "from_index": segment[-1].get("index"),
            "to_index": entry_after.get("index"),
            "passed": boundary_valid,
        }

    # Check 4: Verify Merkle proofs
    merkle_proofs = package.get("merkle_proofs", {})
    if merkle_proofs:
        from charter.merkle import MerkleTree
        merkle_results = []
        for idx_str, proof_data in merkle_proofs.items():
            leaf_hash = proof_data.get("leaf_hash")
            proof_path = proof_data.get("proof")
            root = proof_data.get("merkle_root")
            if all([leaf_hash, proof_path is not None, root]):
                valid = MerkleTree.verify_proof(leaf_hash, proof_path, root)
                if not valid:
                    merkle_results.append({
                        "chain_index": int(idx_str),
                        "status": "FAILED",
                    })
        results["checks"]["merkle_proofs"] = {
            "total": len(merkle_proofs),
            "valid": len(merkle_proofs) - len(merkle_results),
            "failures": merkle_results,
            "passed": len(merkle_results) == 0,
        }

    # Overall verdict
    all_passed = all(
        check.get("passed", True)
        for check in results["checks"].values()
    )
    results["verified"] = all_passed
    results["reason"] = (
        "All checks passed — chain segment is authentic"
        if all_passed
        else "One or more verification checks failed"
    )

    return results


def inspect_dispute_package(package: dict) -> str:
    """Generate a human-readable inspection report from a dispute package.

    This is Phase 2 (Independent Verification) of the inspection protocol,
    formatted for review by a technical examiner or legal team.

    Args:
        package: A dispute package dict.

    Returns:
        Formatted markdown inspection report.
    """
    verification = verify_dispute_package(package)
    segment = package.get("chain_segment", [])
    pkg_range = package.get("range", {})

    lines = []
    lines.append("# Charter Dispute Package — Independent Verification Report")
    lines.append("")
    lines.append(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    lines.append(f"**Package created:** {package.get('created_at')}")
    lines.append(f"**Source node:** {package.get('source_alias')} ({package.get('source_node', '')[:24]}...)")
    lines.append("")

    # Range summary
    lines.append("## Disputed Range")
    lines.append("")
    lines.append(f"- Entry range: [{pkg_range.get('from_index')} — {pkg_range.get('to_index')}]")
    lines.append(f"- Entries examined: {pkg_range.get('entry_count')}")
    if segment:
        lines.append(f"- First timestamp: {segment[0].get('timestamp')}")
        lines.append(f"- Last timestamp: {segment[-1].get('timestamp')}")
    lines.append("")

    # Verification results
    status = "VERIFIED" if verification["verified"] else "FAILED"
    lines.append(f"## Verification Result: {status}")
    lines.append("")

    for check_name, check_result in verification.get("checks", {}).items():
        check_status = "PASS" if check_result.get("passed") else "FAIL"
        lines.append(f"### {check_name}: {check_status}")
        if "total" in check_result:
            lines.append(f"- Checked: {check_result['total']}")
            lines.append(f"- Valid: {check_result.get('valid', 'N/A')}")
        if check_result.get("failures") or check_result.get("breaks"):
            issues = check_result.get("failures") or check_result.get("breaks", [])
            for issue in issues:
                lines.append(f"- **Issue at index {issue.get('index')}:** {issue.get('status')}")
        lines.append("")

    # Governance context
    gov = package.get("governance", {})
    lines.append("## Governance Context")
    lines.append("")
    config_at_start = gov.get("active_config_at_start")
    config_at_end = gov.get("active_config_at_end")
    if config_at_start:
        lines.append(f"- Config at range start: {config_at_start.get('config_hash', 'N/A')[:24]}...")
        lines.append(f"  - Domain: {config_at_start.get('domain')}")
        lines.append(f"  - Layer A rules: {config_at_start.get('layer_a_rules')}")
        lines.append(f"  - Layer B rules: {config_at_start.get('layer_b_rules')}")
        lines.append(f"  - Changed at index: {config_at_start.get('changed_at_index')}")
    if config_at_end and config_at_end != config_at_start:
        lines.append(f"- Config at range end: {config_at_end.get('config_hash', 'N/A')[:24]}...")
        lines.append(f"  - **Governance changed during disputed period**")
    snapshots = gov.get("config_snapshots", [])
    if snapshots:
        lines.append(f"- Config changes in period: {len(snapshots)}")
    lines.append("")

    # Timestamp anchors
    ts = package.get("timestamp_anchors", {})
    anchors_in_range = ts.get("within_range", [])
    lines.append("## Timestamp Anchoring")
    lines.append("")
    if anchors_in_range:
        lines.append(f"- Anchors within range: {len(anchors_in_range)}")
        for a in anchors_in_range:
            lines.append(f"  - Index {a.get('chain_index')}: {a.get('tsa_timestamp')} ({a.get('tsa_url')})")
    else:
        lines.append("- No RFC 3161 anchors within disputed range")
    if ts.get("nearest_before"):
        nb = ts["nearest_before"]
        lines.append(f"- Nearest anchor before range: index {nb.get('chain_index')} ({nb.get('tsa_timestamp')})")
    if ts.get("nearest_after"):
        na = ts["nearest_after"]
        lines.append(f"- Nearest anchor after range: index {na.get('chain_index')} ({na.get('tsa_timestamp')})")
    lines.append("")

    # Event summary
    lines.append("## Event Summary")
    lines.append("")
    event_counts = {}
    for e in segment:
        event = e.get("event", "unknown")
        event_counts[event] = event_counts.get(event, 0) + 1
    for event, count in sorted(event_counts.items()):
        lines.append(f"- {event}: {count}")
    lines.append("")

    # Exchange proofs
    exchange = package.get("exchange_proofs", [])
    if exchange:
        lines.append("## Exchange Proofs")
        lines.append("")
        lines.append(f"- Cross-party proof events: {len(exchange)}")
        for ep in exchange:
            lines.append(f"  - Index {ep.get('chain_index')}: {ep.get('event')} at {ep.get('timestamp')}")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("*This report was generated by Charter's automated verification system.*")
    lines.append("*All checks are deterministic and independently reproducible.*")
    lines.append(f"*Package signature: {package.get('signature', 'N/A')[:32]}...*")

    return "\n".join(lines)


def run_dispute(args):
    """CLI entry point for charter dispute."""
    if args.action == "export":
        from_idx = args.from_index
        to_idx = args.to_index

        if from_idx is None or to_idx is None:
            # Default to full chain if not specified
            chain_path = get_chain_path()
            if not os.path.isfile(chain_path):
                print("No chain found.")
                return
            with open(chain_path) as f:
                entries = [json.loads(line) for line in f if line.strip()]
            if not entries:
                print("Chain is empty.")
                return
            if from_idx is None:
                from_idx = entries[0].get("index", 0)
            if to_idx is None:
                to_idx = entries[-1].get("index", 0)

        print(f"Exporting dispute package for entries {from_idx} to {to_idx}...")
        package = export_dispute_package(from_idx, to_idx)

        if not package:
            print("Failed to create dispute package.")
            return

        output = json.dumps(package, indent=2)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Dispute package saved to: {args.output}")
            print(f"  Entries: {package['range']['entry_count']}")
            print(f"  Merkle proofs: {len(package.get('merkle_proofs', {}))}")
            print(f"  Timestamp anchors: {len(package.get('timestamp_anchors', {}).get('within_range', []))}")
            print(f"  Config snapshots: {len(package.get('governance', {}).get('config_snapshots', []))}")
            print(f"  Integrity: {'INTACT' if package['integrity']['segment_intact'] else 'BROKEN'}")
        else:
            print(output)

    elif args.action == "verify":
        if not args.package:
            print("Usage: charter dispute verify --package <path>")
            return

        with open(args.package) as f:
            package = json.load(f)

        result = verify_dispute_package(package)

        status = "VERIFIED" if result["verified"] else "FAILED"
        print(f"Dispute Package Verification: {status}")
        print(f"  Source: {result.get('source_node', 'N/A')[:24]}...")
        print(f"  Range: [{result['range']['from_index']} — {result['range']['to_index']}]")
        print(f"  Entries: {result['range']['entry_count']}")
        print()
        for check_name, check_result in result.get("checks", {}).items():
            check_status = "PASS" if check_result.get("passed") else "FAIL"
            print(f"  [{check_status}] {check_name}")
        print()
        print(f"  Reason: {result['reason']}")

    elif args.action == "inspect":
        if not args.package:
            print("Usage: charter dispute inspect --package <path>")
            return

        with open(args.package) as f:
            package = json.load(f)

        report = inspect_dispute_package(package)

        if args.output:
            with open(args.output, "w") as f:
                f.write(report)
            print(f"Inspection report saved to: {args.output}")
        else:
            print(report)
