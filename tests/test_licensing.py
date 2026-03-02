"""Tests for charter.licensing — license keys, tier validation, feature gating."""

import json
import os
import time
import pytest

from charter.licensing import (
    TIER_FREE,
    TIER_PRO,
    TIER_ENTERPRISE,
    TIER_ORDER,
    TIER_LABELS,
    TIER_KEY_PREFIX,
    KEY_PREFIX_TO_TIER,
    CLI_FEATURE_TIERS,
    MCP_FEATURE_TIERS,
    LicenseError,
    generate_license_key,
    validate_key_format,
    activate_license,
    deactivate_license,
    upgrade_license,
    get_license,
    get_current_tier,
    check_tier,
    gate,
    get_license_status,
    get_upgrade_info,
    _get_license_path,
)


# --- Fixtures ---

@pytest.fixture
def license_home(tmp_path, monkeypatch):
    """Redirect license path to temp directory."""
    charter_dir = tmp_path / ".charter"
    charter_dir.mkdir()
    license_path = str(charter_dir / "license.json")

    monkeypatch.setattr("charter.licensing._get_license_path", lambda: license_path)

    # Also patch identity so chain logging doesn't fail
    monkeypatch.setattr("charter.licensing._log_chain_event", lambda e, d: None)

    return charter_dir


@pytest.fixture
def pro_key():
    """Generate a valid Pro license key."""
    return generate_license_key(TIER_PRO, identifier="test-pro")


@pytest.fixture
def enterprise_key():
    """Generate a valid Enterprise license key."""
    return generate_license_key(TIER_ENTERPRISE, identifier="test-ent")


# --- Tier constants ---

class TestTierConstants:
    def test_tier_order(self):
        assert TIER_ORDER[TIER_FREE] < TIER_ORDER[TIER_PRO]
        assert TIER_ORDER[TIER_PRO] < TIER_ORDER[TIER_ENTERPRISE]

    def test_tier_labels_exist(self):
        assert TIER_FREE in TIER_LABELS
        assert TIER_PRO in TIER_LABELS
        assert TIER_ENTERPRISE in TIER_LABELS

    def test_key_prefix_roundtrip(self):
        for tier, prefix in TIER_KEY_PREFIX.items():
            assert KEY_PREFIX_TO_TIER[prefix] == tier


# --- Key generation ---

class TestKeyGeneration:
    def test_generate_pro_key_format(self):
        key = generate_license_key(TIER_PRO)
        assert key.startswith("CHARTER-PRO-")
        parts = key.split("-")
        assert len(parts) == 4
        assert len(parts[2]) == 8
        assert len(parts[3]) == 4

    def test_generate_enterprise_key_format(self):
        key = generate_license_key(TIER_ENTERPRISE)
        assert key.startswith("CHARTER-ENT-")

    def test_generate_free_key_format(self):
        key = generate_license_key(TIER_FREE)
        assert key.startswith("CHARTER-FREE-")

    def test_keys_are_unique(self):
        k1 = generate_license_key(TIER_PRO)
        k2 = generate_license_key(TIER_PRO)
        assert k1 != k2

    def test_invalid_tier_raises(self):
        with pytest.raises(ValueError, match="Invalid tier"):
            generate_license_key("invalid")

    def test_generate_with_identifier(self):
        key = generate_license_key(TIER_PRO, identifier="cus_abc123")
        assert validate_key_format(key)["valid"]


# --- Key validation ---

