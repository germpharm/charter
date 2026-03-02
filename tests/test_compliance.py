"""Tests for charter.compliance — regulatory compliance mapping."""

import os

import yaml

from charter.compliance import ComplianceMapper, get_available_standards


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEMPLATES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "charter", "templates"
)
COMPLIANCE_DIR = os.path.join(TEMPLATES_DIR, "compliance")


def _load_healthcare_config():
    """Load the healthcare domain template as a config dict."""
    path = os.path.join(TEMPLATES_DIR, "healthcare.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# TestGetAvailableStandards
# ---------------------------------------------------------------------------


class TestGetAvailableStandards:
    """Tests for the get_available_standards() helper."""

    def test_returns_list(self):
        result = get_available_standards()
        assert isinstance(result, list)

    def test_contains_sox(self):
        result = get_available_standards()
        assert "sox" in result

    def test_contains_hipaa(self):
        result = get_available_standards()
        assert "hipaa" in result

    def test_contains_ferpa(self):
        result = get_available_standards()
        assert "ferpa" in result

    def test_names_are_strings(self):
        result = get_available_standards()
        for name in result:
            assert isinstance(name, str)

    def test_names_have_no_extension(self):
        result = get_available_standards()
        for name in result:
            assert not name.endswith(".yaml")
            assert not name.endswith(".yml")


# ---------------------------------------------------------------------------
# TestLoadStandard
# ---------------------------------------------------------------------------


class TestLoadStandard:
    """Tests for ComplianceMapper.load_standard()."""

    def test_loads_hipaa(self, sample_config):
        mapper = ComplianceMapper(config=sample_config)
        data = mapper.load_standard("hipaa")
        assert data is not None
        assert data["standard"] == "hipaa"

    def test_hipaa_has_controls(self, sample_config):
        mapper = ComplianceMapper(config=sample_config)
        data = mapper.load_standard("hipaa")
        assert "controls" in data
        assert len(data["controls"]) > 0

    def test_each_control_has_required_fields(self, sample_config):
        mapper = ComplianceMapper(config=sample_config)
        data = mapper.load_standard("hipaa")
        for control in data["controls"]:
            assert "id" in control, f"Control missing 'id': {control}"
            assert "name" in control, f"Control missing 'name': {control}"
            assert "match" in control, f"Control missing 'match': {control}"

    def test_loads_sox(self, sample_config):
        mapper = ComplianceMapper(config=sample_config)
        data = mapper.load_standard("sox")
        assert data is not None
        assert data["standard"] == "sox"

    def test_loads_ferpa(self, sample_config):
        mapper = ComplianceMapper(config=sample_config)
        data = mapper.load_standard("ferpa")
        assert data is not None
        assert data["standard"] == "ferpa"

    def test_returns_none_for_unknown(self, sample_config):
        mapper = ComplianceMapper(config=sample_config)
        data = mapper.load_standard("nonexistent_standard_xyz")
        assert data is None

    def test_sets_standard_attribute(self, sample_config):
        mapper = ComplianceMapper(config=sample_config)
        mapper.load_standard("sox")
        assert mapper.standard == "sox"
        assert mapper.standard_data is not None


# ---------------------------------------------------------------------------
# TestComplianceMapper
# ---------------------------------------------------------------------------


class TestComplianceMapper:
    """Tests for ComplianceMapper construction and basic behaviour."""

    def test_init_with_config_and_standard(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="hipaa")
        assert mapper.config is sample_config
        assert mapper.standard == "hipaa"
        assert mapper.standard_data is not None

    def test_init_with_config_only(self, sample_config):
        mapper = ComplianceMapper(config=sample_config)
        assert mapper.config is sample_config
        assert mapper.standard is None
        assert mapper.standard_data is None

    def test_map_to_standard_returns_valid_structure(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="hipaa")
        result = mapper.map_to_standard()
        assert result is not None

        required_keys = [
            "standard",
            "standard_name",
            "total_controls",
            "covered_controls",
            "partial_controls",
            "gap_controls",
            "coverage_percentage",
            "mappings",
            "timestamp",
        ]
        for key in required_keys:
            assert key in result, f"Missing key in result: {key}"

    def test_map_returns_none_without_standard(self, sample_config):
        mapper = ComplianceMapper(config=sample_config)
        result = mapper.map_to_standard()
        assert result is None

    def test_map_returns_none_without_config(self):
        mapper = ComplianceMapper.__new__(ComplianceMapper)
        mapper.config = None
        mapper.standard = "hipaa"
        mapper.standard_data = {"controls": []}
        result = mapper.map_to_standard()
        assert result is None

    def test_mappings_have_required_fields(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        result = mapper.map_to_standard()
        for mapping in result["mappings"]:
            assert "control_id" in mapping
            assert "control_name" in mapping
            assert "charter_coverage" in mapping
            assert "charter_rules" in mapping
            assert "status" in mapping
            assert "notes" in mapping

    def test_status_values_are_valid(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="hipaa")
        result = mapper.map_to_standard()
        valid_statuses = {"covered", "partial", "gap"}
        for mapping in result["mappings"]:
            assert mapping["status"] in valid_statuses, (
                f"Invalid status '{mapping['status']}' for {mapping['control_id']}"
            )

    def test_control_counts_add_up(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="hipaa")
        result = mapper.map_to_standard()
        total = result["total_controls"]
        covered = result["covered_controls"]
        partial = result["partial_controls"]
        gap = result["gap_controls"]
        assert covered + partial + gap == total


# ---------------------------------------------------------------------------
# TestMapToStandard
# ---------------------------------------------------------------------------


class TestMapToStandard:
    """Tests for mapping specific configs against compliance standards."""

    def test_healthcare_config_high_hipaa_coverage(self):
        """Healthcare template should have high HIPAA coverage."""
        config = _load_healthcare_config()
        mapper = ComplianceMapper(config=config, standard="hipaa")
        result = mapper.map_to_standard()
        assert result is not None
        # Healthcare config should cover most HIPAA controls
        assert result["coverage_percentage"] >= 50.0

    def test_healthcare_config_has_covered_controls(self):
        config = _load_healthcare_config()
        mapper = ComplianceMapper(config=config, standard="hipaa")
        result = mapper.map_to_standard()
        assert result["covered_controls"] > 0

    def test_healthcare_data_access_maps_to_hipaa(self):
        """Healthcare data_access rule should map to HIPAA access controls."""
        config = _load_healthcare_config()
        mapper = ComplianceMapper(config=config, standard="hipaa")
        result = mapper.map_to_standard()
        # Find the 164.312(a)(1) Access Control mapping
        access_ctrl = None
        for m in result["mappings"]:
            if m["control_id"] == "164.312(a)(1)":
                access_ctrl = m
                break
        assert access_ctrl is not None, "164.312(a)(1) not found in mappings"
        assert access_ctrl["status"] == "covered"
        assert access_ctrl["charter_coverage"] == "layer_b"

    def test_healthcare_audit_trail_maps_to_hipaa(self):
        """Hash chain should map to HIPAA audit controls."""
        config = _load_healthcare_config()
        mapper = ComplianceMapper(config=config, standard="hipaa")
        result = mapper.map_to_standard()
        audit_ctrl = None
        for m in result["mappings"]:
            if m["control_id"] == "164.312(b)":
                audit_ctrl = m
                break
        assert audit_ctrl is not None, "164.312(b) not found in mappings"
        assert audit_ctrl["status"] == "covered"
        assert audit_ctrl["charter_coverage"] == "chain"

    def test_sample_config_against_hipaa_has_gaps(self, sample_config):
        """Generic sample_config should have some HIPAA gaps."""
        mapper = ComplianceMapper(config=sample_config, standard="hipaa")
        result = mapper.map_to_standard()
        assert result["gap_controls"] > 0

    def test_default_config_coverage_percentage_is_number(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        result = mapper.map_to_standard()
        assert isinstance(result["coverage_percentage"], float)
        assert 0.0 <= result["coverage_percentage"] <= 100.0

    def test_total_controls_matches_template(self, sample_config):
        """total_controls should equal the number of controls in the template."""
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        result = mapper.map_to_standard()
        # Load the SOX template directly and count controls
        sox_path = os.path.join(COMPLIANCE_DIR, "sox.yaml")
        with open(sox_path) as f:
            sox_data = yaml.safe_load(f)
        expected_total = len(sox_data["controls"])
        assert result["total_controls"] == expected_total


# ---------------------------------------------------------------------------
# TestGapAnalysis
# ---------------------------------------------------------------------------


class TestGapAnalysis:
    """Tests for ComplianceMapper.gap_analysis()."""

    def test_returns_list(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="hipaa")
        gaps = mapper.gap_analysis()
        assert isinstance(gaps, list)

    def test_only_gap_and_partial_statuses(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="hipaa")
        gaps = mapper.gap_analysis()
        for g in gaps:
            assert g["status"] in ("gap", "partial"), (
                f"Unexpected status '{g['status']}' in gap analysis"
            )

    def test_no_covered_in_gaps(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        gaps = mapper.gap_analysis()
        for g in gaps:
            assert g["status"] != "covered"

    def test_gap_count_matches_map(self, sample_config):
        """Gap analysis count should match gap + partial from map_to_standard."""
        mapper = ComplianceMapper(config=sample_config, standard="hipaa")
        result = mapper.map_to_standard()
        gaps = mapper.gap_analysis()
        expected = result["gap_controls"] + result["partial_controls"]
        assert len(gaps) == expected

    def test_healthcare_has_fewer_gaps_than_sample(self, sample_config):
        """Healthcare config should have fewer HIPAA gaps than generic config."""
        healthcare_config = _load_healthcare_config()
        mapper_hc = ComplianceMapper(config=healthcare_config, standard="hipaa")
        mapper_gen = ComplianceMapper(config=sample_config, standard="hipaa")
        gaps_hc = mapper_hc.gap_analysis()
        gaps_gen = mapper_gen.gap_analysis()
        assert len(gaps_hc) <= len(gaps_gen)

    def test_returns_empty_list_without_standard(self, sample_config):
        mapper = ComplianceMapper(config=sample_config)
        gaps = mapper.gap_analysis()
        assert gaps == []

    def test_gap_entries_have_control_id(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="ferpa")
        gaps = mapper.gap_analysis()
        for g in gaps:
            assert "control_id" in g
            assert len(g["control_id"]) > 0


# ---------------------------------------------------------------------------
# TestGenerateReport
# ---------------------------------------------------------------------------


class TestGenerateReport:
    """Tests for ComplianceMapper.generate_report()."""

    def test_returns_markdown_string(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="hipaa")
        report = mapper.generate_report(format="markdown")
        assert isinstance(report, str)
        assert len(report) > 0

    def test_contains_standard_name(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="hipaa")
        report = mapper.generate_report()
        assert "HIPAA" in report

    def test_contains_coverage_percentage(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        result = mapper.map_to_standard()
        report = mapper.generate_report()
        assert f"{result['coverage_percentage']}%" in report

    def test_contains_covered_section_when_applicable(self):
        config = _load_healthcare_config()
        mapper = ComplianceMapper(config=config, standard="hipaa")
        report = mapper.generate_report()
        assert "## Covered Controls" in report

    def test_contains_gaps_section_when_applicable(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="hipaa")
        result = mapper.map_to_standard()
        report = mapper.generate_report()
        if result["gap_controls"] > 0:
            assert "## Gaps" in report

    def test_contains_summary_section(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        report = mapper.generate_report()
        assert "## Summary" in report

    def test_contains_generated_timestamp(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="ferpa")
        report = mapper.generate_report()
        assert "**Generated:**" in report

    def test_returns_empty_string_without_standard(self, sample_config):
        mapper = ComplianceMapper(config=sample_config)
        report = mapper.generate_report()
        assert report == ""

    def test_report_header_includes_compliance_report(self):
        config = _load_healthcare_config()
        mapper = ComplianceMapper(config=config, standard="sox")
        report = mapper.generate_report()
        assert "Charter Compliance Report" in report


# ---------------------------------------------------------------------------
# TestWithSampleConfig
# ---------------------------------------------------------------------------


class TestWithSampleConfig:
    """Tests using the sample_config fixture against SOX controls."""

    def test_map_against_sox(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        result = mapper.map_to_standard()
        assert result is not None
        assert "total_controls" in result

    def test_sox_financial_transaction_covered(self, sample_config):
        """sample_config has financial_transaction rule, should cover SOX-302-1."""
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        result = mapper.map_to_standard()
        sox302 = None
        for m in result["mappings"]:
            if m["control_id"] == "SOX-302-1":
                sox302 = m
                break
        assert sox302 is not None
        assert sox302["status"] == "covered"

    def test_sox_audit_trail_covered(self, sample_config):
        """Hash chain type should always be covered."""
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        result = mapper.map_to_standard()
        sox802 = None
        for m in result["mappings"]:
            if m["control_id"] == "SOX-802-1":
                sox802 = m
                break
        assert sox802 is not None
        assert sox802["status"] == "covered"

    def test_sox_layer_a_audit_trail_rule(self, sample_config):
        """sample_config has 'Never conceal the audit trail' — should match SOX-802-2."""
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        result = mapper.map_to_standard()
        sox802_2 = None
        for m in result["mappings"]:
            if m["control_id"] == "SOX-802-2":
                sox802_2 = m
                break
        assert sox802_2 is not None
        assert sox802_2["status"] == "covered"
        assert sox802_2["charter_coverage"] == "layer_a"

    def test_sox_total_controls_is_ten(self, sample_config):
        """SOX template defines exactly 10 controls."""
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        result = mapper.map_to_standard()
        assert result["total_controls"] == 10

    def test_sox_mappings_count_equals_total(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        result = mapper.map_to_standard()
        assert len(result["mappings"]) == result["total_controls"]

    def test_coverage_percentage_is_reasonable(self, sample_config):
        """sample_config should get at least some SOX coverage."""
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        result = mapper.map_to_standard()
        assert result["coverage_percentage"] > 0.0

    def test_timestamp_format(self, sample_config):
        mapper = ComplianceMapper(config=sample_config, standard="sox")
        result = mapper.map_to_standard()
        ts = result["timestamp"]
        assert "T" in ts
        # Expect ISO-like format: YYYY-MM-DDTHH:MM:SS
        assert len(ts) == 19
