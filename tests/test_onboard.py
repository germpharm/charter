"""Tests for charter.onboard — enterprise onboarding wizard."""

import json
import os
import pytest

from charter.onboard import (
    ONBOARD_STEPS,
    _load_onboard_state,
    _save_onboard_state,
    _mark_step_complete,
    _check_prerequisites,
    run_onboard,
    STEP_RUNNERS,
)


# --- Fixtures ---

@pytest.fixture
def onboard_home(tmp_path, monkeypatch):
    """Redirect onboard state path to temp directory."""
    charter_dir = tmp_path / ".charter"
    charter_dir.mkdir()
    state_path = str(charter_dir / "onboard_state.json")

    monkeypatch.setattr("charter.onboard._get_onboard_state_path", lambda: state_path)
    # Suppress chain logging
    monkeypatch.setattr("charter.onboard._mark_step_complete",
                        lambda n: _mark_step_no_chain(n, state_path))

    return charter_dir


def _mark_step_no_chain(step_number, state_path):
    """Mark step complete without chain logging."""
    import time
    state_file = state_path
    if not os.path.isfile(state_file):
        state = {"steps_completed": [], "started_at": None, "last_step_at": None}
    else:
        with open(state_file) as f:
            state = json.load(f)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not state["started_at"]:
        state["started_at"] = now
    if step_number not in state["steps_completed"]:
        state["steps_completed"].append(step_number)
        state["steps_completed"].sort()
    state["last_step_at"] = now

    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)


# --- Constants ---

class TestOnboardSteps:
    def test_eight_steps_defined(self):
        assert len(ONBOARD_STEPS) == 8

    def test_steps_numbered_1_to_8(self):
        for i, step in enumerate(ONBOARD_STEPS):
            assert step["number"] == i + 1

    def test_all_steps_have_name_and_description(self):
        for step in ONBOARD_STEPS:
            assert "name" in step
            assert "description" in step
            assert len(step["name"]) > 0
            assert len(step["description"]) > 0

    def test_all_steps_have_runners(self):
        for step in ONBOARD_STEPS:
            assert step["number"] in STEP_RUNNERS


# --- State management ---

class TestOnboardState:
    def test_initial_state_empty(self, onboard_home):
        state = _load_onboard_state()
        assert state["steps_completed"] == []
        assert state["started_at"] is None

    def test_save_and_load(self, onboard_home):
        state = {"steps_completed": [1, 2], "started_at": "2026-03-01T00:00:00Z", "last_step_at": "2026-03-01T00:00:00Z"}
        _save_onboard_state(state)
        loaded = _load_onboard_state()
        assert loaded["steps_completed"] == [1, 2]

    def test_mark_step_complete(self, onboard_home):
        state_path = str(onboard_home / "onboard_state.json")
        _mark_step_no_chain(1, state_path)
        # Read directly
        with open(state_path) as f:
            state = json.load(f)
        assert 1 in state["steps_completed"]
        assert state["started_at"] is not None

    def test_mark_step_idempotent(self, onboard_home):
        state_path = str(onboard_home / "onboard_state.json")
        _mark_step_no_chain(1, state_path)
        _mark_step_no_chain(1, state_path)
        with open(state_path) as f:
            state = json.load(f)
        assert state["steps_completed"].count(1) == 1

    def test_steps_sorted_after_marking(self, onboard_home):
        state_path = str(onboard_home / "onboard_state.json")
        _mark_step_no_chain(3, state_path)
        _mark_step_no_chain(1, state_path)
        with open(state_path) as f:
            state = json.load(f)
        assert state["steps_completed"] == [1, 3]


# --- Prerequisites ---

class TestPrerequisites:
    def test_step_1_no_prerequisites(self, onboard_home):
        ok, msg = _check_prerequisites(1)
        assert ok

    def test_step_2_needs_step_1(self, onboard_home):
        ok, msg = _check_prerequisites(2)
        assert not ok
        assert "Step 1" in msg

    def test_step_2_passes_after_step_1(self, onboard_home):
        state_path = str(onboard_home / "onboard_state.json")
        _mark_step_no_chain(1, state_path)
        # Need to reload state in the module
        state = _load_onboard_state()
        _save_onboard_state(state)
        ok, msg = _check_prerequisites(2)
        assert ok

    def test_step_7_needs_step_5(self, onboard_home):
        state_path = str(onboard_home / "onboard_state.json")
        _mark_step_no_chain(1, state_path)
        ok, msg = _check_prerequisites(7)
        assert not ok
        assert "Step 5" in msg

    def test_step_8_needs_step_5(self, onboard_home):
        state_path = str(onboard_home / "onboard_state.json")
        _mark_step_no_chain(1, state_path)
        ok, msg = _check_prerequisites(8)
        assert not ok
        assert "Step 5" in msg

    def test_steps_3_4_6_only_need_step_1(self, onboard_home):
        state_path = str(onboard_home / "onboard_state.json")
        _mark_step_no_chain(1, state_path)
        for step in [3, 4, 6]:
            ok, msg = _check_prerequisites(step)
            assert ok, f"Step {step} should pass with only step 1 complete"


# --- CLI entry point ---

class TestRunOnboard:
    def test_status_shows_progress(self, onboard_home, capsys):
        import argparse
        args = argparse.Namespace(step=None, status=True)
        run_onboard(args)
        output = capsys.readouterr().out
        assert "Onboarding" in output
        assert "0/8" in output

    def test_invalid_step_number(self, onboard_home, capsys):
        import argparse
        args = argparse.Namespace(step=9, status=False)
        run_onboard(args)
        output = capsys.readouterr().out
        assert "Invalid step" in output

    def test_step_zero_invalid(self, onboard_home, capsys):
        import argparse
        args = argparse.Namespace(step=0, status=False)
        run_onboard(args)
        output = capsys.readouterr().out
        assert "Invalid step" in output


# --- Corrupt state file ---

class TestCorruptState:
    def test_corrupt_json_returns_empty(self, onboard_home):
        state_path = str(onboard_home / "onboard_state.json")
        with open(state_path, "w") as f:
            f.write("{corrupt")
        state = _load_onboard_state()
        assert state["steps_completed"] == []

    def test_missing_file_returns_empty(self, onboard_home):
        state = _load_onboard_state()
        assert state["steps_completed"] == []
