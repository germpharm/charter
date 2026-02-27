"""Merkle tree for Charter hash chain — production-scale verification.

Replaces the linear O(n) chain verification with O(log n) proofs.
A single root hash summarizes an entire batch of transactions.
A proof of inclusion for any single transaction requires only
log2(n) hashes — 40 hashes to prove 1 transaction out of 1 trillion.

Architecture:
    - Transactions are batched into leaves
    - Each leaf is the SHA-256 hash of the transaction data
    - Internal nodes are SHA-256(left_child || right_child)
    - If a level has an odd number of nodes, the last node is promoted
    - The root hash is the single hash that summarizes the entire batch

Usage:
    tree = MerkleTree(transaction_hashes)
    root = tree.root
    proof = tree.get_proof(index)
    valid = MerkleTree.verify_proof(leaf_hash, proof, root)

Integration with Charter chain:
    - append_to_chain still works exactly as before for individual events
    - Periodically, a batch of chain entries is rolled into a Merkle tree
    - The tree root is stored as a new chain entry (event: "merkle_root")
    - Proofs can be generated for any entry in any batch
    - Old chain entries are preserved; the tree is an overlay, not a replacement

Node model:
    - Each Charter node maintains its own chain and its own Merkle trees
    - When two nodes interact, they exchange Merkle roots
    - A proof of a specific transaction requires only the leaf + proof path
    - Neither party needs the other's full dataset
"""

import hashlib
import json
import math
import os
import time


def sha256(data: bytes) -> str:
    """SHA-256 hash, returned as hex string."""
    return hashlib.sha256(data).hexdigest()


def hash_pair(left: str, right: str) -> str:
    """Hash two hex strings together. Order matters."""
    combined = bytes.fromhex(left) + bytes.fromhex(right)
    return sha256(combined)


