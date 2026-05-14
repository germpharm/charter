"""Pseudonymous identity management with hash chain."""

import hashlib
import json
import os
import time
import secrets

from charter.paths import chain_write_lock, get_charter_home


IDENTITY_DIR = ".charter"
IDENTITY_FILE = "identity.json"
CHAIN_FILE = "chain.jsonl"


def get_identity_dir():
    """Get the active Charter home directory.

    Resolves through `charter.paths.get_charter_home()` so multi-tenant
    deployments can scope each request to a tenant-specific directory
    via ContextVar without changing the rest of the codebase. Single-tenant
    local installs see exactly the same path as before (~/.charter).
    """
    return get_charter_home()


def get_identity_path():
    return os.path.join(get_identity_dir(), IDENTITY_FILE)


def get_chain_path():
    return os.path.join(get_identity_dir(), CHAIN_FILE)


def get_project_chain_path(project_path=None):
    """Get the chain path for a specific project.

    If project_path is provided, returns a per-project chain path
    at ~/.charter/chains/<project_hash>.jsonl.
    If None, falls back to the global chain.

    The project_hash is SHA-256 of the absolute project path.
    """
    if project_path is None:
        return get_chain_path()

    abs_path = os.path.abspath(project_path)
    project_hash = hashlib.sha256(abs_path.encode()).hexdigest()
    chains_dir = os.path.join(get_identity_dir(), "chains")
    os.makedirs(chains_dir, exist_ok=True)
    return os.path.join(chains_dir, f"{project_hash}.jsonl")


def get_project_hash(project_path):
    """Compute the project hash from a path."""
    abs_path = os.path.abspath(project_path)
    return hashlib.sha256(abs_path.encode()).hexdigest()


def register_project(project_path, project_name=None):
    """Register a project in the global chain and create its chain file.

    Records a project_registered event in the global root chain,
    and creates the per-project chain file if it doesn't exist.

    Returns the project hash.
    """
    abs_path = os.path.abspath(project_path)
    project_hash = get_project_hash(project_path)
    chain_path = get_project_chain_path(project_path)

    # Create project chain with genesis entry if it doesn't exist
    if not os.path.isfile(chain_path):
        identity = load_identity()
        if not identity:
            return None
        genesis = {
            "index": 0,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": "project_chain_created",
            "data": {
                "project_hash": project_hash,
                "project_path": abs_path,
                "project_name": project_name or os.path.basename(abs_path),
            },
            "actor": "collaborative",
            "actor_id": get_active_actor(),
            "previous_hash": "0" * 64,
        }
        genesis["hash"] = hash_entry(genesis)
        with open(chain_path, "w") as f:
            f.write(json.dumps(genesis) + "\n")

    # Register in global chain
    append_to_chain("project_registered", {
        "project_hash": project_hash,
        "project_path": abs_path,
        "project_name": project_name or os.path.basename(abs_path),
        "chain_file": chain_path,
    }, actor="collaborative")

    return project_hash