class TestKeyValidation:
    def test_valid_pro_key(self, pro_key):
        result = validate_key_format(pro_key)
        assert result["valid"]
        assert result["tier"] == TIER_PRO

    def test_valid_enterprise_key(self, enterprise_key):
        result = validate_key_format(enterprise_key)
        assert result["valid"]
        assert result["tier"] == TIER_ENTERPRISE

    def test_invalid_format_too_few_parts(self):
        result = validate_key_format("CHARTER-PRO-abc")
        assert not result["valid"]

    def test_invalid_format_too_many_parts(self):
        result = validate_key_format("CHARTER-PRO-abcd1234-ef56-extra")
        assert not result["valid"]

    def test_invalid_prefix(self):
        result = validate_key_format("CHARTER-GOLD-abcd1234-ef56")
        assert not result["valid"]

    def test_invalid_hex_body_a(self):
        result = validate_key_format("CHARTER-PRO-ZZZZZZZZ-abcd")
        assert not result["valid"]

    def test_invalid_hex_body_b(self):
        result = validate_key_format("CHARTER-PRO-abcd1234-ZZZZ")
        assert not result["valid"]

    def test_wrong_body_length_a(self):
        result = validate_key_format("CHARTER-PRO-abc-abcd")
        assert not result["valid"]

    def test_wrong_body_length_b(self):
        result = validate_key_format("CHARTER-PRO-abcd1234-ab")
        assert not result["valid"]

    def test_non_string_input(self):
        result = validate_key_format(12345)
        assert not result["valid"]

    def test_empty_string(self):
        result = validate_key_format("")
        assert not result["valid"]


# --- Activation ---

class TestActivation:
    def test_activate_pro(self, license_home, pro_key):
        result = activate_license(pro_key)
        assert result["success"]
        assert result["tier"] == TIER_PRO

    def test_activate_enterprise(self, license_home, enterprise_key):
        result = activate_license(enterprise_key)
        assert result["success"]
        assert result["tier"] == TIER_ENTERPRISE

    def test_activate_writes_file(self, license_home, pro_key):
        activate_license(pro_key)
        license_path = str(license_home / "license.json")
        assert os.path.isfile(license_path)
        with open(license_path) as f:
            data = json.load(f)
        assert data["tier"] == TIER_PRO
        assert data["key"] == pro_key

    def test_activate_with_seats(self, license_home, pro_key):
        result = activate_license(pro_key, seats=10)
        assert result["seats"] == 10

    def test_activate_with_stripe_customer(self, license_home, pro_key):
        activate_license(pro_key, stripe_customer_id="cus_test123")
        lic = get_license()
        assert lic["stripe_customer_id"] == "cus_test123"

    def test_activate_free_key_fails(self, license_home):
        key = generate_license_key(TIER_FREE)
        result = activate_license(key)
        assert not result["success"]

    def test_activate_invalid_key_fails(self, license_home):
        result = activate_license("INVALID-KEY")
        assert not result["success"]


# --- Deactivation ---

class TestDeactivation:
    def test_deactivate(self, license_home, pro_key):
        activate_license(pro_key)
        result = deactivate_license()
        assert result["success"]
        assert result["previous_tier"] == TIER_PRO

    def test_deactivate_removes_file(self, license_home, pro_key):
        activate_license(pro_key)
        deactivate_license()
        assert get_license() is None

    def test_deactivate_no_license(self, license_home):
        result = deactivate_license()
        assert not result["success"]


# --- Upgrade ---

class TestUpgrade:
    def test_upgrade_free_to_pro(self, license_home, pro_key):
        result = upgrade_license(pro_key)
        assert result["success"]

    def test_upgrade_pro_to_enterprise(self, license_home, pro_key, enterprise_key):
        activate_license(pro_key)
        result = upgrade_license(enterprise_key)
        assert result["success"]

    def test_upgrade_same_tier_fails(self, license_home, pro_key):
        activate_license(pro_key)
        another_pro = generate_license_key(TIER_PRO)
        result = upgrade_license(another_pro)
        assert not result["success"]

    def test_downgrade_fails(self, license_home, enterprise_key, pro_key):
        activate_license(enterprise_key)
        result = upgrade_license(pro_key)
        assert not result["success"]


# --- Tier checking ---

class TestTierChecking:
    def test_free_tier_default(self, license_home):
        assert get_current_tier() == TIER_FREE

    def test_pro_tier_after_activation(self, license_home, pro_key):
        activate_license(pro_key)
        assert get_current_tier() == TIER_PRO

    def test_enterprise_tier_after_activation(self, license_home, enterprise_key):
        activate_license(enterprise_key)
        assert get_current_tier() == TIER_ENTERPRISE

    def test_expired_license_reverts_to_free(self, license_home, pro_key):
        activate_license(pro_key)
        # Manually set expiry in the past
        lic_path = str(license_home / "license.json")
        with open(lic_path) as f:
            data = json.load(f)
        data["expires_at"] = "2020-01-01T00:00:00Z"
        with open(lic_path, "w") as f:
            json.dump(data, f)
        assert get_current_tier() == TIER_FREE


