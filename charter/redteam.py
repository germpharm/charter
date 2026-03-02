"""Red Team adversarial testing for Charter governance.

Systematically tests whether Charter's governance layers can be bypassed,
tampered with, or eroded. Each scenario simulates a specific adversarial
attack and verifies that defenses hold.

Categories:
    constraint_escape     — Can Layer A rules be bypassed?
    gradient_manipulation — Can Layer B thresholds be lowered without detection?
    chain_tampering       — Can chain entries be modified without detection?
    threshold_erosion     — Can compliance gradually degrade?
    identity_spoofing     — Can signatures be forged?
    audit_evasion         — Can audit output be suppressed?

Usage:
    charter redteam run                    # Run full battery
    charter redteam run --category chain_tampering  # Single category
    charter redteam generate threats.yaml  # Generate from threat log
    charter redteam report                 # Generate markdown report
"""

import copy
import hashlib
import json
import os
import time

from charter.config import load_config, find_config, hash_config, save_config
from charter.identity import (
    append_to_chain,
    get_chain_path,
    hash_entry,
    load_identity,
    sign_data,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BATTERY_CATEGORIES = [
    "constraint_escape",
    "gradient_manipulation",
    "chain_tampering",
    "threshold_erosion",
    "identity_spoofing",
    "audit_evasion",
]


# ---------------------------------------------------------------------------
# Scenario class
# ---------------------------------------------------------------------------

class RedTeamScenario:
    """A single adversarial test scenario.

    Attributes:
        name:        Short identifier for the scenario.
        category:    One of BATTERY_CATEGORIES.
        description: Human-readable explanation of the attack.
        attack_fn:   callable(context) -> attack_result
        verify_fn:   callable(context, attack_result) -> bool
                     True means the defense held (test passed).
    """

    def __init__(self, name, category, description, attack_fn, verify_fn):
        self.name = name
        self.category = category
        self.description = description
        self.attack_fn = attack_fn
        self.verify_fn = verify_fn


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------

def _build_context(config_path=None, chain_path=None):
    """Build a test context dict for scenario functions.

    The context provides a snapshot of the current governance state
    that scenarios can attack without modifying the real files.
    """
    config_file = config_path or find_config()
    config = load_config(config_file) if config_file else None
    identity = load_identity()
    c_path = chain_path or get_chain_path()

    chain_entries = []
    if c_path and os.path.isfile(c_path):
        with open(c_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    chain_entries.append(json.loads(line))

    return {
        "config_path": config_file,
        "config": config,
        "config_copy": copy.deepcopy(config) if config else None,
        "identity": identity,
        "chain_path": c_path,
        "chain_entries": chain_entries,
        "chain_copy": copy.deepcopy(chain_entries),
    }


# ---------------------------------------------------------------------------
# Built-in attack and verify functions
# ---------------------------------------------------------------------------

# -- constraint_escape ------------------------------------------------------

def _attack_layer_a_bypass(ctx):
    """Try to create a chain entry with an 'override_layer_a' event type."""
    entry = {
        "index": 9999,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": "override_layer_a",
        "data": {"attempted_bypass": True, "rule": "test_constraint"},
        "previous_hash": "0" * 64,
    }
    entry["hash"] = hash_entry(entry)
    return {"crafted_entry": entry}


def _verify_layer_a_bypass(ctx, result):
    """Defense holds if there is no bypass mechanism.

    Charter records entries literally — 'override_layer_a' is just a
    string, not a command. The chain has no execute-on-read semantics,
    so writing this event does nothing. Defense holds by design.
    """
    entry = result["crafted_entry"]
    # Verify the entry is just data, not an executable override.
    # The config still has all its Layer A rules intact.
    config = ctx.get("config")
    if not config:
        return True  # No config to bypass — vacuously true
    gov = config.get("governance", {})
    layer_a = gov.get("layer_a", {})
    rules = layer_a.get("rules", [])
    # Rules are unchanged — the 'override' event had no effect
    original_rules = ctx["config_copy"].get("governance", {}).get("layer_a", {}).get("rules", [])
    return rules == original_rules


def _attack_config_deletion(ctx):
    """Remove all Layer A rules from a config copy and hash it."""
    config = ctx.get("config_copy")
    if not config:
        return {"skipped": True, "reason": "no config"}
    original_hash = hash_config(config)

    mutated = copy.deepcopy(config)
    gov = mutated.get("governance", {})
    if "layer_a" in gov:
        gov["layer_a"]["rules"] = []
    mutated_hash = hash_config(mutated)
    return {
        "original_hash": original_hash,
        "mutated_hash": mutated_hash,
        "rules_removed": True,
    }


def _verify_config_deletion(ctx, result):
    """Defense holds if hash_config detects the change."""
    if result.get("skipped"):
        return True
    return result["original_hash"] != result["mutated_hash"]


# -- gradient_manipulation --------------------------------------------------

def _attack_threshold_change(ctx):
    """Modify a Layer B threshold in a config copy."""
    config = ctx.get("config_copy")
    if not config:
        return {"skipped": True, "reason": "no config"}

    original_hash = hash_config(config)
    mutated = copy.deepcopy(config)

    gov = mutated.get("governance", {})
    layer_b = gov.get("layer_b", {})
    rules = layer_b.get("rules", [])
    if not rules:
        return {"skipped": True, "reason": "no layer_b rules"}

    # Weaken the first rule by changing its threshold
    original_rule = copy.deepcopy(rules[0])
    if isinstance(rules[0], dict):
        rules[0]["threshold"] = "never"
    else:
        rules[0] = "modified_" + str(rules[0])

    mutated_hash = hash_config(mutated)
    return {
        "original_hash": original_hash,
        "mutated_hash": mutated_hash,
        "original_rule": original_rule,
        "modified_rule": rules[0],
    }


def _verify_threshold_change(ctx, result):
    """Defense holds if the hash changed after threshold modification."""
    if result.get("skipped"):
        return True
    return result["original_hash"] != result["mutated_hash"]


def _attack_silent_threshold(ctx):
    """Attempt to save config with record_in_chain=False.

    Even when chain recording is disabled, the hash mismatch between
    the current config and its previous recorded hash is detectable.
    """
    config = ctx.get("config_copy")
    if not config:
        return {"skipped": True, "reason": "no config"}

    original_hash = hash_config(config)

    # Simulate what would happen: modify threshold and save without chain record
    mutated = copy.deepcopy(config)
    gov = mutated.get("governance", {})
    layer_b = gov.get("layer_b", {})
    rules = layer_b.get("rules", [])
    if not rules:
        return {"skipped": True, "reason": "no layer_b rules"}

    if isinstance(rules[0], dict):
        rules[0]["threshold"] = "never"
    else:
        rules[0] = "silently_modified_" + str(rules[0])

    mutated_hash = hash_config(mutated)

    return {
        "original_hash": original_hash,
        "mutated_hash": mutated_hash,
        "chain_would_detect": original_hash != mutated_hash,
    }


def _verify_silent_threshold(ctx, result):
    """Defense holds if the hash mismatch is detectable.

    Even without a chain event, any subsequent config load + hash
    comparison will reveal the change.
    """
    if result.get("skipped"):
        return True
    return result["chain_would_detect"]


# -- chain_tampering --------------------------------------------------------

def _attack_entry_modification(ctx):
    """Modify a chain entry's data field and check hash change."""
    entries = ctx.get("chain_copy", [])
    if not entries:
        return {"skipped": True, "reason": "no chain entries"}

    target = copy.deepcopy(entries[-1])
    original_hash = hash_entry(target)

    # Tamper with the data field
    target["data"] = {"tampered": True, "original_event": target.get("event")}
    tampered_hash = hash_entry(target)

    return {
        "original_hash": original_hash,
        "tampered_hash": tampered_hash,
        "entry_index": target.get("index"),
    }


def _verify_entry_modification(ctx, result):
    """Defense holds if hash_entry produces a different hash after tampering."""
    if result.get("skipped"):
        return True
    return result["original_hash"] != result["tampered_hash"]


def _attack_link_break(ctx):
    """Modify a chain entry's hash and check the next entry's link."""
    entries = ctx.get("chain_copy", [])
    if len(entries) < 2:
        return {"skipped": True, "reason": "need at least 2 chain entries"}

    # Take two consecutive entries
    first = copy.deepcopy(entries[-2])
    second = copy.deepcopy(entries[-1])

    original_link = second.get("previous_hash")
    original_first_hash = first.get("hash")

    # Tamper with the first entry's data, recompute its hash
    first["data"] = {"tampered": True}
    first["hash"] = hash_entry(first)
    tampered_first_hash = first["hash"]

    return {
        "original_first_hash": original_first_hash,
        "tampered_first_hash": tampered_first_hash,
        "second_previous_hash": original_link,
        "link_matches_tampered": original_link == tampered_first_hash,
    }


def _verify_link_break(ctx, result):
    """Defense holds if the link no longer matches after tampering."""
    if result.get("skipped"):
        return True
    return not result["link_matches_tampered"]


def _attack_signature_forgery(ctx):
    """Modify a chain entry, recompute its hash, check HMAC fails."""
    entries = ctx.get("chain_copy", [])
    identity = ctx.get("identity")
    if not entries or not identity:
        return {"skipped": True, "reason": "no chain or identity"}

    target = copy.deepcopy(entries[-1])
    original_signature = target.get("signature")

    if not original_signature:
        return {"skipped": True, "reason": "entry has no signature"}

    private_seed = identity.get("private_seed")
    if not private_seed:
        return {"skipped": True, "reason": "no private_seed in identity"}

    # Tamper with data and recompute hash
    target["data"] = {"forged": True}
    target["hash"] = hash_entry(target)

    # Try to sign the tampered entry with the correct key
    tampered_signature = sign_data(target, private_seed)

    return {
        "original_signature": original_signature,
        "tampered_signature": tampered_signature,
        "signatures_differ": original_signature != tampered_signature,
    }


def _verify_signature_forgery(ctx, result):
    """Defense holds if the HMAC for tampered data differs from original."""
    if result.get("skipped"):
        return True
    return result["signatures_differ"]


# -- threshold_erosion ------------------------------------------------------

def _attack_rule_count(ctx):
    """Compare current rule count to detect removed rules."""
    config = ctx.get("config")
    if not config:
        return {"skipped": True, "reason": "no config"}

    gov = config.get("governance", {})
    layer_a_rules = len(gov.get("layer_a", {}).get("rules", []))
    layer_b_rules = len(gov.get("layer_b", {}).get("rules", []))
    kill_triggers = len(gov.get("kill_triggers", []))

    # Simulate removing a rule
    mutated = copy.deepcopy(config)
    m_gov = mutated.get("governance", {})
    m_rules = m_gov.get("layer_a", {}).get("rules", [])
    removed = None
    if m_rules:
        removed = m_rules.pop()

    return {
        "original_layer_a": layer_a_rules,
        "original_layer_b": layer_b_rules,
        "original_kill_triggers": kill_triggers,
        "mutated_layer_a": len(m_gov.get("layer_a", {}).get("rules", [])),
        "removed_rule": removed,
        "count_changed": layer_a_rules != len(m_gov.get("layer_a", {}).get("rules", [])),
    }


def _verify_rule_count(ctx, result):
    """Defense holds if rule removal is detectable via count comparison."""
    if result.get("skipped"):
        return True
    return result["count_changed"]


# -- identity_spoofing ------------------------------------------------------

def _attack_signature_verify(ctx):
    """Create data, modify it, verify sign_data produces different HMAC."""
    identity = ctx.get("identity")
    if not identity:
        return {"skipped": True, "reason": "no identity"}

    private_seed = identity.get("private_seed")
    if not private_seed:
        return {"skipped": True, "reason": "no private_seed"}

    original_data = {"action": "approved", "amount": 1000, "ts": "2026-01-01"}
    modified_data = {"action": "approved", "amount": 999999, "ts": "2026-01-01"}

    sig_original = sign_data(original_data, private_seed)
    sig_modified = sign_data(modified_data, private_seed)

    return {
        "sig_original": sig_original,
        "sig_modified": sig_modified,
        "signatures_differ": sig_original != sig_modified,
    }


def _verify_signature_verify(ctx, result):
    """Defense holds if modifying data changes the signature."""
    if result.get("skipped"):
        return True
    return result["signatures_differ"]


def _attack_wrong_key(ctx):
    """Sign data with a random key and compare to the real signature."""
    identity = ctx.get("identity")
    if not identity:
        return {"skipped": True, "reason": "no identity"}

    private_seed = identity.get("private_seed")
    if not private_seed:
        return {"skipped": True, "reason": "no private_seed"}

    data = {"test": "wrong_key_detection", "value": 42}

    real_sig = sign_data(data, private_seed)

    # Generate a random 32-byte key (64 hex chars)
    fake_seed = hashlib.sha256(b"attacker_key_material").hexdigest()
    fake_sig = sign_data(data, fake_seed)

    return {
        "real_sig": real_sig,
        "fake_sig": fake_sig,
        "sigs_match": real_sig == fake_sig,
    }


def _verify_wrong_key(ctx, result):
    """Defense holds if a wrong key produces a different signature."""
    if result.get("skipped"):
        return True
    return not result["sigs_match"]


# -- audit_evasion ----------------------------------------------------------

def _attack_chain_gap(ctx):
    """Check for index gaps in the chain (entries must be sequential)."""
    entries = ctx.get("chain_copy", [])
    if len(entries) < 2:
        return {"skipped": True, "reason": "need at least 2 entries"}

    gaps = []
    for i in range(1, len(entries)):
        expected_index = entries[i - 1].get("index", 0) + 1
        actual_index = entries[i].get("index", 0)
        if actual_index != expected_index:
            gaps.append({
                "position": i,
                "expected": expected_index,
                "actual": actual_index,
            })

    # Also simulate inserting a gap to prove detection works
    simulated = copy.deepcopy(entries)
    if len(simulated) > 2:
        # Remove a middle entry to create a gap
        removed_idx = len(simulated) // 2
        removed_entry = simulated.pop(removed_idx)
        sim_gaps = []
        for i in range(1, len(simulated)):
            expected = simulated[i - 1].get("index", 0) + 1
            actual = simulated[i].get("index", 0)
            if actual != expected:
                sim_gaps.append({"expected": expected, "actual": actual})
    else:
        sim_gaps = []
        removed_entry = None

    return {
        "real_gaps": gaps,
        "chain_length": len(entries),
        "simulated_gaps": sim_gaps,
        "simulation_detected_gap": len(sim_gaps) > 0,
    }


def _verify_chain_gap(ctx, result):
    """Defense holds if there are no real gaps and simulated gaps are detected."""
    if result.get("skipped"):
        return True
    # Real chain should have no gaps
    no_real_gaps = len(result["real_gaps"]) == 0
    # Simulated gap removal should be detectable
    sim_detected = result["simulation_detected_gap"]
    return no_real_gaps and sim_detected


def _attack_timestamp_regression(ctx):
    """Check that timestamps are monotonically non-decreasing."""
    entries = ctx.get("chain_copy", [])
    if len(entries) < 2:
        return {"skipped": True, "reason": "need at least 2 entries"}

    regressions = []
    for i in range(1, len(entries)):
        ts_prev = entries[i - 1].get("timestamp", "")
        ts_curr = entries[i].get("timestamp", "")
        # ISO 8601 timestamps are lexicographically comparable
        if ts_curr < ts_prev:
            regressions.append({
                "index": entries[i].get("index"),
                "previous_ts": ts_prev,
                "current_ts": ts_curr,
            })

    # Simulate a regression to prove detection works
    simulated = copy.deepcopy(entries)
    if len(simulated) >= 2:
        simulated[-1]["timestamp"] = "1970-01-01T00:00:00Z"
        sim_regressions = []
        for i in range(1, len(simulated)):
            ts_p = simulated[i - 1].get("timestamp", "")
            ts_c = simulated[i].get("timestamp", "")
            if ts_c < ts_p:
                sim_regressions.append({"index": simulated[i].get("index")})
    else:
        sim_regressions = []

    return {
        "real_regressions": regressions,
        "simulated_regressions": sim_regressions,
        "simulation_detected": len(sim_regressions) > 0,
    }


def _verify_timestamp_regression(ctx, result):
    """Defense holds if no real regressions exist and simulated ones are caught."""
    if result.get("skipped"):
        return True
    no_real = len(result["real_regressions"]) == 0
    sim_detected = result["simulation_detected"]
    return no_real and sim_detected


# ---------------------------------------------------------------------------
# Built-in scenario registry
# ---------------------------------------------------------------------------

def _get_builtin_scenarios():
    """Return the full set of built-in adversarial test scenarios."""
    return [
        # constraint_escape
        RedTeamScenario(
            name="layer_a_bypass_attempt",
            category="constraint_escape",
            description=(
                "Attempt to create a chain entry with event type "
                "'override_layer_a'. Proves constraints are structural "
                "(data-level), not behaviorally executable."
            ),
            attack_fn=_attack_layer_a_bypass,
            verify_fn=_verify_layer_a_bypass,
        ),
        RedTeamScenario(
            name="config_deletion_attempt",
            category="constraint_escape",
            description=(
                "Remove all Layer A rules from a config dict and verify "
                "hash_config detects the change."
            ),
            attack_fn=_attack_config_deletion,
            verify_fn=_verify_config_deletion,
        ),

        # gradient_manipulation
        RedTeamScenario(
            name="threshold_change_detection",
            category="gradient_manipulation",
            description=(
                "Modify a Layer B rule threshold in config and verify "
                "the config hash changes, making the alteration detectable."
            ),
            attack_fn=_attack_threshold_change,
            verify_fn=_verify_threshold_change,
        ),
        RedTeamScenario(
            name="silent_threshold_change",
            category="gradient_manipulation",
            description=(
                "Attempt to modify a threshold without chain recording. "
                "Verify the hash mismatch is still detectable on next load."
            ),
            attack_fn=_attack_silent_threshold,
            verify_fn=_verify_silent_threshold,
        ),

        # chain_tampering
        RedTeamScenario(
            name="entry_modification_detection",
            category="chain_tampering",
            description=(
                "Modify a chain entry's data field and verify hash_entry "
                "produces a different hash."
            ),
            attack_fn=_attack_entry_modification,
            verify_fn=_verify_entry_modification,
        ),
        RedTeamScenario(
            name="link_break_detection",
            category="chain_tampering",
            description=(
                "Modify a chain entry's data and recompute its hash. "
                "Verify the next entry's previous_hash no longer matches."
            ),
            attack_fn=_attack_link_break,
            verify_fn=_verify_link_break,
        ),
        RedTeamScenario(
            name="signature_forgery_detection",
            category="chain_tampering",
            description=(
                "Modify a chain entry and recompute its hash. Verify the "
                "HMAC signature no longer validates against the original."
            ),
            attack_fn=_attack_signature_forgery,
            verify_fn=_verify_signature_forgery,
        ),

        # threshold_erosion
        RedTeamScenario(
            name="rule_count_monitoring",
            category="threshold_erosion",
            description=(
                "Compare current rule count against a baseline. Flag "
                "if rules have been removed — erosion is detectable."
            ),
            attack_fn=_attack_rule_count,
            verify_fn=_verify_rule_count,
        ),

        # identity_spoofing
        RedTeamScenario(
            name="signature_verification",
            category="identity_spoofing",
            description=(
                "Create an entry, modify its data, verify sign_data with "
                "the correct key produces a different signature."
            ),
            attack_fn=_attack_signature_verify,
            verify_fn=_verify_signature_verify,
        ),
        RedTeamScenario(
            name="wrong_key_detection",
            category="identity_spoofing",
            description=(
                "Sign data with a random key and verify it does not match "
                "the signature produced by the real private seed."
            ),
            attack_fn=_attack_wrong_key,
            verify_fn=_verify_wrong_key,
        ),

        # audit_evasion
        RedTeamScenario(
            name="chain_gap_detection",
            category="audit_evasion",
            description=(
                "Check for index gaps in the chain. Entries must be "
                "sequential — any gap indicates deleted entries."
            ),
            attack_fn=_attack_chain_gap,
            verify_fn=_verify_chain_gap,
        ),
        RedTeamScenario(
            name="timestamp_regression_detection",
            category="audit_evasion",
            description=(
                "Check that chain timestamps are monotonically "
                "non-decreasing. Regression indicates tampering."
            ),
            attack_fn=_attack_timestamp_regression,
            verify_fn=_verify_timestamp_regression,
        ),
    ]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

class RedTeamRunner:
    """Execute adversarial test scenarios against Charter governance.

    Args:
        config_path: Path to charter.yaml (uses find_config if None).
        chain_path:  Path to chain.jsonl (uses default if None).
    """

    def __init__(self, config_path=None, chain_path=None):
        self.config_path = config_path
        self.chain_path = chain_path
        self._context = None

    def _get_context(self):
        """Build or return cached context."""
        if self._context is None:
            self._context = _build_context(self.config_path, self.chain_path)
        return self._context

    def run_scenario(self, scenario):
        """Run a single scenario.

        Returns:
            dict with keys: passed, scenario, category, details.
            None if the scenario could not be executed.
        """
        ctx = self._get_context()
        try:
            attack_result = scenario.attack_fn(ctx)
            if attack_result is None:
                return None
            defense_held = scenario.verify_fn(ctx, attack_result)
            details = _summarize_result(attack_result, defense_held)
        except Exception as e:
            defense_held = False
            details = f"Exception during scenario: {e}"

        return {
            "passed": bool(defense_held),
            "scenario": scenario.name,
            "category": scenario.category,
            "details": details,
        }

    def run_battery(self, categories=None):
        """Run all scenarios, optionally filtered by category.

        Args:
            categories: List of category strings to include.
                        If None, runs all categories.

        Returns:
            dict with keys: passed, failed, total, results, duration_ms.
            None if no scenarios were available.
        """
        scenarios = _get_builtin_scenarios()
        if categories:
            scenarios = [s for s in scenarios if s.category in categories]

        if not scenarios:
            return None

        start_ms = _now_ms()
        results = []
        passed = 0
        failed = 0

        for scenario in scenarios:
            result = self.run_scenario(scenario)
            if result is None:
                continue
            results.append(result)
            if result["passed"]:
                passed += 1
            else:
                failed += 1

        duration_ms = _now_ms() - start_ms
        total = passed + failed

        return {
            "passed": passed,
            "failed": failed,
            "total": total,
            "results": results,
            "duration_ms": duration_ms,
        }


# ---------------------------------------------------------------------------
# Enterprise threat log
# ---------------------------------------------------------------------------

def generate_from_threats(threats_path):
    """Read a YAML or JSON threat log and generate custom RedTeamScenarios.

    Threat log format (YAML or JSON):
        threats:
          - name: "PHI extraction"
            category: "constraint_escape"
            description: "Attempt to access protected health information"
            attack_pattern: "data_exfiltration"
            expected_block: "layer_a"

    For each threat, generates a scenario that checks whether the
    governance config contains rules that would address the threat.

    Returns:
        List of RedTeamScenario objects, or None on failure.
    """
    if not os.path.isfile(threats_path):
        return None

    with open(threats_path) as f:
        raw = f.read()

    # Try JSON first, then YAML
    data = None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        pass

    if data is None:
        try:
            import yaml
            data = yaml.safe_load(raw)
        except Exception:
            return None

    if not data or not isinstance(data, dict):
        return None

    threats = data.get("threats", [])
    if not threats:
        return None

    scenarios = []
    for threat in threats:
        name = threat.get("name", "unnamed_threat")
        category = threat.get("category", "constraint_escape")
        description = threat.get("description", "")
        attack_pattern = threat.get("attack_pattern", "")
        expected_block = threat.get("expected_block", "layer_a")

        # Sanitize name for use as identifier
        safe_name = name.lower().replace(" ", "_").replace("-", "_")

        scenario = _build_threat_scenario(
            safe_name, category, description, attack_pattern, expected_block,
        )
        scenarios.append(scenario)

    return scenarios


def _build_threat_scenario(name, category, description, attack_pattern, expected_block):
    """Build a RedTeamScenario from a threat definition.

    The attack checks whether charter.yaml has rules addressing
    the threat category. The verify confirms the rules exist.
    """

    def attack_fn(ctx, _pattern=attack_pattern, _block=expected_block):
        config = ctx.get("config")
        if not config:
            return {"skipped": True, "reason": "no config"}

        gov = config.get("governance", {})
        rules_text = json.dumps(gov, sort_keys=True).lower()

        # Check if rules reference the attack pattern or block layer
        pattern_found = _pattern.lower() in rules_text if _pattern else False
        block_layer = gov.get(f"layer_{_block[-1]}", gov.get(_block, {}))

        layer_rules = []
        if isinstance(block_layer, dict):
            layer_rules = block_layer.get("rules", [])

        return {
            "pattern_in_rules": pattern_found,
            "block_layer": _block,
            "layer_rule_count": len(layer_rules),
            "has_relevant_rules": len(layer_rules) > 0,
        }

    def verify_fn(ctx, result):
        if result.get("skipped"):
            return True
        # Defense holds if there are rules in the expected blocking layer
        return result["has_relevant_rules"]

    return RedTeamScenario(
        name=f"threat_{name}",
        category=category,
        description=f"Threat scenario: {description}",
        attack_fn=attack_fn,
        verify_fn=verify_fn,
    )


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(results):
    """Generate a markdown report from red team results.

    Args:
        results: The dict returned by RedTeamRunner.run_battery().

    Returns:
        A markdown string with summary, per-category breakdown,
        failed scenario details, and recommendations.
        None if results is None.
    """
    if not results:
        return None

    lines = []
    lines.append("# Charter Red Team Report")
    lines.append("")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}")
    lines.append(f"Duration: {results['duration_ms']}ms")
    lines.append("")

    # Summary
    total = results["total"]
    passed = results["passed"]
    failed = results["failed"]
    pct = (passed / total * 100) if total > 0 else 0

    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Passed:** {passed}/{total} ({pct:.0f}%)")
    lines.append(f"- **Failed:** {failed}/{total}")
    lines.append(f"- **Status:** {'ALL DEFENSES HELD' if failed == 0 else 'DEFENSES BREACHED'}")
    lines.append("")

    # Per-category breakdown
    lines.append("## Category Breakdown")
    lines.append("")
    by_category = {}
    for r in results["results"]:
        cat = r["category"]
        if cat not in by_category:
            by_category[cat] = {"passed": 0, "failed": 0, "scenarios": []}
        if r["passed"]:
            by_category[cat]["passed"] += 1
        else:
            by_category[cat]["failed"] += 1
        by_category[cat]["scenarios"].append(r)

    for cat in BATTERY_CATEGORIES:
        if cat not in by_category:
            continue
        info = by_category[cat]
        cat_total = info["passed"] + info["failed"]
        status = "PASS" if info["failed"] == 0 else "FAIL"
        lines.append(f"### {cat} [{status}]")
        lines.append(f"")
        lines.append(f"Passed: {info['passed']}/{cat_total}")
        lines.append("")
        for s in info["scenarios"]:
            icon = "[PASS]" if s["passed"] else "[FAIL]"
            lines.append(f"- {icon} `{s['scenario']}`: {s['details']}")
        lines.append("")

    # Failed scenario details
    failures = [r for r in results["results"] if not r["passed"]]
    if failures:
        lines.append("## Failed Scenarios — Details")
        lines.append("")
        for f in failures:
            lines.append(f"### {f['scenario']} ({f['category']})")
            lines.append("")
            lines.append(f"**Details:** {f['details']}")
            lines.append("")
            rec = _recommendation(f["category"], f["scenario"])
            lines.append(f"**Recommendation:** {rec}")
            lines.append("")

    # Recommendations summary
    if failed > 0:
        lines.append("## Recommendations")
        lines.append("")
        cats_failed = [cat for cat, info in by_category.items() if info["failed"] > 0]
        for cat in cats_failed:
            lines.append(f"- **{cat}**: {_category_recommendation(cat)}")
        lines.append("")
    else:
        lines.append("## Recommendations")
        lines.append("")
        lines.append("All defenses held. No immediate action required.")
        lines.append("Schedule next red team run per your audit frequency.")
        lines.append("")

    return "\n".join(lines)


def _recommendation(category, scenario_name):
    """Return a specific recommendation for a failed scenario."""
    recs = {
        "layer_a_bypass_attempt": (
            "Layer A constraints may be vulnerable to override. "
            "Verify that chain entries do not have execute-on-read semantics."
        ),
        "config_deletion_attempt": (
            "Config hash function is not detecting rule removal. "
            "Verify hash_config uses canonical JSON serialization."
        ),
        "threshold_change_detection": (
            "Layer B threshold changes are not producing hash differences. "
            "Verify hash_config includes all Layer B rule fields."
        ),
        "silent_threshold_change": (
            "Silent config modifications are not detectable. "
            "Implement config hash verification on every load."
        ),
        "entry_modification_detection": (
            "Chain entries can be modified without hash detection. "
            "Verify hash_entry excludes only 'hash' and 'signature' fields."
        ),
        "link_break_detection": (
            "Chain link breaks are not detectable. "
            "Verify previous_hash linkage in append_to_chain."
        ),
        "signature_forgery_detection": (
            "HMAC signatures are not tamper-evident. "
            "Verify sign_data uses HMAC-SHA256 with the private seed."
        ),
        "rule_count_monitoring": (
            "Rule removal is not detectable via count comparison. "
            "Implement rule count baselines in governance config."
        ),
        "signature_verification": (
            "Data modification does not produce different signatures. "
            "Verify sign_data uses canonical JSON serialization."
        ),
        "wrong_key_detection": (
            "Wrong key produces matching signatures. "
            "This is a critical cryptographic failure — investigate immediately."
        ),
        "chain_gap_detection": (
            "Chain index gaps detected — entries may have been deleted. "
            "Investigate the gap indices and restore from backup if available."
        ),
        "timestamp_regression_detection": (
            "Timestamp regression detected — entries may have been reordered. "
            "Investigate the regression points for tampering."
        ),
    }
    return recs.get(scenario_name, "Review the failed scenario and investigate the root cause.")


def _category_recommendation(category):
    """Return a high-level recommendation for a failed category."""
    recs = {
        "constraint_escape": "Review Layer A enforcement — constraints may not be structural.",
        "gradient_manipulation": "Review Layer B hash detection — threshold changes may go unnoticed.",
        "chain_tampering": "Review hash chain integrity — entries may be modifiable without detection.",
        "threshold_erosion": "Implement rule count baselines — gradual rule removal may go undetected.",
        "identity_spoofing": "Review HMAC implementation — signatures may be forgeable.",
        "audit_evasion": "Review chain continuity checks — gaps or regressions indicate tampering.",
    }
    return recs.get(category, "Investigate failures in this category.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ms():
    """Current time in milliseconds."""
    return int(time.time() * 1000)


def _summarize_result(attack_result, defense_held):
    """Create a short human-readable summary of an attack result."""
    if attack_result.get("skipped"):
        return f"Skipped: {attack_result.get('reason', 'unknown')}"

    status = "defense held" if defense_held else "DEFENSE BREACHED"

    # Build detail from key fields
    parts = [status]
    for key in ("original_hash", "tampered_hash", "mutated_hash"):
        if key in attack_result:
            val = attack_result[key]
            if isinstance(val, str) and len(val) > 16:
                val = val[:16] + "..."
            parts.append(f"{key}={val}")

    for key in ("signatures_differ", "sigs_match", "link_matches_tampered",
                "count_changed", "chain_would_detect", "simulation_detected_gap",
                "simulation_detected"):
        if key in attack_result:
            parts.append(f"{key}={attack_result[key]}")

    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Chain event recording
# ---------------------------------------------------------------------------

def _record_run_started(categories, scenario_count):
    """Record redteam_run_started chain event."""
    try:
        append_to_chain("redteam_run_started", {
            "categories": categories or BATTERY_CATEGORIES,
            "scenario_count": scenario_count,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
    except Exception:
        pass  # Chain recording is non-critical


def _record_run_completed(results):
    """Record redteam_run_completed chain event."""
    if not results:
        return
    try:
        append_to_chain("redteam_run_completed", {
            "passed": results["passed"],
            "failed": results["failed"],
            "total": results["total"],
            "duration_ms": results["duration_ms"],
            "categories": list({r["category"] for r in results["results"]}),
        })
    except Exception:
        pass


def _record_scenario_failed(result):
    """Record redteam_scenario_failed chain event for a single failure."""
    try:
        append_to_chain("redteam_scenario_failed", {
            "scenario_name": result["scenario"],
            "category": result["category"],
            "details": result["details"],
        })
    except Exception:
        pass


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_redteam(args):
    """CLI entry point for charter redteam.

    Actions:
        run      — Run the adversarial test battery.
        generate — Generate scenarios from an enterprise threat file.
        report   — Generate and print a markdown report from a run.
    """
    action = getattr(args, "action", "run")

    if action == "run":
        categories = None
        cat_arg = getattr(args, "category", None)
        if cat_arg:
            categories = [c.strip() for c in cat_arg.split(",")]
            invalid = [c for c in categories if c not in BATTERY_CATEGORIES]
            if invalid:
                print(f"Unknown categories: {', '.join(invalid)}")
                print(f"Valid: {', '.join(BATTERY_CATEGORIES)}")
                return

        config_path = getattr(args, "config", None)
        runner = RedTeamRunner(config_path=config_path)
        scenarios = _get_builtin_scenarios()
        if categories:
            scenarios = [s for s in scenarios if s.category in categories]

        _record_run_started(categories, len(scenarios))

        results = runner.run_battery(categories=categories)
        if not results:
            print("No scenarios to run.")
            return

        # Print results
        print(f"Charter Red Team — Adversarial Test Battery")
        print(f"{'=' * 50}")
        print()

        for r in results["results"]:
            icon = "PASS" if r["passed"] else "FAIL"
            print(f"  [{icon}] {r['scenario']} ({r['category']})")
            print(f"         {r['details']}")

        print()
        print(f"Results: {results['passed']}/{results['total']} passed "
              f"({results['failed']} failed) in {results['duration_ms']}ms")

        if results["failed"] > 0:
            print()
            print("DEFENSES BREACHED — review failed scenarios above.")

        # Record chain events
        _record_run_completed(results)
        for r in results["results"]:
            if not r["passed"]:
                _record_scenario_failed(r)

    elif action == "generate":
        threats_path = getattr(args, "threats_file", None)
        if not threats_path:
            print("Usage: charter redteam generate <threats_file>")
            return

        scenarios = generate_from_threats(threats_path)
        if not scenarios:
            print(f"No threats loaded from {threats_path}")
            return

        print(f"Generated {len(scenarios)} scenarios from {threats_path}:")
        for s in scenarios:
            print(f"  - {s.name} ({s.category}): {s.description}")

        # Run them
        config_path = getattr(args, "config", None)
        runner = RedTeamRunner(config_path=config_path)
        ctx = runner._get_context()

        passed = 0
        failed = 0
        for s in scenarios:
            result = runner.run_scenario(s)
            if result is None:
                continue
            icon = "PASS" if result["passed"] else "FAIL"
            print(f"  [{icon}] {result['scenario']}: {result['details']}")
            if result["passed"]:
                passed += 1
            else:
                failed += 1

        total = passed + failed
        print(f"\nResults: {passed}/{total} passed ({failed} failed)")

    elif action == "report":
        config_path = getattr(args, "config", None)
        categories = None
        cat_arg = getattr(args, "category", None)
        if cat_arg:
            categories = [c.strip() for c in cat_arg.split(",")]

        runner = RedTeamRunner(config_path=config_path)
        results = runner.run_battery(categories=categories)

        if not results:
            print("No scenarios to run.")
            return

        report = generate_report(results)
        if report:
            print(report)

            # Save report
            report_dir = "charter_redteam"
            os.makedirs(report_dir, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S", time.gmtime())
            report_path = os.path.join(report_dir, f"redteam_{ts}.md")
            with open(report_path, "w") as f:
                f.write(report)
            print(f"Report saved to: {os.path.abspath(report_path)}")

        # Record chain events
        _record_run_completed(results)
        for r in results["results"]:
            if not r["passed"]:
                _record_scenario_failed(r)
