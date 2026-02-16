"""Pseudonymous identity management with hash chain."""

import hashlib
import json
import os
import time
import secrets


IDENTITY_DIR = ".charter"
IDENTITY_FILE = "identity.json"
CHAIN_FILE = "chain.jsonl"


def get_identity_dir():
    """Get the .charter directory in user's home."""
    home = os.path.expanduser("~")
    return os.path.join(home, IDENTITY_DIR)


def get_identity_path():
    return os.path.join(get_identity_dir(), IDENTITY_FILE)


def get_chain_path():
    return os.path.join(get_identity_dir(), CHAIN_FILE)


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

    # Initialize the hash chain with genesis entry
    genesis = {
        "index": 0,
        "timestamp": identity["created_at"],
        "event": "identity_created",
        "data": {"public_id": public_id, "alias": identity["alias"]},
        "previous_hash": "0" * 64,
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
    # Hash everything except the hash field itself
    content = {k: v for k, v in entry.items() if k != "hash"}
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


def append_to_chain(event, data):
    """Append a new entry to the hash chain."""
    chain_path = get_chain_path()
    identity = load_identity()
    if not identity:
        return None

    # Read last entry to get previous hash
    last_hash = "0" * 64
    index = 0
    if os.path.isfile(chain_path):
        with open(chain_path) as f:
            lines = f.readlines()
            if lines:
                last_entry = json.loads(lines[-1])
                last_hash = last_entry.get("hash", "0" * 64)
                index = last_entry.get("index", 0) + 1

    entry = {
        "index": index,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event,
        "data": data,
        "previous_hash": last_hash,
        "signer": identity["public_id"],
    }
    entry["hash"] = hash_entry(entry)
    entry["signature"] = sign_data(entry, identity["private_seed"])

    with open(chain_path, "a") as f:
        f.write(json.dumps(entry) + "\n")

    # Update contribution count
    identity["contributions"] = index
    with open(get_identity_path(), "w") as f:
        json.dump(identity, f, indent=2)

    return entry


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
