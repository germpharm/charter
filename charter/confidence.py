"""Confidence tagging and revision linkage for Charter chain entries.

Every chain entry records a decision, but not all decisions carry the same
certainty. This module enriches chain entry data dicts with confidence
metadata — how sure the system is, what evidence supports it, and what
assumptions must hold true.

Revision linkage connects entries that supersede earlier ones. When a
decision is revised, the new entry points back to the original via
_revision_of, creating a backward-traceable chain of reasoning. This
makes it possible to answer two questions:

    1. "What revised this entry?" (forward lookup via find_revisions)
    2. "What's the full history behind this decision?" (backward walk
       via get_revision_chain)

Confidence fields are prefixed with _ to distinguish them from user data.
Existing entries without these fields remain valid — this is backward
compatible. The fields live inside the data dict, not in the entry
schema itself.

Confidence levels:
    verified     — Supported by direct evidence or confirmed outcome
    inferred     — Derived from available data with reasonable confidence
    exploratory  — Hypothesis or early-stage reasoning, may change
"""

import json
import os
import time

from charter.identity import append_to_chain


CONFIDENCE_LEVELS = ("verified", "inferred", "exploratory")


def validate_confidence(confidence):
    """Return True if confidence is one of the three valid levels."""
    return confidence in CONFIDENCE_LEVELS


def tag_confidence(data, confidence, evidence_basis, constraint_assumptions=None):
    """Enrich a data dict with confidence metadata.

    Returns a new dict (copy of data) with added fields:
        _confidence: the confidence level
        _evidence_basis: str explaining the evidence
        _constraint_assumptions: list of assumptions that must remain true

    Args:
        data: The chain entry data dict to enrich.
        confidence: One of "verified", "inferred", "exploratory".
        evidence_basis: String explaining what evidence supports this.
        constraint_assumptions: Optional list of assumptions that must
            remain true for this confidence level to hold.

    Returns:
        New dict with confidence fields added, or None if confidence
        is invalid.
    """
    if not validate_confidence(confidence):
        return None

    enriched = dict(data)
    enriched["_confidence"] = confidence
    enriched["_evidence_basis"] = evidence_basis
    enriched["_constraint_assumptions"] = constraint_assumptions or []

    return enriched


def link_revision(data, revision_of, revision_reason):
    """Enrich a data dict with revision linkage.

    Returns a new dict (copy of data) with added fields:
        _revision_of: the entry hash being revised
        _revision_reason: str explaining what changed and why

    Args:
        data: The chain entry data dict to enrich.
        revision_of: Hash of the chain entry being revised.
        revision_reason: String explaining what changed and why.

    Returns:
        New dict with revision fields added, or None if revision_of
        or revision_reason is empty.
    """
    if not revision_of or not revision_reason:
        return None

    enriched = dict(data)
    enriched["_revision_of"] = revision_of
    enriched["_revision_reason"] = revision_reason

    return enriched


def _load_chain(chain_path):
    """Load all entries from a chain.jsonl file.

    Returns a list of entry dicts, or an empty list if the file
    does not exist or is empty.
    """
    if not os.path.isfile(chain_path):
        return []

    with open(chain_path) as f:
        entries = [json.loads(line) for line in f if line.strip()]

    return entries


def _find_entry_by_hash(entries, entry_hash):
    """Find a chain entry by its hash field.

    Returns the entry dict, or None if not found.
    """
    for entry in entries:
        if entry.get("hash") == entry_hash:
            return entry
    return None


def find_revisions(chain_path, entry_hash):
    """Find all entries whose data._revision_of matches entry_hash.

    This is a forward lookup: "what revised this entry?"

    Args:
        chain_path: Path to chain.jsonl.
        entry_hash: The hash of the entry to find revisions for.

    Returns:
        List of matching chain entries. Empty list if none found.
    """
    entries = _load_chain(chain_path)
    revisions = []

    for entry in entries:
        data = entry.get("data", {})
        if data.get("_revision_of") == entry_hash:
            revisions.append(entry)

    return revisions