def list_project_chains():
    """List all registered project chains.

    Returns a list of dicts with project_hash, chain_path,
    and entry count for each project chain.
    """
    chains_dir = os.path.join(get_identity_dir(), "chains")
    if not os.path.isdir(chains_dir):
        return []

    projects = []
    for filename in os.listdir(chains_dir):
        if not filename.endswith(".jsonl"):
            continue
        chain_path = os.path.join(chains_dir, filename)
        project_hash = filename.replace(".jsonl", "")

        entry_count = 0
        project_name = None
        with open(chain_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    entry_count += 1
                    if entry_count == 1:
                        try:
                            genesis = json.loads(line)
                            project_name = genesis.get("data", {}).get("project_name")
                        except json.JSONDecodeError:
                            pass

        projects.append({
            "project_hash": project_hash,
            "chain_path": chain_path,
            "entry_count": entry_count,
            "project_name": project_name,
        })

    return projects


def create_identity(alias=None):
    """Create a new pseudonymous identity.

    Identity is a SHA-256 hash of random bytes + timestamp.
    No external dependencies. Pseudonymous until the user
    chooses to link a real identity.
    """
    id_dir = get_identity_dir()
    os.makedirs(id_dir, exist_ok=True)

    # Generate identity key from random bytes
    seed = secrets.token_bytes(32) + str(time.time_ns()).encode()
    public_id = hashlib.sha256(seed).hexdigest()

    # Store the seed for future signing
    private_seed = secrets.token_hex(32)

    identity = {
        "version": "1.0",
        "public_id": public_id,
        "private_seed": private_seed,
        "alias": alias or f"node-{public_id[:8]}",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "real_identity": None,  # Linked later when user validates
        "contributions": 0,
    }

    with open(get_identity_path(), "w") as f:
        json.dump(identity, f, indent=2)

    # Initialize the hash chain with genesis entry. Must include `signer`,
    # `actor`, and `actor_id` so the v3.4.0 walk-backwards guard in
    # append_to_chain (which skips entries lacking the Charter schema to
    # avoid linking to foreign writers) recognizes the genesis as our own.
    # Without these fields, every new user's chain would be stuck at
    # index 0 — append_to_chain would skip the genesis, default to
    # previous_hash="0"*64 and index=0, and the next entry would
    # overwrite the chain head.
    genesis = {
        "index": 0,
        "timestamp": identity["created_at"],
        "event": "identity_created",
        "data": {"public_id": public_id, "alias": identity["alias"]},
        "actor": "human",
        "actor_id": identity["alias"],
        "previous_hash": "0" * 64,
        "signer": public_id,
    }
    genesis["hash"] = hash_entry(genesis)

    with open(get_chain_path(), "w") as f:
        f.write(json.dumps(genesis) + "\n")

    return identity


def load_identity():
    """Load existing identity or return None."""
    path = get_identity_path()
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return json.load(f)


def hash_entry(entry):
    """Compute SHA-256 hash of a chain entry."""
    # Hash everything except the hash and signature fields.
    # The hash is the field we're computing; the signature is
    # added after the hash, so it must be excluded to get the
    # same result during verification.
    content = {k: v for k, v in entry.items() if k not in ("hash", "signature")}
    raw = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def sign_data(data, private_seed):
    """Sign data with the private seed. Returns a hex signature.

    This is HMAC-SHA256 using the private seed as key.
    Simple, no external dependencies, cryptographically sound
    for proving ownership of the identity.
    """
    import hmac
    raw = json.dumps(data, sort_keys=True, separators=(",", ":"))
    sig = hmac.new(
        bytes.fromhex(private_seed),
        raw.encode(),
        hashlib.sha256,
    ).hexdigest()
    return sig


VALID_ACTORS = ("human", "ai", "collaborative")


def get_active_actor():
    """Return a stable identifier for whoever is currently running Charter.

    The returned string is the operator-level identity id used by the
    analytics layer (events.actor_id) to attribute work back to a real
    person across the 3-value chain `actor` enum (human/ai/collaborative).

    Resolution order:
        1. If real_identity is verified and has a `name`, return the
           lowercased first token (e.g. "Matthew Maughan" -> "matthew").
           This is the human-readable handle the bias-detection module
           and most CLI flags use.
        2. Otherwise return the alias from identity.json (e.g.
           "node-93921f61"), which is stable across the lifetime of the
           identity even before verification.
        3. If no identity exists at all, return "unknown".

    This helper is intentionally cheap — it reads identity.json on every
    call so a single long-lived process picks up identity changes
    (verification, alias updates) without restart.
    """
    identity = load_identity()
    if not identity:
        return "unknown"
    real = identity.get("real_identity") or {}
    name = real.get("name") if isinstance(real, dict) else None
    if name:
        first = str(name).strip().split()[0] if str(name).strip() else ""
        if first:
            return first.lower()
    alias = identity.get("alias")
    if alias:
        return alias
    pub = identity.get("public_id") or ""
    return "node-{}".format(pub[:8]) if pub else "unknown"


# Sentinel used to distinguish "caller passed None explicitly" (or not at
# all) from "caller passed a real value". When we see _ACTOR_UNSET we
# know the call site never specified actor and we should both default
# to "collaborative" AND emit a regression warning so the gap surfaces
# in the next session.
_ACTOR_UNSET = object()


def _warn_unattributed_append(event):
    """Print a one-line stderr warning when a write site forgets actor.

    Non-fatal — never raises. The point is to make the regression
    visible to whoever is running Charter so the call site gets a
    proper actor= argument added in a follow-up edit. We rate-limit
    by event-type so a connector emitting 10k events of the same
    kind doesn't flood the terminal.
    """
    import sys
    seen = getattr(_warn_unattributed_append, "_seen", None)
    if seen is None:
        seen = set()
        _warn_unattributed_append._seen = seen
    if event in seen:
        return
    seen.add(event)
    sys.stderr.write(
        "[charter] WARNING: append_to_chain('{}') called without "
        "actor= — defaulting to 'collaborative'. This is a Layer 0 "
        "regression and the call site should be updated.\n".format(event)
    )


def append_to_chain(event, data, auto_batch=True,
                    confidence=None, evidence_basis=None,
                    constraint_assumptions=None,
                    revision_of=None, revision_reason=None,
                    actor=_ACTOR_UNSET, edges=None,
                    project_path=None,
                    actor_id=None):
    """Append a new entry to the hash chain.

    If auto_batch is True and enough unbatched entries have accumulated,
    automatically rolls them into a Merkle tree. The threshold is
    controlled by MERKLE_AUTO_BATCH_SIZE.

    Args:
        actor: Required (v3.1.1 Layer 0 invariant #7). One of "human",
            "ai", or "collaborative". Indicates who performed this action.
            Included in the hash computation so it cannot be altered
            after the fact. Defaults to "collaborative" only for
            backward compatibility — callers should always specify.

        edges: Optional list of graph edges (v3.1.1). Each edge is a
            dict with "type" and "hash" keys. Valid types: caused_by,
            revision_of, input_to, part_of, approved_by. Edges are
            included in the hash computation — once signed, relationships
            are immutable.

    Optional confidence tagging (v2.2.0):
        confidence: "verified" | "inferred" | "exploratory"
        evidence_basis: str describing what evidence supports this decision
        constraint_assumptions: list of assumptions that must remain true
        revision_of: hash of a prior entry this revises
        revision_reason: why the prior conclusion changed
    """
    # v3.1.1: Actor attribution is a Layer 0 invariant.
    # Default to "collaborative" for backward compatibility,
    # but callers should always specify explicitly. The
    # _ACTOR_UNSET sentinel lets us tell the difference between
    # "caller passed None" and "caller didn't pass actor at all"
    # so the regression warning fires only on the latter.
    if actor is _ACTOR_UNSET:
        _warn_unattributed_append(event)
        actor = "collaborative"
    if actor is None:
        actor = "collaborative"
    if actor not in VALID_ACTORS:
        actor = "collaborative"

    # v3.1.2: actor_id is the operator-level identity (e.g., "matt")
    # that produced this entry. Layer 0 enum stays a 3-value role,
    # actor_id carries the richer who-did-this label that downstream
    # analytics (bias-detection-by-absence) needs to attribute work
    # back to a specific person across multi-tenant chains. Defaults
    # to the active identity from identity.json so every new entry
    # is attributed without requiring callers to thread the value.
    if actor_id is None:
        actor_id = get_active_actor()
    chain_path = get_project_chain_path(project_path)
    identity = load_identity()
    if not identity:
        return None

    # Enrich data with confidence metadata if provided
    if confidence or evidence_basis or constraint_assumptions or revision_of:
        data = dict(data)  # shallow copy to avoid mutating caller's dict
        if confidence:
            data["_confidence"] = confidence
        if evidence_basis:
            data["_evidence_basis"] = evidence_basis
        if constraint_assumptions:
            data["_constraint_assumptions"] = constraint_assumptions
        if revision_of:
            data["_revision_of"] = revision_of
        if revision_reason:
            data["_revision_reason"] = revision_reason

    # Hold an advisory lock around the read-modify-write so concurrent writers
    # (multi-tenant workers, a Mini sync job overlapping a live append) cannot
    # interleave. The tail read MUST be inside the lock — otherwise two writers
    # compute the same previous_hash and double-write at the same index. The
    # lock file lives next to the chain and inherits its tenant scope.
    with chain_write_lock(chain_path):
        # Read last entry to get previous hash. Walk backwards to skip any
        # foreign entries that lack the Charter schema (no `index`,
        # `previous_hash`, or `signer`). Defensive: if a parallel writer ever
        # appends to chain.jsonl with its own format, our chain still links
        # cleanly to the most recent legitimate Charter entry instead of
        # taking a foreign hash as previous_hash and resetting the index
        # counter to 1. See tools/charter_migration/migrate_chain.py for the
        # historical incident that motivated this guard.
        last_hash = "0" * 64
        index = 0
        if os.path.isfile(chain_path):
            with open(chain_path) as f:
                lines = f.readlines()
            for raw in reversed(lines):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    candidate = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if (
                    "index" in candidate
                    and "previous_hash" in candidate
                    and "signer" in candidate
                ):
                    last_hash = candidate.get("hash", "0" * 64)
                    index = candidate.get("index", 0) + 1
                    break

        entry = {
            "index": index,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "data": data,
            "actor": actor,
            "actor_id": actor_id,
            "previous_hash": last_hash,
            "signer": identity["public_id"],
        }

        # v3.1.1: Graph edges — immutable relationships between entries.
        # Included in hash computation so they cannot be altered after signing.
        if edges:
            _VALID_EDGE_TYPES = ("caused_by", "revision_of", "input_to", "part_of", "approved_by")
            validated_edges = []
            for edge in edges:
                if isinstance(edge, dict) and edge.get("type") in _VALID_EDGE_TYPES and edge.get("hash"):
                    validated_edges.append({"type": edge["type"], "hash": edge["hash"]})
            if validated_edges:
                entry["_edges"] = validated_edges

        entry["hash"] = hash_entry(entry)
        entry["signature"] = sign_data(entry, identity["private_seed"])

        with open(chain_path, "a") as f:
            f.write(json.dumps(entry) + "\n")

        # Update contribution count
        identity["contributions"] = index
        with open(get_identity_path(), "w") as f:
            json.dump(identity, f, indent=2)

    # Auto-batch into Merkle tree when threshold is reached
    if auto_batch:
        try:
            from charter.merkle import batch_chain_entries
            batch_chain_entries(
                chain_path,
                batch_size=MERKLE_AUTO_BATCH_SIZE,
                min_entries=MERKLE_AUTO_BATCH_SIZE,
            )
        except Exception:
            pass  # Merkle batching is non-critical; never block chain append

    return entry


# Merkle tree auto-batching threshold.
# When this many unbatched chain entries accumulate, they are
# automatically rolled into a Merkle tree. 256 is optimal for
# binary trees and keeps proof paths to 8 steps.
MERKLE_AUTO_BATCH_SIZE = 256


def verify_identity(name, email, method="manual", verification_token=None):
    """Link a real identity to the pseudonymous identity.

    This is the authorship transfer. All prior hash chain entries
    were signed by the same private seed. The chain proves continuity
    from genesis (pseudonymous) through verification (real identity).

    After verification, every contribution in the chain is attributable
    to the verified person. The chain itself is the proof.

    Methods:
        id_me: Government ID verification via ID.me
        org_hr: Organizational HR system verification
        email: Email verification (basic)
        manual: Self-declared (lowest trust level)
    """
    identity = load_identity()
    if not identity:
        raise RuntimeError("No identity found. Run 'charter init' first.")

    if identity.get("real_identity"):
        raise RuntimeError(
            f"Identity already verified as: {identity['real_identity']['name']}. "
            "Transfer already complete."
        )

    # Build the verification record
    verification = {
        "name": name,
        "email": email,
        "method": method,
        "verification_token": verification_token,
        "verified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "trust_level": {
            "id_me": "government",
            "persona": "government_id",
            "org_hr": "organizational",
            "email": "basic",
            "manual": "self_declared",
        }.get(method, "self_declared"),
    }

    # Count prior contributions for the transfer proof
    chain_path = get_chain_path()
    prior_entries = 0
    if os.path.isfile(chain_path):
        with open(chain_path) as f:
            prior_entries = sum(1 for line in f if line.strip())

    # Record the verification event in the chain
    # This is the pivotal entry: everything before it was pseudonymous,
    # everything from here forward is verified. The chain links them.
    transfer_data = {
        "real_identity": {
            "name": name,
            "email": email,
        },
        "method": method,
        "trust_level": verification["trust_level"],
        "prior_entries_transferred": prior_entries,
        "transfer_proof": (
            f"All {prior_entries} chain entries prior to this verification "
            f"were signed by public_id {identity['public_id']}. "
            f"This identity is now verified as {name} ({email}) "
            f"via {method}. The unbroken chain from genesis to this entry "
            f"proves authorship of all prior work."
        ),
    }
    append_to_chain("identity_verified", transfer_data)

    # Update the identity file
    identity["real_identity"] = verification
    with open(get_identity_path(), "w") as f:
        json.dump(identity, f, indent=2)

    return verification, prior_entries