class MerkleTree:
    """Binary Merkle tree over a list of leaf hashes.

    Supports:
        - Construction from a list of hex hash strings
        - Root hash computation
        - Proof generation for any leaf
        - Static proof verification
        - Serialization to/from JSON
    """

    def __init__(self, leaves: list[str]):
        """Build a Merkle tree from leaf hashes.

        Args:
            leaves: List of hex hash strings (SHA-256 of transaction data).
                    Must have at least 1 element.
        """
        if not leaves:
            raise ValueError("Cannot build Merkle tree from empty list")

        self.leaves = list(leaves)
        self.leaf_count = len(leaves)
        self._levels = self._build(leaves)

    @property
    def root(self) -> str:
        """The single root hash summarizing all leaves."""
        return self._levels[-1][0]

    @property
    def depth(self) -> int:
        """Number of levels in the tree (including leaves)."""
        return len(self._levels)

    def _build(self, leaves: list[str]) -> list[list[str]]:
        """Build all levels of the tree bottom-up.

        Returns a list of levels. Level 0 = leaves, last level = [root].
        """
        levels = [list(leaves)]
        current = list(leaves)

        while len(current) > 1:
            next_level = []
            for i in range(0, len(current), 2):
                if i + 1 < len(current):
                    next_level.append(hash_pair(current[i], current[i + 1]))
                else:
                    # Odd node: promote without hashing
                    next_level.append(current[i])
            levels.append(next_level)
            current = next_level

        return levels

    def get_proof(self, index: int) -> list[dict]:
        """Generate an inclusion proof for the leaf at the given index.

        Returns a list of proof steps. Each step has:
            - hash: the sibling hash needed for verification
            - position: "left" or "right" (where the sibling sits)

        To verify: start with the leaf hash, apply each step in order,
        and compare the result to the root.
        """
        if index < 0 or index >= self.leaf_count:
            raise IndexError(f"Leaf index {index} out of range [0, {self.leaf_count})")

        proof = []
        idx = index

        for level in self._levels[:-1]:  # Skip the root level
            if len(level) == 1:
                break

            if idx % 2 == 0:
                # Current node is on the left; sibling is on the right
                if idx + 1 < len(level):
                    proof.append({
                        "hash": level[idx + 1],
                        "position": "right",
                    })
                # If no sibling (odd node), no proof step needed
            else:
                # Current node is on the right; sibling is on the left
                proof.append({
                    "hash": level[idx - 1],
                    "position": "left",
                })

            idx = idx // 2

        return proof

    @staticmethod
    def verify_proof(leaf_hash: str, proof: list[dict], expected_root: str) -> bool:
        """Verify that a leaf hash is included in the tree with the given root.

        Args:
            leaf_hash: The SHA-256 hash of the transaction to verify.
            proof: The proof path from get_proof().
            expected_root: The Merkle root to verify against.

        Returns:
            True if the proof is valid.
        """
        current = leaf_hash

        for step in proof:
            sibling = step["hash"]
            if step["position"] == "right":
                current = hash_pair(current, sibling)
            else:
                current = hash_pair(sibling, current)

        return current == expected_root

    def to_dict(self) -> dict:
        """Serialize the tree to a JSON-compatible dict."""
        return {
            "version": "1.0",
            "leaf_count": self.leaf_count,
            "root": self.root,
            "depth": self.depth,
            "leaves": self.leaves,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MerkleTree":
        """Reconstruct a MerkleTree from a serialized dict."""
        return cls(data["leaves"])

    def __repr__(self) -> str:
        return f"MerkleTree(leaves={self.leaf_count}, root={self.root[:16]}...)"


# ---------------------------------------------------------------------------
# Batch management — rolling chain entries into Merkle trees
# ---------------------------------------------------------------------------

MERKLE_DIR = "merkle_trees"


def get_merkle_dir() -> str:
    """Get the directory for stored Merkle trees."""
    home = os.path.expanduser("~")
    d = os.path.join(home, ".charter", MERKLE_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def get_batch_index_path() -> str:
    """Path to the batch index file tracking which chain entries are in which tree."""
    return os.path.join(get_merkle_dir(), "batch_index.json")


def load_batch_index() -> dict:
    """Load the batch index. Returns dict mapping batch_id to metadata."""
    path = get_batch_index_path()
    if not os.path.isfile(path):
        return {"batches": [], "last_chain_index": -1}
    with open(path) as f:
        return json.load(f)


def save_batch_index(index: dict):
    """Save the batch index."""
    path = get_batch_index_path()
    with open(path, "w") as f:
        json.dump(index, f, indent=2)


def batch_chain_entries(
    chain_path: str,
    batch_size: int = 256,
    min_entries: int = 16,
) -> dict | None:
    """Roll unbatched chain entries into a new Merkle tree.

    Args:
        chain_path: Path to the chain.jsonl file.
        batch_size: Max entries per batch. Powers of 2 are optimal.
        min_entries: Don't batch fewer than this many entries.

    Returns:
        Dict with batch metadata if a new tree was created, None otherwise.
    """
    if not os.path.isfile(chain_path):
        return None

    # Load chain
    with open(chain_path) as f:
        entries = [json.loads(line) for line in f if line.strip()]

    if not entries:
        return None

    # Load batch index
    batch_idx = load_batch_index()
    last_batched = batch_idx["last_chain_index"]

    # Find unbatched entries
    unbatched = [e for e in entries if e.get("index", 0) > last_batched]

    if len(unbatched) < min_entries:
        return None

    # Take up to batch_size entries
    to_batch = unbatched[:batch_size]

    # Build leaf hashes from chain entry hashes
    leaves = [e["hash"] for e in to_batch]

    # Build the tree
    tree = MerkleTree(leaves)

    # Create batch metadata
    batch_id = f"batch_{len(batch_idx['batches']):06d}"
    first_index = to_batch[0].get("index", 0)
    last_index = to_batch[-1].get("index", 0)

    batch_meta = {
        "batch_id": batch_id,
        "root": tree.root,
        "leaf_count": tree.leaf_count,
        "depth": tree.depth,
        "chain_range": [first_index, last_index],
        "first_timestamp": to_batch[0].get("timestamp"),
        "last_timestamp": to_batch[-1].get("timestamp"),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    # Save the full tree
    tree_path = os.path.join(get_merkle_dir(), f"{batch_id}.json")
    with open(tree_path, "w") as f:
        json.dump(tree.to_dict(), f, indent=2)

    # Update batch index
    batch_idx["batches"].append(batch_meta)
    batch_idx["last_chain_index"] = last_index
    save_batch_index(batch_idx)

    return batch_meta


def generate_proof(chain_index: int) -> dict | None:
    """Generate a Merkle proof for a specific chain entry.

    Args:
        chain_index: The chain entry index to prove.

    Returns:
        Dict with the proof, batch metadata, and verification instructions.
        None if the entry hasn't been batched yet.
    """
    batch_idx = load_batch_index()

    # Find which batch contains this chain index
    target_batch = None
    for batch in batch_idx["batches"]:
        start, end = batch["chain_range"]
        if start <= chain_index <= end:
            target_batch = batch
            break

    if not target_batch:
        return None

    # Load the tree
    tree_path = os.path.join(get_merkle_dir(), f"{target_batch['batch_id']}.json")
    if not os.path.isfile(tree_path):
        return None

    with open(tree_path) as f:
        tree_data = json.load(f)

    tree = MerkleTree.from_dict(tree_data)

    # The leaf index within the batch
    leaf_index = chain_index - target_batch["chain_range"][0]

    # Generate proof
    proof_path = tree.get_proof(leaf_index)

    return {
        "chain_index": chain_index,
        "batch_id": target_batch["batch_id"],
        "merkle_root": tree.root,
        "leaf_hash": tree.leaves[leaf_index],
        "leaf_index": leaf_index,
        "proof": proof_path,
        "proof_length": len(proof_path),
        "batch_leaf_count": tree.leaf_count,
        "verification": {
            "instruction": (
                "To verify: start with leaf_hash, apply each proof step "
                "(hash_pair with sibling at stated position), compare "
                "result to merkle_root."
            ),
            "steps": len(proof_path),
            "equivalent_dataset_size": f"Proves 1 entry out of {tree.leaf_count} "
                                       f"with only {len(proof_path)} hash operations",
        },
    }


def verify_chain_entry(chain_index: int, entry_hash: str) -> dict:
    """Verify a chain entry against its Merkle tree.

    Args:
        chain_index: The chain entry index.
        entry_hash: The hash of the chain entry to verify.

    Returns:
        Dict with verification result.
    """
    proof_data = generate_proof(chain_index)

    if not proof_data:
        return {
            "verified": False,
            "reason": "Entry not yet batched into a Merkle tree",
            "chain_index": chain_index,
        }

    if proof_data["leaf_hash"] != entry_hash:
        return {
            "verified": False,
            "reason": "Entry hash does not match leaf hash in tree",
            "chain_index": chain_index,
            "expected": proof_data["leaf_hash"],
            "got": entry_hash,
        }

    valid = MerkleTree.verify_proof(
        entry_hash,
        proof_data["proof"],
        proof_data["merkle_root"],
    )

    return {
        "verified": valid,
        "chain_index": chain_index,
        "batch_id": proof_data["batch_id"],
        "merkle_root": proof_data["merkle_root"],
        "proof_steps": proof_data["proof_length"],
        "reason": "Proof valid" if valid else "Proof verification failed",
    }


# ---------------------------------------------------------------------------
# Cross-node verification
# ---------------------------------------------------------------------------

def create_exchange_proof(chain_index: int, chain_path: str = None) -> dict | None:
    """Create a proof package suitable for sending to another node.

    This is what Dartmouth Health sends to BCBS when a claim is disputed.
    It contains everything needed to verify the claim was processed under
    governance, without exposing any other data.

    Args:
        chain_index: The chain entry to prove.
        chain_path: Path to chain.jsonl (uses default if None).

    Returns:
        A self-contained proof package.
    """
    from charter.identity import get_chain_path, load_identity, sign_data

    if chain_path is None:
        chain_path = get_chain_path()

    # Load the specific chain entry
    if not os.path.isfile(chain_path):
        return None

    with open(chain_path) as f:
        entries = [json.loads(line) for line in f if line.strip()]

    entry = None
    for e in entries:
        if e.get("index") == chain_index:
            entry = e
            break

    if not entry:
        return None

    # Generate Merkle proof
    proof_data = generate_proof(chain_index)

    identity = load_identity()

    package = {
        "type": "charter_exchange_proof",
        "version": "1.0",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_node": identity["public_id"] if identity else None,
        "source_alias": identity.get("alias") if identity else None,
        "chain_entry": {
            "index": entry["index"],
            "timestamp": entry["timestamp"],
            "event": entry["event"],
            "data": entry["data"],
            "hash": entry["hash"],
        },
        "merkle_proof": proof_data,
        "verification_instructions": (
            "1. Recompute the chain entry hash from the entry fields. "
            "2. Verify the Merkle proof: apply proof steps to the leaf hash "
            "   and confirm the result matches merkle_root. "
            "3. The merkle_root is signed by the source node. "
            "4. This proves the entry existed in the source node's chain "
            "   at the stated time, under the stated governance."
        ),
    }

    # Sign the entire package
    if identity:
        package["signature"] = sign_data(package, identity["private_seed"])

    return package


def verify_exchange_proof(package: dict) -> dict:
    """Verify a proof package received from another node.

    This is what BCBS runs when Dartmouth Health sends a claim proof.
    No access to DH's chain or database is needed.

    Args:
        package: The exchange proof package.

    Returns:
        Verification result.
    """
    if package.get("type") != "charter_exchange_proof":
        return {"verified": False, "reason": "Not a Charter exchange proof"}

    entry = package.get("chain_entry", {})
    merkle_proof = package.get("merkle_proof")

    if not entry or not merkle_proof:
        return {"verified": False, "reason": "Missing chain entry or Merkle proof"}

    # Verify the Merkle proof
    leaf_hash = merkle_proof.get("leaf_hash")
    proof_path = merkle_proof.get("proof")
    root = merkle_proof.get("merkle_root")

    if not all([leaf_hash, proof_path is not None, root]):
        return {"verified": False, "reason": "Incomplete Merkle proof data"}

    # Check that the entry hash matches the leaf
    if entry.get("hash") != leaf_hash:
        return {
            "verified": False,
            "reason": "Chain entry hash does not match Merkle leaf",
        }

    # Verify the proof path
    valid = MerkleTree.verify_proof(leaf_hash, proof_path, root)

    return {
        "verified": valid,
        "source_node": package.get("source_node"),
        "source_alias": package.get("source_alias"),
        "event": entry.get("event"),
        "timestamp": entry.get("timestamp"),
        "merkle_root": root,
        "proof_steps": len(proof_path),
        "reason": "Exchange proof valid" if valid else "Merkle proof verification failed",
    }
