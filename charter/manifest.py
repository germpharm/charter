"""Charter Context Manifest — portable professional intelligence.

The Context Manifest is a standardized format that captures a person's
professional intelligence layer: identity, relationships, decision history,
behavioral patterns, and governance profile.

Two products use this format:
  Product 1 (Company-facing): Institutional Knowledge Retention
    - When someone leaves, the company keeps role-scoped knowledge
    - Next person gets onboarding context any AI can read

  Product 2 (Individual-facing): Professional Intelligence Portability
    - The person takes their intelligence layer with them
    - New AI reconstructs working context in hours, not months

Both use the same schema. The difference is scope filtering.

Usage:
    from charter.manifest import create_manifest, verify_manifest

    # Individual export
    manifest = create_manifest(scope="individual")

    # Company role export
    manifest = create_manifest(scope="institutional", context_name="dartmouth")

    # Verify integrity
    result = verify_manifest(manifest)
"""

import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

from charter.config import load_config
from charter.identity import (
    get_chain_path, load_identity, sign_data, append_to_chain,
)

MANIFEST_VERSION = "1.0"

# ── Core: Create ──────────────────────────────────────────────────


def create_manifest(scope="individual", context_name=None,
                    actor_id=None, since=None, config_path=None):
    """Create a Context Manifest.

    Orchestrates all submodules to build a complete manifest:
    identity, graph snapshot, decision log, pattern declarations,
    and governance profile.

    Args:
        scope: "individual" | "institutional" | "role"
        context_name: Optional context filter (e.g. "dartmouth").
        actor_id: Optional actor/signer filter for chain entries.
        since: Optional ISO date to filter interactions and decisions.
        config_path: Optional path to charter.yaml.

    Returns:
        dict: The complete Context Manifest, signed.
    """
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Identity block
    identity_block = _build_identity_block()

    # 2. Graph snapshot
    graph_snapshot = _build_graph_snapshot(
        context=context_name, since=since,
    )

    # 3. Decision log from chain
    decision_log = _build_decision_log(
        actor_id=actor_id, context=context_name, since=since,
    )

    # 4. Pattern declarations
    pattern_declarations = _build_pattern_declarations(actor=actor_id)

    # 5. Governance profile
    governance_profile = _build_governance_profile(config_path=config_path)

    # Assemble manifest
    manifest = {
        "@context": "https://schema.charteragent.ai/manifest/v1",
        "@type": "ContextManifest",
        "version": MANIFEST_VERSION,
        "scope": scope,
        "generated_at": generated_at,
        "identity": identity_block,
        "graph_snapshot": graph_snapshot,
        "decision_log": decision_log,
        "pattern_declarations": pattern_declarations,
        "governance_profile": governance_profile,
    }

    # Sign the manifest
    manifest["signature"] = _sign_manifest(manifest)

    # Record export in chain. Hash WITHOUT signature so it matches
    # get_manifest_anchor() (which strips signature before hashing).
    manifest_unsigned = {
        k: v for k, v in manifest.items() if k != "signature"
    }
    append_to_chain("manifest_exported", {
        "scope": scope,
        "context": context_name or "",
        "actor": actor_id or "",
        "entity_count": graph_snapshot.get(
            "stats", {}
        ).get("entity_count", 0),
        "decision_count": len(decision_log),
        "declaration_count": len(
            pattern_declarations.get("declarations", [])
        ),
        "manifest_hash": hashlib.sha256(
            json.dumps(
                manifest_unsigned,
                sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()[:32],
    })

    return manifest


# ── Core: Verify ──────────────────────────────────────────────────


def verify_manifest(manifest):
    """Verify a Context Manifest's integrity.

    Checks:
    - Version compatibility
    - Required fields present
    - Signature valid (if identity available)
    - Internal consistency

    Args:
        manifest: The manifest dict to verify.

    Returns:
        dict with valid (bool), checks (list), and errors (list).
    """
    checks = []
    errors = []

    # Version check
    version = manifest.get("version", "")
    if version == MANIFEST_VERSION:
        checks.append("version: compatible ({})".format(version))
    else:
        errors.append("version: incompatible (got {}, expected {})".format(
            version, MANIFEST_VERSION))

    # Required fields
    required = [
        "@context", "@type", "version", "scope", "generated_at",
        "identity", "graph_snapshot", "decision_log",
        "pattern_declarations", "governance_profile", "signature",
    ]
    for field in required:
        if field in manifest:
            checks.append("field present: {}".format(field))
        else:
            errors.append("missing required field: {}".format(field))

    # Scope validation
    scope = manifest.get("scope", "")
    if scope in ("individual", "institutional", "role"):
        checks.append("scope valid: {}".format(scope))
    else:
        errors.append("invalid scope: {}".format(scope))

    # Identity block
    identity = manifest.get("identity", {})
    if identity.get("public_id"):
        checks.append("identity: public_id present")
    else:
        errors.append("identity: missing public_id")

    # Graph snapshot basic validation
    gs = manifest.get("graph_snapshot", {})
    entity_count = gs.get("stats", {}).get("entity_count", 0)
    checks.append("graph: {} entities".format(entity_count))

    # Signature verification
    # Note: HMAC-SHA256 is symmetric — only the original signer can
    # verify their own signature. For cross-instance manifests, we
    # verify structural integrity and note the foreign signer.
    sig = manifest.get("signature", "")
    if sig:
        identity_data = load_identity()
        manifest_id = manifest.get("identity", {}).get("public_id", "")
        local_id = (identity_data or {}).get("public_id", "")

        if not identity_data:
            checks.append(
                "signature: present, no local identity to verify"
            )
        elif manifest_id and manifest_id != local_id:
            # Foreign manifest — cannot verify HMAC without source seed
            checks.append(
                "signature: present, signed by foreign identity {}".format(
                    manifest_id[:16]
                )
            )
            checks.append(
                "signature: cross-instance verification requires "
                "trust path (Merkle anchor or federation)"
            )
        elif identity_data.get("private_seed"):
            # Same identity — can verify HMAC
            manifest_copy = {
                k: v for k, v in manifest.items() if k != "signature"
            }
            expected_sig = sign_data(
                manifest_copy, identity_data["private_seed"]
            )
            if sig == expected_sig:
                checks.append("signature: valid (HMAC-SHA256)")
            else:
                errors.append(
                    "signature: mismatch (manifest may have been modified)"
                )
        else:
            checks.append(
                "signature: present, no private seed to verify"
            )
    else:
        errors.append("signature: missing")

    return {
        "valid": len(errors) == 0,
        "checks": checks,
        "errors": errors,
        "manifest_version": version,
        "scope": scope,
        "generated_at": manifest.get("generated_at", ""),
    }


# ── Core: Filter ──────────────────────────────────────────────────


def filter_manifest(manifest, target_scope):
    """Filter a manifest for a specific scope.

    - "institutional": Strip personal entities, keep role patterns,
      de-personalize actor references.
    - "individual": Strip company-proprietary data, keep personal
      patterns and identity.

    Args:
        manifest: The full manifest dict.
        target_scope: "institutional" or "individual".

    Returns:
        dict: A new filtered manifest (original unchanged).
    """
    import copy
    filtered = copy.deepcopy(manifest)
    filtered["scope"] = target_scope

    if target_scope == "institutional":
        # Strip personal context entities from graph
        gs = filtered.get("graph_snapshot", {})
        gs["entities"] = [
            e for e in gs.get("entities", [])
            if e.get("context", "") != "personal"
        ]
        # Remove personal emails and phones
        for entity in gs.get("entities", []):
            if entity.get("context", "") == "":
                entity["email"] = ""
                entity["phone"] = ""

        # Filter interactions to only work context
        gs["interactions"] = [
            i for i in gs.get("interactions", [])
            if i.get("interaction_type", "") in (
                "meeting", "call", "transaction", "email"
            )
        ]

        # Update stats
        gs["stats"]["entity_count"] = len(gs.get("entities", []))
        gs["stats"]["interaction_count"] = len(gs.get("interactions", []))

    elif target_scope == "individual":
        # Keep everything but strip governance rules that are
        # company-specific (they belong to the org, not the person)
        gp = filtered.get("governance_profile", {})
        # Keep only universal constraints (Layer A universal)
        if "layer_a" in gp:
            gp["layer_a"] = {
                "universal": gp["layer_a"].get("universal", []),
                "rules": [],  # Company-specific rules don't travel
            }
        # Layer B thresholds are company-specific
        gp["layer_b"] = []
        # Layer C audit config is personal
        # Compliance frameworks stay (professional credential)

    # Re-sign
    filtered["signature"] = _sign_manifest(
        {k: v for k, v in filtered.items() if k != "signature"}
    )

    return filtered


# ── Role Manifest (Product 1: Institutional Knowledge) ────────────


def generate_role_manifest(context_name, role_name=None, since=None,
                           config_path=None):
    """Generate an institutional role manifest for knowledge retention.

    When someone leaves a role, this captures what the role learned:
    decision patterns, relationship context, escalation behavior,
    institutional knowledge. De-personalized for the next person.

    Args:
        context_name: Work context to scope to (e.g. "dartmouth").
        role_name: Optional role label (e.g. "telepharmacy director").
        since: Optional ISO date filter.
        config_path: Optional path to charter.yaml.

    Returns:
        dict: A de-personalized, role-scoped Context Manifest.
    """
    # Start with a full institutional manifest
    manifest = create_manifest(
        scope="institutional",
        context_name=context_name,
        since=since,
        config_path=config_path,
    )

    # De-personalize: replace the primary identity with role reference
    identity = manifest.get("identity", {})
    original_alias = identity.get("alias", "unknown")
    role_label = role_name or "this role"

    manifest["role"] = {
        "name": role_label,
        "context": context_name,
        "original_alias": original_alias,
        "tenure_start": identity.get("created_at", ""),
    }

    # De-personalize graph entities: replace primary person with role ref
    gs = manifest.get("graph_snapshot", {})
    primary_id = None
    for entity in gs.get("entities", []):
        if entity.get("name", "").lower() == original_alias.lower():
            primary_id = entity.get("id")
            break

    if primary_id:
        for entity in gs.get("entities", []):
            if entity.get("id") == primary_id:
                entity["name"] = role_label
                entity["email"] = ""
                entity["_depersonalized"] = True

        # Update references in interactions
        for interaction in gs.get("interactions", []):
            if interaction.get("source_id") == primary_id:
                interaction["_source_role"] = role_label
            if interaction.get("target_id") == primary_id:
                interaction["_target_role"] = role_label

    # Strip personal identity details
    manifest["identity"] = {
        "public_id": "",
        "alias": role_label,
        "chain_hash": identity.get("chain_hash", ""),
        "verified": False,
        "charter_version": MANIFEST_VERSION,
        "scope_note": "Role manifest. Personal identity removed.",
    }

    # Add judgment profile if available
    try:
        from charter.analytics.judgment import generate_judgment_profile
        judgment = generate_judgment_profile(context=context_name)
        manifest["judgment_profile"] = judgment
    except Exception:
        manifest["judgment_profile"] = {"statements": []}

    # Re-sign with institutional scope marker
    manifest["scope"] = "role"
    manifest["signature"] = _sign_manifest(
        {k: v for k, v in manifest.items() if k != "signature"}
    )

    # Record in chain
    append_to_chain("role_manifest_exported", {
        "context": context_name,
        "role": role_label,
        "entity_count": gs.get("stats", {}).get("entity_count", 0),
    })

    return manifest


# ── Contextualization (Product 2: Intelligence Portability) ───────


def contextualize(incoming_manifest, local_manifest=None):
    """Map an incoming manifest against local Charter state.

    When someone arrives at a new organization with their intelligence
    layer, this finds overlap, complements, and conflicts between
    their context and the organization's existing context.

    Args:
        incoming_manifest: The arriving person's Context Manifest.
        local_manifest: Optional local manifest to compare against.
            If None, generates one from current state.

    Returns:
        dict with overlap, complements, conflicts, and a
        contextualization report the AI agent can use to prime itself.
    """
    if local_manifest is None:
        local_manifest = create_manifest(scope="institutional")

    incoming_gs = incoming_manifest.get("graph_snapshot", {})
    local_gs = local_manifest.get("graph_snapshot", {})

    # 1. Find overlapping entities (by name or email)
    incoming_entities = {
        e.get("name", "").lower(): e
        for e in incoming_gs.get("entities", [])
        if e.get("name")
    }
    incoming_emails = {
        e.get("email", "").lower(): e
        for e in incoming_gs.get("entities", [])
        if e.get("email")
    }
    local_entities = {
        e.get("name", "").lower(): e
        for e in local_gs.get("entities", [])
        if e.get("name")
    }
    local_emails = {
        e.get("email", "").lower(): e
        for e in local_gs.get("entities", [])
        if e.get("email")
    }

    overlaps = []
    for name, entity in incoming_entities.items():
        if name in local_entities:
            overlaps.append({
                "match_type": "name",
                "name": entity.get("name", ""),
                "incoming_type": entity.get("entity_type", ""),
                "local_type": local_entities[name].get(
                    "entity_type", ""
                ),
            })
    for email, entity in incoming_emails.items():
        if email and email in local_emails:
            name = entity.get("name", "")
            if name.lower() not in [o["name"].lower() for o in overlaps]:
                overlaps.append({
                    "match_type": "email",
                    "name": name,
                    "email": email,
                })

    # 2. Find complementary knowledge (incoming has, local doesn't)
    incoming_names = set(incoming_entities.keys())
    local_names = set(local_entities.keys())
    complement_names = incoming_names - local_names

    complements = []
    for name in list(complement_names)[:20]:
        entity = incoming_entities[name]
        complements.append({
            "name": entity.get("name", ""),
            "entity_type": entity.get("entity_type", ""),
            "context": entity.get("context", ""),
        })

    # 3. Find governance conflicts
    incoming_gov = incoming_manifest.get("governance_profile", {})
    local_gov = local_manifest.get("governance_profile", {})

    conflicts = []
    # Compare Layer A rules
    incoming_rules = set(
        str(r) for r in incoming_gov.get("layer_a", {}).get("rules", [])
    )
    local_rules = set(
        str(r) for r in local_gov.get("layer_a", {}).get("rules", [])
    )
    if incoming_rules != local_rules:
        only_incoming = incoming_rules - local_rules
        only_local = local_rules - incoming_rules
        if only_incoming or only_local:
            conflicts.append({
                "layer": "A",
                "type": "rule_difference",
                "only_in_incoming": list(only_incoming)[:5],
                "only_in_local": list(only_local)[:5],
            })

    # Compare domains
    if (incoming_gov.get("domain", "") !=
            local_gov.get("domain", "")):
        conflicts.append({
            "layer": "domain",
            "type": "domain_mismatch",
            "incoming": incoming_gov.get("domain", ""),
            "local": local_gov.get("domain", ""),
        })

    # 4. Build contextualization report
    incoming_id = incoming_manifest.get("identity", {})
    report_lines = []
    report_lines.append(
        "Incoming: {} (chain: {} entries)".format(
            incoming_id.get("alias", "unknown"),
            incoming_id.get("chain_length", 0),
        )
    )
    report_lines.append(
        "Overlap: {} shared entities".format(len(overlaps))
    )
    report_lines.append(
        "New knowledge: {} entities not in local graph".format(
            len(complements)
        )
    )
    report_lines.append(
        "Governance conflicts: {}".format(len(conflicts))
    )

    # Pattern comparison
    incoming_patterns = incoming_manifest.get(
        "pattern_declarations", {}
    ).get("declarations", [])
    if incoming_patterns:
        report_lines.append(
            "Behavioral patterns: {} declarations".format(
                len(incoming_patterns)
            )
        )
        for p in incoming_patterns[:3]:
            report_lines.append("  - {}".format(p.get("statement", "")))

    return {
        "overlapping_entities": overlaps,
        "complementary_knowledge": complements,
        "governance_conflicts": conflicts,
        "overlap_count": len(overlaps),
        "complement_count": len(complements),
        "conflict_count": len(conflicts),
        "report": "\n".join(report_lines),
        "recommendation": _contextualization_recommendation(
            overlaps, complements, conflicts
        ),
    }


def _contextualization_recommendation(overlaps, complements, conflicts):
    """Generate a plain-language recommendation from contextualization."""
    parts = []

    if overlaps:
        parts.append(
            "{} shared contacts/entities provide immediate common ground."
            .format(len(overlaps))
        )

    if complements:
        parts.append(
            "{} new entities represent knowledge this person brings "
            "that the organization doesn't currently have.".format(
                len(complements)
            )
        )

    if conflicts:
        parts.append(
            "{} governance differences need resolution before "
            "full context integration.".format(len(conflicts))
        )

    if not parts:
        parts.append("No significant overlap or conflicts detected.")

    return " ".join(parts)


# ── Merkle Anchoring ──────────────────────────────────────────────


def get_manifest_anchor(manifest):
    """Find the Merkle proof for a manifest's export event in the chain.

    When a manifest is exported, a manifest_exported event is appended
    to the chain containing the manifest hash. Once that entry is
    Merkle-batched, this function returns a proof that the manifest
    existed at a specific time, verifiable by anyone with access to
    the Merkle root.

    Args:
        manifest: The Context Manifest dict.

    Returns:
        dict with chain_index, merkle_proof, and anchor metadata,
        or None if not yet anchored.
    """
    # Compute the manifest hash that was recorded in the chain
    manifest_copy = {
        k: v for k, v in manifest.items() if k != "signature"
    }
    target_hash = hashlib.sha256(
        json.dumps(
            manifest_copy, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()[:32]

    # Find the manifest_exported event in the chain
    chain_path = get_chain_path()
    if not os.path.isfile(chain_path):
        return None

    target_index = None
    target_entry_hash = None
    target_line_num = None
    with open(chain_path) as f:
        for line_num, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("event") != "manifest_exported":
                continue
            data = entry.get("data", {})
            if data.get("manifest_hash") == target_hash:
                target_index = entry.get("index")
                target_entry_hash = entry.get("hash")
                target_line_num = line_num
                # Take the latest match
    if target_index is None:
        return None

    # Try to get a Merkle proof for this entry. Look up by entry hash
    # because chain indices are not globally unique on chains that have
    # been contaminated by foreign writers in the past.
    try:
        from charter.merkle import generate_proof
        proof = generate_proof(
            chain_index=target_index,
            entry_hash=target_entry_hash,
        )
    except Exception:
        proof = None

    if proof is None:
        return {
            "anchored": False,
            "chain_index": target_index,
            "chain_line": target_line_num,
            "entry_hash": target_entry_hash,
            "manifest_hash": target_hash,
            "note": (
                "Manifest export recorded in chain but not yet "
                "Merkle-batched. Run 'charter merkle batch' to "
                "anchor it, or wait for the next scheduled batch."
            ),
        }

    return {
        "anchored": True,
        "chain_index": target_index,
        "chain_line": target_line_num,
        "entry_hash": target_entry_hash,
        "manifest_hash": target_hash,
        "merkle_root": proof["merkle_root"],
        "merkle_proof": proof["proof"],
        "batch_id": proof["batch_id"],
        "leaf_hash": proof["leaf_hash"],
        "verification": proof["verification"],
    }


def verify_manifest_anchor(manifest, expected_root=None):
    """Verify a manifest's Merkle anchor.

    Independently verifies that a manifest existed at the time
    its chain entry was anchored. Optionally checks against a
    known Merkle root.

    Args:
        manifest: The Context Manifest dict.
        expected_root: Optional expected Merkle root to compare.

    Returns:
        dict with valid (bool), checks (list), errors (list).
    """
    anchor = get_manifest_anchor(manifest)
    checks = []
    errors = []

    if anchor is None:
        errors.append(
            "no chain entry found for this manifest hash"
        )
        return {
            "valid": False, "checks": checks, "errors": errors,
        }

    if not anchor.get("anchored"):
        checks.append(
            "chain entry exists at index {}".format(
                anchor["chain_index"]
            )
        )
        errors.append(
            "manifest not yet Merkle-anchored "
            "(batch pending)"
        )
        return {
            "valid": False, "checks": checks, "errors": errors,
        }

    checks.append(
        "chain entry at index {}".format(anchor["chain_index"])
    )
    checks.append(
        "Merkle root: {}".format(anchor["merkle_root"][:24])
    )
    checks.append(
        "proof length: {} hash operations".format(
            len(anchor["merkle_proof"])
        )
    )

    if expected_root and anchor["merkle_root"] != expected_root:
        errors.append(
            "merkle root mismatch (expected {}, got {})".format(
                expected_root[:16], anchor["merkle_root"][:16]
            )
        )
    elif expected_root:
        checks.append("merkle root matches expected")

    return {
        "valid": len(errors) == 0,
        "checks": checks,
        "errors": errors,
        "anchor": anchor,
    }


# ── Export/Import ─────────────────────────────────────────────────


def export_manifest(manifest, output_path):
    """Write a manifest to a JSON file.

    Args:
        manifest: The manifest dict.
        output_path: File path to write to.

    Returns:
        dict with path and size.
    """
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)

    size = os.path.getsize(output_path)
    return {"path": output_path, "size_bytes": size}


def import_manifest(manifest_path):
    """Load a manifest from a JSON file and verify it.

    Args:
        manifest_path: Path to the manifest JSON file.

    Returns:
        dict with manifest and verification result.
    """
    with open(manifest_path) as f:
        manifest = json.load(f)

    verification = verify_manifest(manifest)

    # Record import in chain
    append_to_chain("manifest_imported", {
        "source_path": manifest_path,
        "scope": manifest.get("scope", ""),
        "source_identity": manifest.get("identity", {}).get("public_id", "")[:16],
        "entity_count": manifest.get("graph_snapshot", {}).get("stats", {}).get("entity_count", 0),
        "valid": verification["valid"],
    })

    return {
        "manifest": manifest,
        "verification": verification,
    }


# ── Private: Build Blocks ─────────────────────────────────────────


def _build_identity_block():
    """Build the identity section of the manifest."""
    identity = load_identity()
    if not identity:
        return {
            "public_id": "",
            "alias": "",
            "chain_hash": "",
            "verified": False,
            "charter_version": MANIFEST_VERSION,
        }

    # Get the latest chain hash for provenance anchor
    chain_hash = ""
    chain_path = get_chain_path()
    if os.path.isfile(chain_path):
        with open(chain_path) as f:
            lines = f.readlines()
            if lines:
                last = json.loads(lines[-1])
                chain_hash = last.get("hash", "")

    verified = bool(identity.get("real_identity"))
    block = {
        "public_id": identity.get("public_id", ""),
        "alias": identity.get("alias", ""),
        "chain_hash": chain_hash,
        "chain_length": len(open(chain_path).readlines()) if os.path.isfile(chain_path) else 0,
        "verified": verified,
        "charter_version": MANIFEST_VERSION,
        "created_at": identity.get("created_at", ""),
    }

    if verified:
        ri = identity["real_identity"]
        block["verified_name"] = ri.get("name", "")
        block["verified_email"] = ri.get("email", "")
        block["trust_level"] = ri.get("trust_level", "")

    return block


def _build_graph_snapshot(context=None, since=None):
    """Build the graph snapshot section.

    Attempts to import and use the graph memory engine.
    Falls back gracefully if not available.
    """
    try:
        sys.path.insert(0, os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        ))
        from core.graph_memory.engine import GraphMemory
        gm = GraphMemory()
        snapshot = gm.export_snapshot(context=context, since=since)
        gm.close()
        return snapshot
    except Exception as e:
        return {
            "@context": "https://schema.charteragent.ai/manifest/v1",
            "@type": "GraphSnapshot",
            "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "entities": [],
            "relationships": [],
            "interactions": [],
            "stats": {
                "entity_count": 0,
                "relationship_count": 0,
                "interaction_count": 0,
                "error": str(e),
            },
        }


def _build_decision_log(actor_id=None, context=None, since=None):
    """Build the decision log from the hash chain."""
    try:
        from charter.chain_graph_link import load_chain, extract_decision_log
        entries = load_chain()
        return extract_decision_log(
            entries, actor_id=actor_id, context=context, since=since,
        )
    except Exception as e:
        return [{"error": str(e)}]


def _build_pattern_declarations(actor=None, underused_threshold=None):
    """Build pattern declarations from the analytics engine.

    Includes bias-by-absence declarations from analytics.absence so the
    role intelligence + fresh perspective output surfaces what was NOT
    done alongside what was done. Absence declarations are appended to
    the same list with type='absence' and carry their own confidence
    and caveat fields.
    """
    declarations = []
    source_metrics = {}
    error = None

    try:
        from charter.analytics.patterns import PatternEngine
        pe = PatternEngine(auto_sync=True)
        result = pe.declare_patterns(actor=actor)
        pe.close()
        declarations.extend(result.get("declarations", []) or [])
        source_metrics = result.get("source_metrics", {}) or {}
    except Exception as e:
        error = str(e)

    # Append bias-by-absence declarations.
    absence_summary = None
    try:
        from charter.analytics.absence import (
            declare_absence, DEFAULT_UNDERUSED_THRESHOLD,
        )
        absence = declare_absence(
            actor=actor,
            underused_threshold=(
                underused_threshold
                if underused_threshold is not None
                else DEFAULT_UNDERUSED_THRESHOLD
            ),
        )
        declarations.extend(absence.get("declarations", []) or [])
        absence_summary = {
            "declaration_count": absence.get("declaration_count", 0),
            "detectors": absence.get("detectors", {}),
        }
    except Exception as e:
        absence_summary = {"error": str(e)}

    out = {
        "declarations": declarations,
        "declaration_count": len(declarations),
        "actor": actor or "organization",
        "source_metrics": source_metrics,
    }
    if absence_summary is not None:
        out["absence_summary"] = absence_summary
    if error:
        out["error"] = error
    return out


def _build_governance_profile(config_path=None):
    """Build the governance profile from charter.yaml."""
    config = load_config(path=config_path)
    if not config:
        return {
            "domain": "unknown",
            "layer_a": {"universal": [], "rules": []},
            "layer_b": [],
            "layer_c": {},
            "compliance_frameworks": [],
        }

    gov = config.get("governance", {})
    layer_a = gov.get("layer_a", {})
    layer_b = gov.get("layer_b", {})
    layer_c = gov.get("layer_c", {})

    # Extract compliance frameworks if mapped
    frameworks = []
    try:
        from charter.compliance import ComplianceMapper
        mapper = ComplianceMapper(config)
        for std in ["hipaa", "sox", "gdpr", "eu_ai_act", "nist_ai_rmf"]:
            try:
                result = mapper.map_standard(std)
                if result.get("coverage_pct", 0) > 0:
                    frameworks.append({
                        "standard": std,
                        "coverage_pct": result.get("coverage_pct", 0),
                    })
            except Exception:
                pass
    except Exception:
        pass

    return {
        "domain": config.get("domain", "general"),
        "layer_a": {
            "universal": layer_a.get("universal", []),
            "rules": layer_a.get("rules", []),
        },
        "layer_b": layer_b.get("rules", []) if isinstance(layer_b, dict) else [],
        "layer_c": {
            "frequency": layer_c.get("frequency", "") if isinstance(layer_c, dict) else "",
            "report_includes": layer_c.get("report_includes", []) if isinstance(layer_c, dict) else [],
        },
        "kill_triggers": gov.get("kill_triggers", []),
        "compliance_frameworks": frameworks,
    }


def _sign_manifest(manifest_data):
    """Sign the manifest with the local identity's private seed."""
    identity = load_identity()
    if not identity or not identity.get("private_seed"):
        return ""
    return sign_data(manifest_data, identity["private_seed"])


# ── CLI Entry Point ───────────────────────────────────────────────


def run_manifest(args):
    """CLI handler for `charter manifest` subcommand."""
    action = args.action

    if action == "export":
        scope = getattr(args, "scope", "individual")
        context = getattr(args, "context", None)
        since = getattr(args, "since", None)
        output = getattr(args, "output", None)

        print("Generating Context Manifest...")
        print("  Scope: {}".format(scope))
        if context:
            print("  Context: {}".format(context))
        if since:
            print("  Since: {}".format(since))
        print()

        manifest = create_manifest(
            scope=scope, context_name=context, since=since,
        )

        # Default output path
        if not output:
            ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
            output = "charter_manifest_{}_{}.json".format(scope, ts)

        result = export_manifest(manifest, output)

        # Summary
        gs = manifest.get("graph_snapshot", {}).get("stats", {})
        pd = manifest.get("pattern_declarations", {})
        dl = manifest.get("decision_log", [])

        print("Context Manifest exported successfully.")
        print("=" * 50)
        print("  Scope:        {}".format(manifest.get("scope", "")))
        print("  Identity:     {}".format(
            manifest.get("identity", {}).get("alias", "unknown")))
        print("  Verified:     {}".format(
            manifest.get("identity", {}).get("verified", False)))
        print("  Entities:     {}".format(gs.get("entity_count", 0)))
        print("  Relationships:{}".format(gs.get("relationship_count", 0)))
        print("  Interactions: {}".format(gs.get("interaction_count", 0)))
        print("  Decisions:    {}".format(len(dl)))
        print("  Patterns:     {}".format(pd.get("declaration_count", 0)))
        print("  Signed:       {}".format(bool(manifest.get("signature"))))
        print()
        print("  Output: {}".format(result["path"]))
        print("  Size:   {} bytes".format(result["size_bytes"]))

    elif action == "verify":
        path = args.path
        if not os.path.isfile(path):
            print("Error: File not found: {}".format(path))
            return

        result = import_manifest(path)
        verification = result["verification"]

        print("Context Manifest Verification")
        print("=" * 50)
        print("  Valid: {}".format(verification["valid"]))
        print("  Scope: {}".format(verification.get("scope", "")))
        print("  Generated: {}".format(verification.get("generated_at", "")))
        print()

        if verification["checks"]:
            print("  Checks passed:")
            for check in verification["checks"]:
                print("    [ok] {}".format(check))

        if verification["errors"]:
            print()
            print("  Errors:")
            for error in verification["errors"]:
                print("    [!!] {}".format(error))

    elif action == "import":
        path = args.path
        if not os.path.isfile(path):
            print("Error: File not found: {}".format(path))
            return

        result = import_manifest(path)
        manifest = result["manifest"]
        verification = result["verification"]

        if not verification["valid"]:
            print("Warning: Manifest has verification errors:")
            for error in verification["errors"]:
                print("  [!!] {}".format(error))
            print()

        gs = manifest.get("graph_snapshot", {}).get("stats", {})
        identity = manifest.get("identity", {})

        print("Context Manifest imported.")
        print("=" * 50)
        print("  Source:       {}".format(identity.get("alias", "unknown")))
        print("  Public ID:    {}...".format(identity.get("public_id", "")[:16]))
        print("  Scope:        {}".format(manifest.get("scope", "")))
        print("  Entities:     {}".format(gs.get("entity_count", 0)))
        print("  Decisions:    {}".format(len(manifest.get("decision_log", []))))
        print("  Valid:        {}".format(verification["valid"]))
        print()
        print("  Recorded in chain as manifest_imported event.")

    elif action == "role-export":
        context = getattr(args, "context", None)
        role = getattr(args, "role", None)
        since = getattr(args, "since", None)
        output = getattr(args, "output", None)

        if not context:
            print("Error: --context required for role-export")
            return

        print("Generating Role Manifest...")
        print("  Context: {}".format(context))
        if role:
            print("  Role: {}".format(role))
        print()

        manifest = generate_role_manifest(
            context_name=context,
            role_name=role,
            since=since,
        )

        if not output:
            ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
            output = "charter_role_manifest_{}.json".format(ts)

        result = export_manifest(manifest, output)
        gs = manifest.get("graph_snapshot", {}).get("stats", {})
        jp = manifest.get("judgment_profile", {})

        print("Role Manifest exported (de-personalized).")
        print("=" * 50)
        print("  Role:         {}".format(
            manifest.get("role", {}).get("name", "unknown")))
        print("  Context:      {}".format(context))
        print("  Entities:     {}".format(gs.get("entity_count", 0)))
        print("  Decisions:    {}".format(
            len(manifest.get("decision_log", []))))
        print("  Judgment:     {} statements".format(
            jp.get("statement_count", 0)))
        print("  De-personal:  Yes")
        print()
        print("  Output: {}".format(result["path"]))

    elif action == "adapt":
        platform = getattr(args, "platform", None)
        output = getattr(args, "output", None)
        source = (getattr(args, "path", None)
                  or getattr(args, "input", None))

        if not platform:
            print("Error: --platform required for adapt")
            return
        if not source or not os.path.isfile(source):
            print("Error: manifest file path required")
            return
        if not output:
            output = "./charter_adapted_{}".format(platform)

        with open(source) as f:
            manifest = json.load(f)

        from charter.adapters import get_adapter
        adapter = get_adapter(platform)
        result = adapter.adapt(manifest, output)

        print("Manifest adapted for {}.".format(platform))
        print("=" * 50)
        for name, path in result.get("files", {}).items():
            size = os.path.getsize(path)
            print("  {} ({} bytes)".format(name, size))
        print()
        print("  Output: {}".format(result["output_dir"]))

    elif action == "contextualize":
        source = (getattr(args, "path", None)
                  or getattr(args, "input", None))
        if not source or not os.path.isfile(source):
            print("Error: incoming manifest file path required")
            return

        with open(source) as f:
            incoming = json.load(f)

        print("Contextualizing incoming manifest...")
        print()

        result = contextualize(incoming)

        print("Contextualization Report")
        print("=" * 50)
        print(result["report"])
        print()
        print("Recommendation:")
        print("  {}".format(result["recommendation"]))
        print()
        print("  Overlapping entities: {}".format(
            result["overlap_count"]))
        print("  New knowledge:        {}".format(
            result["complement_count"]))
        print("  Governance conflicts: {}".format(
            result["conflict_count"]))

    elif action == "anchor":
        source = (getattr(args, "path", None)
                  or getattr(args, "input", None))
        if not source or not os.path.isfile(source):
            print("Error: manifest file path required")
            return

        with open(source) as f:
            manifest = json.load(f)

        anchor = get_manifest_anchor(manifest)
        if anchor is None:
            print("No chain entry found for this manifest.")
            print("It may not have been exported by this Charter.")
            return

        print("Manifest Merkle Anchor")
        print("=" * 50)
        print("  Manifest hash: {}...".format(
            anchor["manifest_hash"][:24]))
        print("  Chain index:   {}".format(anchor["chain_index"]))
        print("  Chain entry:   {}...".format(
            (anchor.get("entry_hash") or "")[:24]))
        print()

        if anchor.get("anchored"):
            print("  Status:        ANCHORED")
            print("  Merkle root:   {}...".format(
                anchor["merkle_root"][:24]))
            print("  Batch:         {}".format(anchor["batch_id"]))
            print("  Proof length:  {} hash operations".format(
                len(anchor["merkle_proof"])))
            print()
            print("  This manifest can be independently verified by")
            print("  anyone with access to the Merkle root.")
        else:
            print("  Status:        NOT YET ANCHORED")
            print("  Note:          {}".format(anchor.get("note", "")))
            print()
            print("  Run: charter merkle batch")

    elif action == "schema":
        output = getattr(args, "output", None)
        schema_path = os.path.join(
            os.path.dirname(__file__),
            "templates", "manifest-schema.jsonld",
        )
        if not os.path.isfile(schema_path):
            print("Error: schema file not found at {}".format(
                schema_path))
            return
        with open(schema_path) as f:
            schema = f.read()
        if output:
            with open(output, "w") as f:
                f.write(schema)
            print("Schema written to: {}".format(output))
        else:
            print(schema)

    elif action == "verify-anchor":
        source = (getattr(args, "path", None)
                  or getattr(args, "input", None))
        if not source or not os.path.isfile(source):
            print("Error: manifest file path required")
            return

        with open(source) as f:
            manifest = json.load(f)

        result = verify_manifest_anchor(manifest)
        print("Manifest Anchor Verification")
        print("=" * 50)
        print("  Valid: {}".format(result["valid"]))
        print()
        for check in result["checks"]:
            print("    [ok] {}".format(check))
        for error in result["errors"]:
            print("    [!!] {}".format(error))

    else:
        print("Usage: charter manifest <action>")
        print()
        print("  export          Generate a Context Manifest")
        print("  verify          Verify a manifest file")
        print("  import          Import a manifest into local Charter")
        print("  role-export     Export de-personalized role manifest")
        print("  adapt           Adapt manifest for a platform")
        print("  contextualize   Map incoming manifest against local")
        print("  anchor          Show manifest's Merkle anchor proof")
        print("  verify-anchor   Verify a manifest's Merkle anchor")
        print("  schema          Print or save the JSON-LD schema")
