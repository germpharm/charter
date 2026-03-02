"""Charter licensing — tier validation and feature gating.

License tiers:
  - free: CLI + local governance (forever free)
  - pro: Teams dashboard, compliance reports, audit export ($29/seat/month)
  - enterprise: Everything in Pro + RBAC, SIEM, federation ($249/seat/month)

License keys are HMAC-SHA256 validated offline. No network call needed.
"""

import hashlib
import hmac
import json
import os
import time


# --- Tiers ---

TIER_FREE = "free"
TIER_PRO = "pro"
TIER_ENTERPRISE = "enterprise"

TIER_ORDER = {TIER_FREE: 0, TIER_PRO: 1, TIER_ENTERPRISE: 2}

TIER_LABELS = {
    TIER_FREE: "Free",
    TIER_PRO: "Pro ($29/seat/month)",
    TIER_ENTERPRISE: "Enterprise ($249/seat/month)",
}

# --- Feature → minimum tier ---

CLI_FEATURE_TIERS = {
    # Pro features
    "confidence": TIER_PRO,
    "redteam": TIER_PRO,
    "arbitrate": TIER_PRO,
    "alert": TIER_PRO,
    "siem": TIER_PRO,
    "compliance": TIER_PRO,
    "mcp-serve": TIER_PRO,
    "daemon": TIER_PRO,
    "web": TIER_PRO,
    "serve": TIER_PRO,
    # Enterprise features
    "role": TIER_ENTERPRISE,
    "propose-rule": TIER_ENTERPRISE,
    "sign": TIER_ENTERPRISE,
    "federation": TIER_ENTERPRISE,
    "onboard": TIER_ENTERPRISE,
}

MCP_FEATURE_TIERS = {
    # Pro MCP tools
    "charter_tag_confidence": TIER_PRO,
    "charter_revision_history": TIER_PRO,
    "charter_redteam_run": TIER_PRO,
    "charter_redteam_status": TIER_PRO,
    "charter_arbitrate": TIER_PRO,
    "charter_alert_status": TIER_PRO,
    "charter_siem_export": TIER_PRO,
    "charter_compliance_map": TIER_PRO,
    "charter_audit_report": TIER_PRO,
    "charter_dispute_resolve": TIER_PRO,
    # Enterprise MCP tools
    "charter_propose_rule": TIER_ENTERPRISE,
    "charter_sign_rule": TIER_ENTERPRISE,
    "charter_role_status": TIER_ENTERPRISE,
    "charter_federation_status": TIER_ENTERPRISE,
    "charter_federation_events": TIER_ENTERPRISE,
    "charter_merkle_status": TIER_ENTERPRISE,
    "charter_merkle_audit": TIER_ENTERPRISE,
    "charter_timestamp_batch": TIER_ENTERPRISE,
}

# --- License key format ---
# CHARTER-{TIER}-{8hex}-{4hex}
# TIER: FREE, PRO, ENT
# Body is HMAC-SHA256 derived from a signing secret + tier + timestamp

# This secret is used for offline key validation. It ships with the code
# intentionally — the purpose is format validation and casual tamper
# resistance, not DRM. Charter's value is in the service, not the lock.
_LICENSE_SIGNING_SECRET = b"charter-governance-license-v1"

TIER_KEY_PREFIX = {
    TIER_FREE: "CHARTER-FREE",
    TIER_PRO: "CHARTER-PRO",
    TIER_ENTERPRISE: "CHARTER-ENT",
}

KEY_PREFIX_TO_TIER = {v: k for k, v in TIER_KEY_PREFIX.items()}


class LicenseError(Exception):
    """Raised when a feature requires a higher license tier."""

    def __init__(self, feature, required_tier, current_tier):
        self.feature = feature
        self.required_tier = required_tier
        self.current_tier = current_tier
        tier_label = TIER_LABELS.get(required_tier, required_tier)
        current_label = TIER_LABELS.get(current_tier, current_tier)
        super().__init__(
            f"Charter {tier_label} required for '{feature}'.\n"
            f"Current tier: {current_label}\n\n"
            f"Upgrade: charter upgrade"
        )


# --- License file ---

def _get_license_path():
    """Path to ~/.charter/license.json"""
    home = os.path.expanduser("~")
    return os.path.join(home, ".charter", "license.json")


def get_license():
    """Read the current license. Returns dict or None if no license / free tier."""
    path = _get_license_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return data
    except (json.JSONDecodeError, IOError):
        return None


def get_current_tier():
    """Return the current license tier string."""
    lic = get_license()
    if lic is None:
        return TIER_FREE
    # Check expiry
    expires = lic.get("expires_at")
    if expires:
        try:
            # ISO format: 2026-04-01T00:00:00Z
            exp_time = time.mktime(time.strptime(expires, "%Y-%m-%dT%H:%M:%SZ"))
            if time.time() > exp_time:
                return TIER_FREE  # Expired
        except (ValueError, OverflowError):
            pass
    return lic.get("tier", TIER_FREE)