# --- Feature gating ---

class TestFeatureGating:
    def test_free_features_always_allowed(self, license_home):
        assert check_tier("bootstrap")
        assert check_tier("status")
        assert check_tier("nonexistent_feature")

    def test_pro_features_blocked_on_free(self, license_home):
        assert not check_tier("compliance")
        assert not check_tier("redteam")
        assert not check_tier("siem")

    def test_pro_features_allowed_on_pro(self, license_home, pro_key):
        activate_license(pro_key)
        assert check_tier("compliance")
        assert check_tier("redteam")
        assert check_tier("siem")

    def test_enterprise_features_blocked_on_pro(self, license_home, pro_key):
        activate_license(pro_key)
        assert not check_tier("federation")
        assert not check_tier("role")

    def test_enterprise_features_allowed_on_enterprise(self, license_home, enterprise_key):
        activate_license(enterprise_key)
        assert check_tier("federation")
        assert check_tier("role")
        assert check_tier("compliance")  # Enterprise includes Pro

    def test_gate_raises_on_insufficient_tier(self, license_home):
        with pytest.raises(LicenseError) as exc_info:
            gate("compliance")
        assert "Pro" in str(exc_info.value)
        assert "compliance" in str(exc_info.value)

    def test_gate_passes_on_sufficient_tier(self, license_home, pro_key):
        activate_license(pro_key)
        gate("compliance")  # Should not raise

    def test_gate_free_feature_never_raises(self, license_home):
        gate("bootstrap")  # Should not raise
        gate("nonexistent")  # Should not raise

    def test_mcp_tier_check(self, license_home, pro_key):
        activate_license(pro_key)
        assert check_tier("charter_compliance_map", feature_map=MCP_FEATURE_TIERS)
        assert not check_tier("charter_federation_status", feature_map=MCP_FEATURE_TIERS)


# --- License status ---

class TestLicenseStatus:
    def test_status_free_tier(self, license_home):
        status = get_license_status()
        assert status["tier"] == TIER_FREE
        assert "Free" in status["tier_label"]

    def test_status_pro_tier(self, license_home, pro_key):
        activate_license(pro_key)
        status = get_license_status()
        assert status["tier"] == TIER_PRO
        assert status["key"].endswith("...")

    def test_status_expired(self, license_home, pro_key):
        activate_license(pro_key)
        lic_path = str(license_home / "license.json")
        with open(lic_path) as f:
            data = json.load(f)
        data["expires_at"] = "2020-01-01T00:00:00Z"
        with open(lic_path, "w") as f:
            json.dump(data, f)
        status = get_license_status()
        assert status.get("expired")


# --- Upgrade info ---

class TestUpgradeInfo:
    def test_free_sees_both_options(self, license_home):
        info = get_upgrade_info()
        assert len(info["options"]) == 2

    def test_pro_sees_enterprise_only(self, license_home, pro_key):
        activate_license(pro_key)
        info = get_upgrade_info()
        assert len(info["options"]) == 1
        assert info["options"][0]["tier"] == TIER_ENTERPRISE

    def test_enterprise_sees_no_options(self, license_home, enterprise_key):
        activate_license(enterprise_key)
        info = get_upgrade_info()
        assert len(info["options"]) == 0


# --- Feature mapping completeness ---

class TestFeatureMappingCompleteness:
    def test_all_cli_features_have_valid_tiers(self):
        for feature, tier in CLI_FEATURE_TIERS.items():
            assert tier in TIER_ORDER, f"CLI feature {feature} has invalid tier {tier}"

    def test_all_mcp_features_have_valid_tiers(self):
        for feature, tier in MCP_FEATURE_TIERS.items():
            assert tier in TIER_ORDER, f"MCP feature {feature} has invalid tier {tier}"

    def test_license_error_contains_feature_name(self):
        err = LicenseError("compliance", TIER_PRO, TIER_FREE)
        assert "compliance" in str(err)
        assert "Pro" in str(err)
        assert "upgrade" in str(err).lower()
