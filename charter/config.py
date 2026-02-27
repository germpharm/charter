"""Config file management for Charter governance."""

import hashlib
import json
import os
import yaml


CONFIG_NAME = "charter.yaml"


def find_config(path=None):
    """Find charter.yaml starting from path, walking up to root."""
    start = path or os.getcwd()
    current = os.path.abspath(start)
    while True:
        candidate = os.path.join(current, CONFIG_NAME)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def load_config(path=None):
    """Load and return the charter config dict."""
    config_path = path if path and os.path.isfile(path) else find_config()
    if not config_path:
        return None
    with open(config_path) as f:
        return yaml.safe_load(f)


def hash_config(config):
    """Compute SHA-256 hash of a governance config.

    The hash is computed over the canonical JSON representation
    of the config dict (sorted keys, compact separators). This
    ensures the same config always produces the same hash,
    regardless of YAML formatting.

    Args:
        config: The governance config dict.

    Returns:
        SHA-256 hex digest string.
    """
    raw = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def save_config(config, path=None, record_in_chain=True):
    """Save config dict to charter.yaml.

    When record_in_chain is True (default), records the config
    change as a first-class chain event with the full config hash.
    This makes governance versioning disputes straightforward —
    for any disputed chain entry, the exact governance rules
    active at that moment are cryptographically recoverable.
    """
    out = path or CONFIG_NAME

    # Compute hash before saving
    config_hash = hash_config(config)

    # Check if this is a change from the current config
    existing = load_config(out if os.path.isfile(out) else None)
    existing_hash = hash_config(existing) if existing else None
    is_change = existing_hash != config_hash

    with open(out, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # Record in chain if this is a change
    if record_in_chain and is_change:
        try:
            from charter.identity import append_to_chain
            append_to_chain("governance_config_changed", {
                "config_hash": config_hash,
                "previous_hash": existing_hash,
                "domain": config.get("domain", "unknown"),
                "config_path": os.path.abspath(out),
                "layer_a_rules": len(config.get("governance", {}).get("layer_a", {}).get("rules", [])),
                "layer_b_rules": len(config.get("governance", {}).get("layer_b", {}).get("rules", [])),
                "kill_triggers": len(config.get("governance", {}).get("kill_triggers", [])),
            })
        except Exception:
            pass  # Chain recording is non-critical; never block config save

    return os.path.abspath(out)


def get_config_at_chain_index(chain_index):
    """Reconstruct which governance config was active at a given chain index.

    Walks the chain backwards from the given index to find the most
    recent governance_config_changed event. Returns the config hash
    and metadata.

    Args:
        chain_index: The chain entry index to check.

    Returns:
        Dict with config_hash, domain, and change metadata,
        or None if no config change events found before this index.
    """
    from charter.identity import get_chain_path

    chain_path = get_chain_path()
    if not os.path.isfile(chain_path):
        return None

    with open(chain_path) as f:
        entries = [json.loads(line) for line in f if line.strip()]

    # Walk backwards from chain_index
    for entry in reversed(entries):
        if entry.get("index", 0) > chain_index:
            continue
        if entry.get("event") == "governance_config_changed":
            return {
                "config_hash": entry["data"].get("config_hash"),
                "domain": entry["data"].get("domain"),
                "changed_at_index": entry["index"],
                "changed_at_time": entry.get("timestamp"),
                "layer_a_rules": entry["data"].get("layer_a_rules"),
                "layer_b_rules": entry["data"].get("layer_b_rules"),
                "kill_triggers": entry["data"].get("kill_triggers"),
            }

    return None
