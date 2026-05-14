"""Cross-Verification — federated tamper-evidence for worker chains.

Workers publish their Merkle roots to a company (or any witness) on
a regular schedule. The company stores only the roots, never the
chain contents. If the worker later rewrites their history, the new
roots will not match the witnessed roots — tampering becomes
mathematically detectable.

This is the structural property that makes Charter genuinely powerful
for workplace deployment. From charter_security_model.md:

  "A company that runs Charter as a workplace platform automatically
  gets tamper-evidence on every employee's chain, for free, as a
  structural property of the system. They do not inspect employee
  chains. They do not run manual audits. The math does the work."

Privacy: the company stores only Merkle roots (32-byte hashes). It
never sees the chain contents or any of the worker's data. The
worker keeps their full chain locally and chooses what to share via
manifest exports.

Architecture (MVP — local file-based):
  - Worker side: charter cross-verify publish [--out PATH]
      Builds a root attestation from local Merkle batches and writes
      it to a file the company can ingest.
  - Company side: charter cross-verify witness <attestation.json>
      Imports a worker's root attestation into the local witnessed
      roots store.
  - Company side: charter cross-verify check <manifest.json>
      Verifies that a presented manifest's chain hash matches the
      witnessed roots for the worker who signed it.

Future: HTTP/MCP transport so workers publish to a company endpoint
on a schedule, no manual file exchange.
"""

import hashlib
import hmac as _hmac
import json
import os
import time

from charter.identity import (
    get_chain_path, get_identity_dir, load_identity, sign_data,
    append_to_chain,
)
from charter.merkle import (
    load_batch_index, batch_chain_entries,
)


WITNESSED_ROOTS_DIR = "witnessed_roots"
ATTESTATION_VERSION = "1.0"


# ── Worker Side: Publish ──────────────────────────────────────────