def get_revision_chain(chain_path, entry_hash):
    """Walk backward through _revision_of links to build full revision history.

    Starts from entry_hash, finds what it revised, what that revised,
    etc. Returns the list from oldest ancestor to the starting entry.

    Args:
        chain_path: Path to chain.jsonl.
        entry_hash: The hash of the entry to trace backward from.

    Returns:
        List of entries from oldest to newest. Empty list if the entry
        has no revision links or is not found.
    """
    entries = _load_chain(chain_path)
    if not entries:
        return []

    # Find the starting entry
    current = _find_entry_by_hash(entries, entry_hash)
    if not current:
        return []

    # Walk backward collecting ancestors
    chain = [current]
    seen = {entry_hash}

    while True:
        revision_of = current.get("data", {}).get("_revision_of")
        if not revision_of:
            break

        # Guard against cycles
        if revision_of in seen:
            break
        seen.add(revision_of)

        ancestor = _find_entry_by_hash(entries, revision_of)
        if not ancestor:
            break

        chain.append(ancestor)
        current = ancestor

    # Reverse so oldest is first
    chain.reverse()
    return chain


def run_confidence(args):
    """CLI entry point for charter confidence."""
    if args.action == "tag":
        from charter.identity import get_chain_path

        chain_path = get_chain_path()
        if not os.path.isfile(chain_path):
            print("No chain found. Run 'charter init' first.")
            return

        with open(chain_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        if not entries:
            print("Chain is empty.")
            return

        entry_index = args.index
        if entry_index < 0 or entry_index >= len(entries):
            print(f"Entry index {entry_index} out of range (0-{len(entries) - 1}).")
            return

        target = entries[entry_index]
        confidence = args.confidence
        evidence_basis = args.evidence_basis
        constraint_assumptions = args.assumptions or []

        if not validate_confidence(confidence):
            print(f"Invalid confidence level: {confidence}")
            print(f"  Valid levels: {', '.join(CONFIDENCE_LEVELS)}")
            return

        tagged_data = tag_confidence(
            {
                "entry_index": entry_index,
                "entry_hash": target["hash"],
                "confidence": confidence,
                "evidence_basis": evidence_basis,
                "constraint_assumptions": constraint_assumptions,
            },
            confidence,
            evidence_basis,
            constraint_assumptions,
        )

        chain_entry = append_to_chain("confidence_tagged", tagged_data)

        if chain_entry:
            print(f"Confidence Tagged")
            print(f"  Entry:       #{entry_index} ({target['hash'][:24]}...)")
            print(f"  Confidence:  {confidence}")
            print(f"  Evidence:    {evidence_basis}")
            if constraint_assumptions:
                print(f"  Assumptions:")
                for assumption in constraint_assumptions:
                    print(f"    - {assumption}")
            print(f"  Chain:       entry #{chain_entry['index']}")
        else:
            print("Failed to record confidence tag. Check identity.")

    elif args.action == "revisions":
        from charter.identity import get_chain_path

        chain_path = get_chain_path()
        entry_hash = args.entry_hash

        revisions = find_revisions(chain_path, entry_hash)

        if not revisions:
            print(f"No revisions found for entry {entry_hash[:24]}...")
            return

        print(f"Revisions of {entry_hash[:24]}...")
        print()
        for rev in revisions:
            idx = rev.get("index", "?")
            ts = rev.get("timestamp", "?")
            reason = rev.get("data", {}).get("_revision_reason", "(no reason)")
            print(f"  #{idx}  {ts}  {reason}")

    elif args.action == "history":
        from charter.identity import get_chain_path

        chain_path = get_chain_path()
        entry_hash = args.entry_hash

        chain = get_revision_chain(chain_path, entry_hash)

        if not chain:
            print(f"No revision history for entry {entry_hash[:24]}...")
            return

        print(f"Revision History (oldest to newest)")
        print()
        for i, entry in enumerate(chain):
            idx = entry.get("index", "?")
            ts = entry.get("timestamp", "?")
            event = entry.get("event", "?")
            confidence = entry.get("data", {}).get("_confidence", "")
            revision_reason = entry.get("data", {}).get("_revision_reason", "")

            marker = " (current)" if i == len(chain) - 1 else ""
            print(f"  #{idx}  {ts}  [{event}]{marker}")
            if confidence:
                print(f"        confidence: {confidence}")
            if revision_reason:
                print(f"        revised because: {revision_reason}")