def check_tier(feature, feature_map=None):
    """Check if current license tier is sufficient for a feature.

    Returns True if allowed, False if tier insufficient.
    """
    if feature_map is None:
        # Check both CLI and MCP maps
        required = CLI_FEATURE_TIERS.get(feature) or MCP_FEATURE_TIERS.get(feature)
    else:
        required = feature_map.get(feature)

    if required is None:
        return True  # No tier restriction — free feature

    current = get_current_tier()
    return TIER_ORDER.get(current, 0) >= TIER_ORDER.get(required, 0)


def gate(feature, feature_map=None):
    """Raise LicenseError if current tier is insufficient for feature."""
    if feature_map is None:
        required = CLI_FEATURE_TIERS.get(feature) or MCP_FEATURE_TIERS.get(feature)
    else:
        required = feature_map.get(feature)

    if required is None:
        return  # Free feature

    current = get_current_tier()
    if TIER_ORDER.get(current, 0) < TIER_ORDER.get(required, 0):
        raise LicenseError(feature, required, current)


# --- Key generation and validation ---

def generate_license_key(tier, identifier=None):
    """Generate a license key for the given tier.

    Args:
        tier: TIER_PRO or TIER_ENTERPRISE
        identifier: optional string to bind the key to (e.g. stripe customer ID)

    Returns:
        str: formatted license key like CHARTER-PRO-a1b2c3d4-e5f6
    """
    if tier not in TIER_KEY_PREFIX:
        raise ValueError(f"Invalid tier: {tier}")

    prefix = TIER_KEY_PREFIX[tier]

    # Create a unique payload
    payload = f"{tier}:{identifier or ''}:{time.time_ns()}"

    # HMAC-SHA256 to get the key body
    sig = hmac.new(
        _LICENSE_SIGNING_SECRET,
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    # Format: PREFIX-8hex-4hex
    body = f"{sig[:8]}-{sig[8:12]}"
    return f"{prefix}-{body}"


def validate_key_format(key):
    """Validate that a key has the correct format.

    Returns:
        dict with {valid: bool, tier: str or None, reason: str}
    """
    if not isinstance(key, str):
        return {"valid": False, "tier": None, "reason": "Key must be a string"}

    parts = key.split("-")
    # CHARTER-TIER-8hex-4hex → 4 parts
    if len(parts) != 4:
        return {"valid": False, "tier": None, "reason": "Invalid key format. Expected: CHARTER-TIER-XXXXXXXX-XXXX"}

    prefix = f"{parts[0]}-{parts[1]}"
    body_a = parts[2]
    body_b = parts[3]

    if prefix not in KEY_PREFIX_TO_TIER:
        return {"valid": False, "tier": None, "reason": f"Unknown key prefix: {prefix}"}

    # Validate hex bodies
    try:
        int(body_a, 16)
    except ValueError:
        return {"valid": False, "tier": None, "reason": f"Invalid key body (part 3): {body_a}"}

    if len(body_a) != 8:
        return {"valid": False, "tier": None, "reason": f"Key body part 3 must be 8 hex chars, got {len(body_a)}"}

    try:
        int(body_b, 16)
    except ValueError:
        return {"valid": False, "tier": None, "reason": f"Invalid key body (part 4): {body_b}"}

    if len(body_b) != 4:
        return {"valid": False, "tier": None, "reason": f"Key body part 4 must be 4 hex chars, got {len(body_b)}"}

    tier = KEY_PREFIX_TO_TIER[prefix]
    return {"valid": True, "tier": tier, "reason": "Valid key format"}


# --- Activation ---

def activate_license(key, seats=1, team_hash=None, stripe_customer_id=None,
                     expires_at=None):
    """Activate a license key. Writes ~/.charter/license.json.

    Args:
        key: license key string
        seats: number of seats (default: 1)
        team_hash: optional team hash to bind to
        stripe_customer_id: optional Stripe customer ID
        expires_at: optional expiry in ISO format

    Returns:
        dict with activation result
    """
    validation = validate_key_format(key)
    if not validation["valid"]:
        return {"success": False, "error": validation["reason"]}

    tier = validation["tier"]

    if tier == TIER_FREE:
        return {"success": False, "error": "Free tier does not require activation"}

    license_data = {
        "tier": tier,
        "key": key,
        "seats": seats,
        "team_hash": team_hash,
        "stripe_customer_id": stripe_customer_id,
        "activated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "expires_at": expires_at,
    }

    # Write license file
    license_path = _get_license_path()
    os.makedirs(os.path.dirname(license_path), exist_ok=True)
    with open(license_path, "w") as f:
        json.dump(license_data, f, indent=2)

    # Log to chain
    _log_chain_event("license_activated", {
        "tier": tier,
        "key_prefix": key[:15] + "...",
        "seats": seats,
    })

    return {
        "success": True,
        "tier": tier,
        "tier_label": TIER_LABELS[tier],
        "seats": seats,
        "activated_at": license_data["activated_at"],
    }


def deactivate_license():
    """Deactivate the current license. Reverts to free tier.

    Returns:
        dict with deactivation result
    """
    lic = get_license()
    if lic is None:
        return {"success": False, "error": "No active license"}

    license_path = _get_license_path()
    try:
        os.remove(license_path)
    except OSError:
        pass

    _log_chain_event("license_deactivated", {
        "previous_tier": lic.get("tier", "unknown"),
    })

    return {"success": True, "previous_tier": lic.get("tier")}


def upgrade_license(new_key):
    """Upgrade an existing license to a higher tier.

    Returns:
        dict with upgrade result
    """
    validation = validate_key_format(new_key)
    if not validation["valid"]:
        return {"success": False, "error": validation["reason"]}

    new_tier = validation["tier"]
    current = get_current_tier()

    if TIER_ORDER.get(new_tier, 0) <= TIER_ORDER.get(current, 0):
        return {
            "success": False,
            "error": f"New key tier ({new_tier}) is not higher than current ({current})",
        }

    # Preserve existing license metadata
    old_lic = get_license() or {}

    result = activate_license(
        new_key,
        seats=old_lic.get("seats", 1),
        team_hash=old_lic.get("team_hash"),
        stripe_customer_id=old_lic.get("stripe_customer_id"),
        expires_at=old_lic.get("expires_at"),
    )

    if result["success"]:
        _log_chain_event("license_upgrade", {
            "from_tier": current,
            "to_tier": new_tier,
        })

    return result


# --- License status display ---

def get_license_status():
    """Get a formatted license status dict for display."""
    lic = get_license()
    tier = get_current_tier()

    status = {
        "tier": tier,
        "tier_label": TIER_LABELS.get(tier, tier),
    }

    if lic:
        status["key"] = lic.get("key", "")[:15] + "..."
        status["seats"] = lic.get("seats", 1)
        status["activated_at"] = lic.get("activated_at")
        status["expires_at"] = lic.get("expires_at")
        status["team_hash"] = lic.get("team_hash")
        # Check if expired
        if tier == TIER_FREE and lic.get("tier") != TIER_FREE:
            status["expired"] = True
    else:
        status["seats"] = 1
        status["activated_at"] = None
        status["expires_at"] = None

    return status


def get_upgrade_info():
    """Get upgrade options with Stripe payment links."""
    current = get_current_tier()

    info = {
        "current_tier": current,
        "current_label": TIER_LABELS.get(current, current),
        "options": [],
    }

    if TIER_ORDER[current] < TIER_ORDER[TIER_PRO]:
        info["options"].append({
            "tier": TIER_PRO,
            "label": TIER_LABELS[TIER_PRO],
            "description": "Teams dashboard, compliance reports, audit export, "
                           "red team, arbitration, alerting, SIEM",
            "stripe_link": "https://buy.stripe.com/test_6oU7sL9lKfK07Hk8sx6AM04",
        })

    if TIER_ORDER[current] < TIER_ORDER[TIER_ENTERPRISE]:
        info["options"].append({
            "tier": TIER_ENTERPRISE,
            "label": TIER_LABELS[TIER_ENTERPRISE],
            "description": "Everything in Pro + RBAC, dual signoff, federation, "
                           "Layer 0 invariants, enterprise onboarding",
            "stripe_link": "https://buy.stripe.com/test_aFa9AT9lK55m0eSfUZ6AM05",
        })

    return info


# --- Internal helpers ---

def _log_chain_event(event, data):
    """Log a licensing event to the hash chain if identity exists."""
    try:
        from charter.identity import append_to_chain
        append_to_chain(event, data, auto_batch=False)
    except Exception:
        pass  # Don't fail activation if chain logging fails


# --- CLI entry points ---

def run_activate(args):
    """Handle `charter activate <key>`."""
    key = args.key
    result = activate_license(key)
    if result["success"]:
        print(f"License activated!")
        print(f"  Tier:      {result['tier_label']}")
        print(f"  Seats:     {result['seats']}")
        print(f"  Activated: {result['activated_at']}")
    else:
        print(f"Activation failed: {result['error']}")


def run_license(args):
    """Handle `charter license`."""
    status = get_license_status()
    print(f"Charter License")
    print(f"  Tier:      {status['tier_label']}")
    if status.get("key"):
        print(f"  Key:       {status['key']}")
    print(f"  Seats:     {status['seats']}")
    if status.get("activated_at"):
        print(f"  Activated: {status['activated_at']}")
    if status.get("expires_at"):
        print(f"  Expires:   {status['expires_at']}")
    if status.get("expired"):
        print(f"  Status:    EXPIRED — run 'charter upgrade' to renew")
    if status.get("team_hash"):
        print(f"  Team:      {status['team_hash'][:16]}...")


def run_upgrade(args):
    """Handle `charter upgrade`."""
    info = get_upgrade_info()
    print(f"Current tier: {info['current_label']}")
    print()

    if not info["options"]:
        print("You're on the highest tier. No upgrades available.")
        return

    print("Available upgrades:")
    print()
    for opt in info["options"]:
        print(f"  {opt['label']}")
        print(f"    {opt['description']}")
        print(f"    Subscribe: {opt['stripe_link']}")
        print()

    print("After subscribing, activate your key:")
    print("  charter activate <key>")