def generate_transfer_proof():
    """Generate a standalone proof document showing the authorship chain.

    This proof can be shared with anyone to demonstrate that:
    1. A pseudonymous identity created work (chain entries)
    2. That identity was later verified as a real person
    3. The chain is unbroken from genesis to verification
    4. Therefore all work belongs to the verified person
    """
    identity = load_identity()
    if not identity:
        return None

    chain_path = get_chain_path()
    if not os.path.isfile(chain_path):
        return None

    with open(chain_path) as f:
        entries = [json.loads(line) for line in f if line.strip()]

    # Verify chain integrity
    intact = True
    breaks = []
    for i in range(1, len(entries)):
        if entries[i].get("previous_hash") != entries[i - 1].get("hash"):
            intact = False
            breaks.append(i)

    # Find verification event
    verification_entry = None
    for entry in entries:
        if entry.get("event") == "identity_verified":
            verification_entry = entry
            break

    proof = {
        "proof_type": "authorship_transfer",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "public_id": identity["public_id"],
        "alias": identity["alias"],
        "chain_length": len(entries),
        "chain_intact": intact,
        "chain_breaks": breaks,
        "genesis_timestamp": entries[0]["timestamp"] if entries else None,
        "latest_timestamp": entries[-1]["timestamp"] if entries else None,
        "verified": identity.get("real_identity") is not None,
        "verification": None,
    }

    if verification_entry:
        proof["verification"] = {
            "name": verification_entry["data"].get("real_identity", {}).get("name"),
            "email": verification_entry["data"].get("real_identity", {}).get("email"),
            "method": verification_entry["data"].get("method"),
            "trust_level": verification_entry["data"].get("trust_level"),
            "verified_at": verification_entry["timestamp"],
            "entries_transferred": verification_entry["data"].get("prior_entries_transferred"),
        }

    # Sign the proof itself
    import hmac
    proof_sig = hmac.new(
        bytes.fromhex(identity["private_seed"]),
        json.dumps(proof, sort_keys=True, separators=(",", ":")).encode(),
        hashlib.sha256,
    ).hexdigest()
    proof["signature"] = proof_sig

    return proof


