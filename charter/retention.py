"""Charter chain retention — archive and prune old chain entries.

Implements a retention policy for the append-only hash chain.  Entries
that have already been batched into Merkle trees can be safely archived
to compressed files and removed from the live chain, because their
integrity is provable via the Merkle root.

Config (in charter.yaml):

    retention:
      max_live_entries: 10000          # keep at most N entries in chain.jsonl
      archive_after_batch: true        # archive entries covered by Merkle batches
      archive_dir: ~/.charter/archive  # where compressed archives go
      delete_archives_after_days: 2555 # ~7 years; 0 = never delete

If no retention section exists, retention is disabled (no-op).
"""

import gzip
import json
import os
import time

from charter.config import load_config
from charter.identity import get_chain_path, append_to_chain
from charter.merkle import load_batch_index, get_merkle_dir


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULTS = {
    "max_live_entries": 10000,
    "archive_after_batch": True,
    "archive_dir": os.path.join(os.path.expanduser("~"), ".charter", "archive"),
    "delete_archives_after_days": 2555,  # ~7 years
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_retention_config(config=None):
    """Load the retention section from config, with defaults applied.

    Args:
        config: Full charter config dict.  If None, loads via load_config().

    Returns:
        Retention config dict with defaults filled in, or None if no
        retention section exists (retention disabled).
    """
    if config is None:
        config = load_config()
    if not config:
        return None

    retention = config.get("retention")
    if not retention:
        return None

    result = dict(_DEFAULTS)
    result.update(retention)

    # Expand ~ in archive_dir
    result["archive_dir"] = os.path.expanduser(result["archive_dir"])
    return result


def apply_retention_policy(config=None):
    """Apply the chain retention policy.

    Archives chain entries that are covered by Merkle batches, then
    prunes the live chain.jsonl to keep only recent entries.

    Args:
        config: Full charter config dict.  If None, loads via load_config().

    Returns:
        Dict with keys: entries_archived, entries_pruned, archives_deleted,
        archive_path (or None).  Returns None if retention is disabled or
        no action was needed.
    """
    ret_cfg = get_retention_config(config)
    if not ret_cfg:
        return None

    if not ret_cfg.get("archive_after_batch", True):
        return None

    chain_path = get_chain_path()
    if not os.path.isfile(chain_path):
        return None

    # Load chain
    with open(chain_path) as f:
        entries = [json.loads(line) for line in f if line.strip()]

    if not entries:
        return None

    max_live = ret_cfg["max_live_entries"]

    # Nothing to do if under the limit
    if len(entries) <= max_live:
        return None

    # Load batch index to find what's been Merkle-batched
    batch_idx = load_batch_index()
    last_batched = batch_idx.get("last_chain_index", -1)

    if last_batched < 0:
        return None  # nothing batched yet

    # Split entries: archivable (batched AND over limit) vs. live
    archivable = [e for e in entries if e.get("index", 0) <= last_batched]
    live = [e for e in entries if e.get("index", 0) > last_batched]

    if not archivable:
        return None

    # If live entries alone are still over max, keep only the last max_live
    # from the live set (this shouldn't normally happen).
    if len(live) > max_live:
        live = live[-max_live:]

    # Write archive
    archive_dir = ret_cfg["archive_dir"]
    os.makedirs(archive_dir, exist_ok=True)

    first_idx = archivable[0].get("index", 0)
    last_idx = archivable[-1].get("index", 0)
    archive_name = f"chain_{first_idx:06d}_{last_idx:06d}.jsonl.gz"
    archive_path = os.path.join(archive_dir, archive_name)

    with gzip.open(archive_path, "wt", encoding="utf-8") as f:
        for entry in archivable:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    # Find the Merkle root covering the last archived entry
    last_batch_root = None
    for batch in reversed(batch_idx.get("batches", [])):
        chain_range = batch.get("chain_range", [])
        if chain_range and chain_range[1] >= last_idx:
            last_batch_root = batch.get("root")
            break

    # Build retention anchor as the new first entry in the pruned chain
    anchor = {
        "index": last_idx,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "retention_anchor",
        "data": {
            "archived_range": [first_idx, last_idx],
            "archive_path": archive_path,
            "entries_archived": len(archivable),
            "previous_batch_root": last_batch_root,
        },
        "previous_hash": archivable[-1].get("hash", ""),
        "hash": archivable[-1].get("hash", ""),  # anchor inherits last archived hash
        "signer": "retention_policy",
    }

    # Rewrite chain.jsonl: anchor + live entries
    pruned = [anchor] + live
    tmp_path = chain_path + ".tmp"
    with open(tmp_path, "w") as f:
        for entry in pruned:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    os.replace(tmp_path, chain_path)

    # Delete old archives past retention ceiling
    archives_deleted = 0
    delete_days = ret_cfg.get("delete_archives_after_days", 0)
    if delete_days > 0:
        archives_deleted = _cleanup_old_archives(archive_dir, delete_days)

    # Log retention event
    try:
        append_to_chain("retention_applied", {
            "entries_archived": len(archivable),
            "entries_pruned": len(entries) - len(pruned),
            "archive_path": archive_path,
            "archives_deleted": archives_deleted,
        })
    except Exception:
        pass  # retention logging is non-critical

    return {
        "entries_archived": len(archivable),
        "entries_pruned": len(entries) - len(pruned),
        "archives_deleted": archives_deleted,
        "archive_path": archive_path,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _cleanup_old_archives(archive_dir, max_age_days):
    """Delete archive files older than max_age_days.

    Returns:
        Number of files deleted.
    """
    deleted = 0
    cutoff = time.time() - (max_age_days * 86400)

    for fname in os.listdir(archive_dir):
        if not fname.endswith(".jsonl.gz"):
            continue
        fpath = os.path.join(archive_dir, fname)
        try:
            if os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                deleted += 1
        except OSError:
            pass

    return deleted