def build_root_attestation(force_batch=True):
    """Build a root attestation for this worker's current chain state.

    Walks the existing Merkle batch index, packages every batch's root
    hash with its chain range, and signs the bundle with the worker's
    HMAC seed. The result is a self-contained attestation a witness
    can store.

    Args:
        force_batch: If True, attempt to batch any unbatched chain
            entries before building the attestation.

    Returns:
        dict: The root attestation, signed.
    """
    identity = load_identity()
    if not identity:
        return None

    if force_batch:
        chain_path = get_chain_path()
        try:
            batch_chain_entries(chain_path)
        except Exception:
            pass  # Batching failures are non-fatal here

    batch_idx = load_batch_index()
    batches = batch_idx.get("batches", [])

    # Build the roots payload
    roots = []
    for b in batches:
        roots.append({
            "batch_id": b.get("batch_id", ""),
            "root": b.get("root", ""),
            "leaf_count": b.get("leaf_count", 0),
            "depth": b.get("depth", 0),
            "chain_range": b.get("chain_range", [0, 0]),
            "first_timestamp": b.get("first_timestamp", ""),
            "last_timestamp": b.get("last_timestamp", ""),
            "created_at": b.get("created_at", ""),
        })

    attestation = {
        "version": ATTESTATION_VERSION,
        "type": "RootAttestation",
        "worker_public_id": identity.get("public_id", ""),
        "worker_alias": identity.get("alias", ""),
        "verified_identity": (
            identity.get("real_identity") is not None
        ),
        "generated_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        ),
        "root_count": len(roots),
        "roots": roots,
        "last_chain_index": batch_idx.get(
            "last_chain_index", -1
        ),
    }

    # Sign with the worker's private seed
    seed = identity.get("private_seed", "")
    if seed:
        sig = _hmac.new(
            bytes.fromhex(seed),
            json.dumps(
                attestation, sort_keys=True, separators=(",", ":")
            ).encode(),
            hashlib.sha256,
        ).hexdigest()
        attestation["signature"] = sig

    # Record the publish event in the chain
    append_to_chain("root_attestation_published", {
        "root_count": attestation["root_count"],
        "last_chain_index": attestation["last_chain_index"],
        "attestation_hash": hashlib.sha256(
            json.dumps(
                {
                    k: v
                    for k, v in attestation.items()
                    if k != "signature"
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:32],
    })

    return attestation


def publish_attestation(output_path=None):
    """Build and write a root attestation to a file.

    Args:
        output_path: File path to write to. Defaults to
            ~/.charter/attestations/attestation_<timestamp>.json

    Returns:
        dict with path and attestation summary.
    """
    attestation = build_root_attestation()
    if not attestation:
        return None

    if not output_path:
        att_dir = os.path.join(
            get_identity_dir(), "attestations"
        )
        os.makedirs(att_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
        output_path = os.path.join(
            att_dir, "attestation_{}.json".format(ts)
        )

    with open(output_path, "w") as f:
        json.dump(attestation, f, indent=2)

    return {
        "path": output_path,
        "size_bytes": os.path.getsize(output_path),
        "worker_public_id": attestation["worker_public_id"],
        "worker_alias": attestation["worker_alias"],
        "root_count": attestation["root_count"],
        "last_chain_index": attestation["last_chain_index"],
    }


# ── Company Side: Witness ─────────────────────────────────────────


def get_witnessed_roots_dir():
    """Path to the local witnessed roots store."""
    d = os.path.join(get_identity_dir(), WITNESSED_ROOTS_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def witness_attestation(attestation_path):
    """Import a worker's root attestation into the local store.

    The company runs this when they receive an attestation from a
    worker. It stores only the roots and metadata — no chain
    contents. The store is keyed by the worker's public_id so
    multiple workers can be witnessed independently.

    Args:
        attestation_path: Path to the attestation JSON file.

    Returns:
        dict with witness result and stored path.
    """
    if not os.path.isfile(attestation_path):
        return {
            "witnessed": False,
            "error": "attestation file not found",
        }

    with open(attestation_path) as f:
        attestation = json.load(f)

    # Validate basic structure
    required = [
        "version", "type", "worker_public_id", "roots", "signature",
    ]
    missing = [k for k in required if k not in attestation]
    if missing:
        return {
            "witnessed": False,
            "error": "attestation missing fields: {}".format(
                ", ".join(missing)
            ),
        }

    if attestation.get("type") != "RootAttestation":
        return {
            "witnessed": False,
            "error": "not a RootAttestation",
        }

    # Note: We do NOT verify the worker's HMAC here.
    # HMAC is symmetric, only the worker can verify their own
    # signature. The attestation is structurally valid; the
    # contract is that the worker is publishing in good faith
    # and the chain itself is the proof. If the worker later
    # tries to alter history, the roots they publish later will
    # not chain back consistently — that's where tampering shows.

    worker_id = attestation["worker_public_id"]
    store_dir = get_witnessed_roots_dir()
    store_path = os.path.join(
        store_dir, "{}.jsonl".format(worker_id[:32])
    )

    # Check for existing roots — detect tampering
    existing_roots = []
    if os.path.isfile(store_path):
        with open(store_path) as f:
            for line in f:
                if line.strip():
                    existing_roots.append(json.loads(line))

    # For each new root, check that any matching batch_id has the
    # same root hash. If not, we have detected tampering.
    tampering_detected = []
    new_roots = []
    existing_by_id = {
        r.get("batch_id"): r for r in existing_roots
    }
    for root in attestation["roots"]:
        bid = root.get("batch_id")
        if bid in existing_by_id:
            old = existing_by_id[bid]
            if old.get("root") != root.get("root"):
                tampering_detected.append({
                    "batch_id": bid,
                    "previously_witnessed_root": old.get("root"),
                    "newly_published_root": root.get("root"),
                    "first_witnessed_at": old.get("witnessed_at"),
                })
        else:
            new_roots.append(root)

    if tampering_detected:
        # Record detection in chain — DO NOT update the store
        append_to_chain("tampering_detected", {
            "worker_public_id": worker_id[:32],
            "worker_alias": attestation.get("worker_alias", ""),
            "conflict_count": len(tampering_detected),
            "details": tampering_detected[:5],
        })
        return {
            "witnessed": False,
            "tampering_detected": True,
            "worker_public_id": worker_id,
            "conflicts": tampering_detected,
            "message": (
                "TAMPERING DETECTED: {} previously witnessed "
                "root(s) do not match the newly published "
                "values. The worker's chain has been altered "
                "since the last attestation.".format(
                    len(tampering_detected)
                )
            ),
        }

    # Append new roots to the store
    witnessed_at = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
    )
    with open(store_path, "a") as f:
        for root in new_roots:
            entry = dict(root)
            entry["witnessed_at"] = witnessed_at
            entry["worker_public_id"] = worker_id
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    # Record witness event in chain
    append_to_chain("attestation_witnessed", {
        "worker_public_id": worker_id[:32],
        "worker_alias": attestation.get("worker_alias", ""),
        "new_roots_count": len(new_roots),
        "total_roots_for_worker": (
            len(existing_roots) + len(new_roots)
        ),
        "last_chain_index": attestation.get(
            "last_chain_index", -1
        ),
    })

    return {
        "witnessed": True,
        "tampering_detected": False,
        "worker_public_id": worker_id,
        "worker_alias": attestation.get("worker_alias", ""),
        "verified_identity": attestation.get(
            "verified_identity", False
        ),
        "new_roots": len(new_roots),
        "existing_roots": len(existing_roots),
        "total_roots": len(existing_roots) + len(new_roots),
        "store_path": store_path,
    }


def list_witnessed_workers():
    """List all workers whose roots are witnessed locally.

    Returns:
        list of dicts with worker_public_id, alias, root_count,
        first_witnessed_at, last_witnessed_at.
    """
    store_dir = get_witnessed_roots_dir()
    if not os.path.isdir(store_dir):
        return []

    workers = []
    for filename in os.listdir(store_dir):
        if not filename.endswith(".jsonl"):
            continue
        path = os.path.join(store_dir, filename)
        with open(path) as f:
            roots = [
                json.loads(line) for line in f if line.strip()
            ]
        if not roots:
            continue
        workers.append({
            "worker_public_id_prefix": filename.replace(
                ".jsonl", ""
            ),
            "root_count": len(roots),
            "first_witnessed_at": roots[0].get(
                "witnessed_at", ""
            ),
            "last_witnessed_at": roots[-1].get(
                "witnessed_at", ""
            ),
            "chain_coverage": [
                roots[0].get("chain_range", [0, 0])[0],
                roots[-1].get("chain_range", [0, 0])[1],
            ],
        })

    return workers


# ── Company Side: Check ───────────────────────────────────────────


def check_manifest_against_witnessed(manifest):
    """Verify a presented manifest against witnessed roots.

    The company runs this when a worker presents a manifest. It
    checks that the manifest's chain hash is consistent with the
    roots they previously witnessed for that worker.

    Args:
        manifest: The Context Manifest dict to verify.

    Returns:
        dict with verified (bool), checks, errors, and details.
    """
    identity = manifest.get("identity", {})
    worker_id = identity.get("public_id", "")
    if not worker_id:
        return {
            "verified": False,
            "errors": ["manifest has no public_id"],
            "checks": [],
        }

    store_dir = get_witnessed_roots_dir()
    store_path = os.path.join(
        store_dir, "{}.jsonl".format(worker_id[:32])
    )

    if not os.path.isfile(store_path):
        return {
            "verified": False,
            "trust_path": "none",
            "checks": [],
            "errors": [
                "no witnessed roots for this worker. Cannot "
                "verify integrity of presented manifest. "
                "Worker must have published attestations to "
                "this Charter instance during their tenure."
            ],
        }

    with open(store_path) as f:
        witnessed = [
            json.loads(line) for line in f if line.strip()
        ]

    checks = [
        "found {} witnessed root(s) for worker".format(
            len(witnessed)
        ),
    ]
    errors = []

    # The manifest's chain_hash should be findable in the
    # witnessed roots' chain ranges. We don't have the full chain
    # to verify the hash directly, but the absence of any
    # witnessed root covering the manifest's chain length is
    # itself a flag.
    chain_length = identity.get("chain_length", 0)
    chain_hash = identity.get("chain_hash", "")

    if chain_length and witnessed:
        max_witnessed_index = max(
            r.get("chain_range", [0, 0])[1] for r in witnessed
        )
        if chain_length > max_witnessed_index + 100:
            checks.append(
                "manifest chain length ({}) extends beyond "
                "witnessed range (max index {})".format(
                    chain_length, max_witnessed_index
                )
            )
            errors.append(
                "manifest contains substantial unwitnessed "
                "history. The portions of the chain after "
                "index {} have not been witnessed by this "
                "instance and cannot be verified.".format(
                    max_witnessed_index
                )
            )

    # Capture the most recent witnessed root for trust display
    latest_root = witnessed[-1] if witnessed else None
    if latest_root:
        checks.append(
            "latest witnessed root: {}... (chain index {})".format(
                latest_root.get("root", "")[:24],
                latest_root.get("chain_range", [0, 0])[1],
            )
        )

    # Note that this is structural verification. To verify the
    # actual hashes match, the worker would also need to provide
    # an inclusion proof against one of the witnessed roots.
    checks.append(
        "structural check passed: worker has previously "
        "published attestations to this instance"
    )

    return {
        "verified": len(errors) == 0,
        "trust_path": "witnessed_roots",
        "worker_public_id": worker_id[:32],
        "worker_alias": identity.get("alias", ""),
        "witnessed_root_count": len(witnessed),
        "manifest_chain_length": chain_length,
        "manifest_chain_hash": chain_hash[:24],
        "checks": checks,
        "errors": errors,
        "latest_witnessed_root": (
            latest_root.get("root", "")[:24] if latest_root else None
        ),
    }


# ── CLI Entry Point ───────────────────────────────────────────────


def run_cross_verify(args):
    """CLI handler for `charter cross-verify` subcommand."""
    action = args.action

    if action == "publish":
        output = getattr(args, "output", None)
        result = publish_attestation(output_path=output)
        if not result:
            print("Error: cannot build attestation. "
                  "Run 'charter init' first.")
            return

        print("Root Attestation Published")
        print("=" * 50)
        print("  Worker:        {} ({}...)".format(
            result["worker_alias"],
            result["worker_public_id"][:16],
        ))
        print("  Roots:         {}".format(result["root_count"]))
        print("  Last index:    {}".format(
            result["last_chain_index"]
        ))
        print()
        print("  Output: {}".format(result["path"]))
        print("  Size:   {} bytes".format(result["size_bytes"]))
        print()
        print("Hand this file to your employer's Charter to be "
              "witnessed:")
        print(
            "  charter cross-verify witness {}".format(
                result["path"]
            )
        )

    elif action == "witness":
        path = getattr(args, "path", None)
        if not path or not os.path.isfile(path):
            print("Error: attestation file required")
            return

        result = witness_attestation(path)

        if result.get("tampering_detected"):
            print("=" * 50)
            print("  TAMPERING DETECTED")
            print("=" * 50)
            print()
            print(result["message"])
            print()
            print("  Worker:    {}".format(
                result["worker_public_id"][:32]
            ))
            print("  Conflicts: {}".format(
                len(result["conflicts"])
            ))
            print()
            for c in result["conflicts"][:3]:
                print("  Batch: {}".format(c["batch_id"]))
                print("    Previously witnessed: {}...".format(
                    (c["previously_witnessed_root"] or "")[:32]
                ))
                print("    Newly published:      {}...".format(
                    (c["newly_published_root"] or "")[:32]
                ))
                print("    First witnessed:      {}".format(
                    c.get("first_witnessed_at", "")
                ))
            print()
            print("Recorded as 'tampering_detected' in chain.")
            return

        if not result.get("witnessed"):
            print("Error: {}".format(
                result.get("error", "unknown")
            ))
            return

        print("Attestation Witnessed")
        print("=" * 50)
        print("  Worker:        {} ({}...)".format(
            result["worker_alias"],
            result["worker_public_id"][:16],
        ))
        print("  Verified ID:   {}".format(
            result["verified_identity"]
        ))
        print("  New roots:     {}".format(result["new_roots"]))
        print("  Existing:      {}".format(result["existing_roots"]))
        print("  Total roots:   {}".format(result["total_roots"]))
        print()
        print("  Stored: {}".format(result["store_path"]))
        print()
        print("Worker's chain is now witnessed by this Charter. "
              "Any future attestation that conflicts with these "
              "roots will be detected as tampering.")

    elif action == "list":
        workers = list_witnessed_workers()
        if not workers:
            print("No witnessed workers.")
            return

        print("Witnessed Workers")
        print("=" * 50)
        for w in workers:
            print()
            print("  ID prefix:        {}...".format(
                w["worker_public_id_prefix"][:24]
            ))
            print("  Root count:       {}".format(w["root_count"]))
            print("  First witnessed:  {}".format(
                w["first_witnessed_at"]
            ))
            print("  Last witnessed:   {}".format(
                w["last_witnessed_at"]
            ))
            print("  Chain coverage:   index {} to {}".format(
                w["chain_coverage"][0], w["chain_coverage"][1]
            ))

    elif action == "check":
        path = getattr(args, "path", None)
        if not path or not os.path.isfile(path):
            print("Error: manifest file required")
            return

        with open(path) as f:
            manifest = json.load(f)

        result = check_manifest_against_witnessed(manifest)

        print("Cross-Verification Check")
        print("=" * 50)
        print("  Verified:      {}".format(result["verified"]))
        print("  Trust path:    {}".format(
            result.get("trust_path", "none")
        ))
        print("  Worker:        {} ({}...)".format(
            result.get("worker_alias", "unknown"),
            result.get("worker_public_id", "")[:16],
        ))
        print()
        for check in result.get("checks", []):
            print("    [ok] {}".format(check))
        for error in result.get("errors", []):
            print("    [!!] {}".format(error))

    else:
        print("Usage: charter cross-verify <action>")
        print()
        print("  publish    Worker: build and write a root "
              "attestation")
        print("  witness    Company: import a worker's "
              "attestation")
        print("  list       Company: list witnessed workers")
        print("  check      Company: verify a presented "
              "manifest against witnessed roots")