def run_identity(args):
    """CLI entry point for charter identity."""
    identity = load_identity()

    if args.action == "show":
        if not identity:
            print("No identity found. Run 'charter init' first.")
            return

        print(f"Charter Identity")
        print(f"  Alias:         {identity['alias']}")
        print(f"  Public ID:     {identity['public_id']}")
        print(f"  Created:       {identity['created_at']}")
        print(f"  Contributions: {identity['contributions']}")
        if identity.get("real_identity"):
            ri = identity["real_identity"]
            print(f"  Verified:      {ri['name']} ({ri['email']})")
            print(f"  Method:        {ri['method']} (trust: {ri['trust_level']})")
            print(f"  Verified at:   {ri['verified_at']}")
        else:
            print(f"  Verified:      (not yet)")
        print()
        if identity.get("real_identity"):
            print("Identity is verified. All prior work is attributed to you.")
            print("Use 'charter identity proof' to generate a transfer proof.")
        else:
            print("Your public ID is your pseudonymous identity on the network.")
            print("All contributions are signed and chained to this ID.")
            print("Use 'charter identity verify' to link your real identity")
            print("and claim authorship of all prior work.")

    elif args.action == "verify":
        if not identity:
            print("No identity found. Run 'charter init' first.")
            return

        if identity.get("real_identity"):
            ri = identity["real_identity"]
            print(f"Already verified as: {ri['name']} ({ri['email']})")
            print(f"Method: {ri['method']} (trust: {ri['trust_level']})")
            return

        print("Charter Identity Verification")
        print("=" * 40)
        print()
        print("This links your real identity to your pseudonymous ID.")
        print("All prior work in your hash chain will be attributed to you.")
        print()

        name = input("  Full name: ").strip()
        if not name:
            print("Name is required.")
            return
        email = input("  Email: ").strip()
        if not email:
            print("Email is required.")
            return

        print()
        print("  Verification methods:")
        print("    1. id_me      — Government ID via ID.me (highest trust)")
        print("    2. org_hr     — Organizational HR verification")
        print("    3. email      — Email verification")
        print("    4. manual     — Self-declared (lowest trust)")
        method_choice = input("  Method (1-4): ").strip()
        method_map = {"1": "id_me", "2": "org_hr", "3": "email", "4": "manual"}
        method = method_map.get(method_choice, "manual")

        print()
        print(f"  Linking: {name} ({email})")
        print(f"  Method:  {method}")
        print(f"  This will transfer authorship of all {identity['contributions']} chain entries.")
        confirm = input("  Proceed? (y/N): ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

        verification, prior = verify_identity(name, email, method)
        print()
        print(f"Identity verified.")
        print(f"  Name:       {name}")
        print(f"  Email:      {email}")
        print(f"  Method:     {method} (trust: {verification['trust_level']})")
        print(f"  Transferred: {prior} chain entries now attributed to you")
        print()
        print("Use 'charter identity proof' to generate a shareable transfer proof.")

    elif args.action == "proof":
        if not identity:
            print("No identity found. Run 'charter init' first.")
            return

        proof = generate_transfer_proof()
        if not proof:
            print("Could not generate proof. No chain found.")
            return

        print("Charter Authorship Transfer Proof")
        print("=" * 40)
        print()
        print(f"  Public ID:    {proof['public_id'][:24]}...")
        print(f"  Alias:        {proof['alias']}")
        print(f"  Chain length: {proof['chain_length']} entries")
        print(f"  Chain intact: {'YES' if proof['chain_intact'] else 'BROKEN'}")
        print(f"  First entry:  {proof['genesis_timestamp']}")
        print(f"  Latest entry: {proof['latest_timestamp']}")
        print()

        if proof["verified"] and proof["verification"]:
            v = proof["verification"]
            print(f"  VERIFIED IDENTITY")
            print(f"    Name:         {v['name']}")
            print(f"    Email:        {v['email']}")
            print(f"    Method:       {v['method']} (trust: {v['trust_level']})")
            print(f"    Verified at:  {v['verified_at']}")
            print(f"    Transferred:  {v['entries_transferred']} prior entries")
        else:
            print(f"  NOT YET VERIFIED")
            print(f"  Use 'charter identity verify' to link your real identity.")

        print()
        print(f"  Proof signature: {proof['signature'][:32]}...")
        print()

        # Also save as JSON
        proof_dir = os.path.join(get_identity_dir(), "proofs")
        os.makedirs(proof_dir, exist_ok=True)
        proof_path = os.path.join(
            proof_dir,
            f"proof_{time.strftime('%Y%m%d_%H%M%S', time.gmtime())}.json",
        )
        with open(proof_path, "w") as f:
            json.dump(proof, f, indent=2)
        print(f"  Proof saved to: {proof_path}")

    elif args.action == "export":
        if not identity:
            print("No identity found. Run 'charter init' first.")
            return
        # Export public identity (no private seed)
        public = {
            "public_id": identity["public_id"],
            "alias": identity["alias"],
            "created_at": identity["created_at"],
            "contributions": identity["contributions"],
        }
        if identity.get("real_identity"):
            public["verified_name"] = identity["real_identity"]["name"]
            public["verified_email"] = identity["real_identity"]["email"]
            public["trust_level"] = identity["real_identity"]["trust_level"]
        print(json.dumps(public, indent=2))
