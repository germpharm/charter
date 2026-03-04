"""Tests for charter.retention — chain archival and pruning."""

import gzip
import json
import os
import time

from charter.identity import create_identity, append_to_chain, get_chain_path
from charter.retention import (
    get_retention_config,
    apply_retention_policy,
    _cleanup_old_archives,
    _DEFAULTS,
)


class TestGetRetentionConfig:
    """Tests for get_retention_config()."""

    def test_returns_none_when_no_config(self):
        result = get_retention_config(config={})
        assert result is None

    def test_returns_none_when_no_retention_section(self):
        result = get_retention_config(config={"domain": "general"})
        assert result is None

    def test_returns_defaults_when_section_empty(self):
        # retention key must be truthy for defaults to apply
        result = get_retention_config(config={"retention": {"max_live_entries": 5000}})
        assert result is not None
        assert result["max_live_entries"] == 5000
        assert result["archive_after_batch"] is True  # default
        assert result["delete_archives_after_days"] == 2555  # default

    def test_expands_tilde_in_archive_dir(self):
        result = get_retention_config(config={
            "retention": {"archive_dir": "~/my_archives"},
        })
        assert "~" not in result["archive_dir"]
        assert os.path.expanduser("~") in result["archive_dir"]

    def test_overrides_defaults(self):
        result = get_retention_config(config={
            "retention": {
                "max_live_entries": 500,
                "delete_archives_after_days": 365,
            },
        })
        assert result["max_live_entries"] == 500
        assert result["delete_archives_after_days"] == 365


class TestApplyRetentionPolicy:
    """Tests for apply_retention_policy()."""

    def test_returns_none_when_no_retention_config(self, charter_home):
        create_identity()
        result = apply_retention_policy(config={"domain": "general"})
        assert result is None

    def test_returns_none_when_archive_after_batch_false(self, charter_home):
        create_identity()
        result = apply_retention_policy(config={
            "retention": {
                "max_live_entries": 5,
                "archive_after_batch": False,
            },
        })
        assert result is None

    def test_returns_none_when_under_limit(self, charter_home):
        create_identity()
        append_to_chain("test", {"x": 1})
        result = apply_retention_policy(config={
            "retention": {"max_live_entries": 10000},
        })
        assert result is None

    def test_returns_none_when_nothing_batched(self, charter_home, monkeypatch):
        """No Merkle batches → nothing can be archived."""
        create_identity()
        # Add enough entries to exceed limit
        for i in range(15):
            append_to_chain("test", {"i": i})

        monkeypatch.setattr(
            "charter.retention.load_batch_index",
            lambda: {"last_chain_index": -1, "batches": []},
        )

        result = apply_retention_policy(config={
            "retention": {"max_live_entries": 5},
        })
        assert result is None

    def test_archives_batched_entries(self, charter_home, tmp_path, monkeypatch):
        """When entries exceed limit and batches exist, archive should be created."""
        create_identity()

        # Create enough entries to exceed a small limit
        for i in range(12):
            append_to_chain("test", {"i": i})

        # Mock the batch index to say entries 0-8 are batched
        monkeypatch.setattr(
            "charter.retention.load_batch_index",
            lambda: {
                "last_chain_index": 8,
                "batches": [
                    {"root": "fakemerkleroot", "chain_range": [0, 8]},
                ],
            },
        )

        archive_dir = str(tmp_path / "archives")
        result = apply_retention_policy(config={
            "retention": {
                "max_live_entries": 5,
                "archive_dir": archive_dir,
                "delete_archives_after_days": 0,
            },
        })

        assert result is not None
        assert result["entries_archived"] > 0
        assert os.path.isfile(result["archive_path"])
        assert result["archive_path"].endswith(".jsonl.gz")

        # Verify the archive is valid gzip with JSON lines
        with gzip.open(result["archive_path"], "rt") as f:
            lines = f.readlines()
        assert len(lines) > 0
        for line in lines:
            entry = json.loads(line.strip())
            assert "event" in entry

    def test_creates_retention_anchor(self, charter_home, tmp_path, monkeypatch):
        """After archival, chain should start with a retention_anchor."""
        create_identity()
        for i in range(12):
            append_to_chain("test", {"i": i})

        monkeypatch.setattr(
            "charter.retention.load_batch_index",
            lambda: {
                "last_chain_index": 8,
                "batches": [
                    {"root": "merkleroot123", "chain_range": [0, 8]},
                ],
            },
        )

        archive_dir = str(tmp_path / "archives")
        apply_retention_policy(config={
            "retention": {
                "max_live_entries": 5,
                "archive_dir": archive_dir,
                "delete_archives_after_days": 0,
            },
        })

        # Read the pruned chain
        chain_path = get_chain_path()
        with open(chain_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        assert entries[0]["event"] == "retention_anchor"
        assert entries[0]["data"]["previous_batch_root"] == "merkleroot123"
        assert "archived_range" in entries[0]["data"]


class TestCleanupOldArchives:
    """Tests for _cleanup_old_archives()."""

    def test_deletes_old_files(self, tmp_path):
        archive_dir = str(tmp_path / "archives")
        os.makedirs(archive_dir)

        # Create a fake archive with old mtime
        old_file = os.path.join(archive_dir, "chain_000000_000100.jsonl.gz")
        with open(old_file, "w") as f:
            f.write("fake")

        # Set mtime to 400 days ago
        old_mtime = time.time() - (400 * 86400)
        os.utime(old_file, (old_mtime, old_mtime))

        deleted = _cleanup_old_archives(archive_dir, max_age_days=365)
        assert deleted == 1
        assert not os.path.exists(old_file)

    def test_keeps_recent_files(self, tmp_path):
        archive_dir = str(tmp_path / "archives")
        os.makedirs(archive_dir)

        recent_file = os.path.join(archive_dir, "chain_000000_000100.jsonl.gz")
        with open(recent_file, "w") as f:
            f.write("fake")

        deleted = _cleanup_old_archives(archive_dir, max_age_days=365)
        assert deleted == 0
        assert os.path.exists(recent_file)

    def test_ignores_non_archive_files(self, tmp_path):
        archive_dir = str(tmp_path / "archives")
        os.makedirs(archive_dir)

        other_file = os.path.join(archive_dir, "readme.txt")
        with open(other_file, "w") as f:
            f.write("not an archive")

        old_mtime = time.time() - (400 * 86400)
        os.utime(other_file, (old_mtime, old_mtime))

        deleted = _cleanup_old_archives(archive_dir, max_age_days=365)
        assert deleted == 0
        assert os.path.exists(other_file)
