"""Charter enterprise onboarding wizard.

8-step guided setup for Enterprise tier customers:
  1. License Activation
  2. RBAC Setup
  3. Alerting Configuration
  4. SIEM Integration
  5. Compliance Framework Selection
  6. Federation Setup
  7. Initial Gap Analysis
  8. First Audit

Each step can be run independently via `charter onboard --step N`.
"""

import json
import os
import time


ONBOARD_STEPS = [
    {
        "number": 1,
        "name": "License Activation",
        "description": "Verify Enterprise license is active",
    },
    {
        "number": 2,
        "name": "RBAC Setup",
        "description": "Assign governance roles to team members (operator, reviewer, auditor, observer)",
    },
    {
        "number": 3,
        "name": "Alerting Configuration",
        "description": "Configure webhook, Slack, or email alerts for governance events",
    },
    {
        "number": 4,
        "name": "SIEM Integration",
        "description": "Connect chain events to Splunk (CEF), Datadog (JSON), or syslog",
    },
    {
        "number": 5,
        "name": "Compliance Framework",
        "description": "Select compliance standard (SOX, HIPAA, FERPA) and map governance controls",
    },
    {
        "number": 6,
        "name": "Federation Setup",
        "description": "Add remote Charter nodes for federated governance visibility",
    },
    {
        "number": 7,
        "name": "Gap Analysis",
        "description": "Run compliance gap analysis against selected framework",
    },
    {
        "number": 8,
        "name": "First Audit",
        "description": "Generate initial governance audit to verify everything works",
    },
]


def _get_onboard_state_path():
    """Path to ~/.charter/onboard_state.json"""
    home = os.path.expanduser("~")
    return os.path.join(home, ".charter", "onboard_state.json")


def _load_onboard_state():
    """Load onboarding state. Returns dict."""
    path = _get_onboard_state_path()
    if not os.path.isfile(path):
        return {"steps_completed": [], "started_at": None, "last_step_at": None}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"steps_completed": [], "started_at": None, "last_step_at": None}


def _save_onboard_state(state):
    """Save onboarding state."""
    path = _get_onboard_state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def _mark_step_complete(step_number):
    """Mark a step as complete in the onboarding state."""
    state = _load_onboard_state()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if not state["started_at"]:
        state["started_at"] = now

    if step_number not in state["steps_completed"]:
        state["steps_completed"].append(step_number)
        state["steps_completed"].sort()

    state["last_step_at"] = now
    _save_onboard_state(state)

    # Log to chain
    try:
        from charter.identity import append_to_chain
        append_to_chain("onboard_step_completed", {
            "step": step_number,
            "step_name": ONBOARD_STEPS[step_number - 1]["name"],
        }, auto_batch=False)
    except Exception:
        pass


def _check_prerequisites(step_number):
    """Check if prerequisites for a step are met.

    Returns (ok, message).
    """
    state = _load_onboard_state()
    completed = state["steps_completed"]

    # Step 1 has no prerequisites
    if step_number == 1:
        return True, ""

    # Step 1 (license) is a prerequisite for all other steps
    if 1 not in completed:
        return False, "Step 1 (License Activation) must be completed first"

    # Steps 7 and 8 need step 5 (compliance framework selection)
    if step_number in (7, 8) and 5 not in completed:
        return False, "Step 5 (Compliance Framework) must be completed first"

    return True, ""


# --- Step implementations ---

def _step_1_license():
    """Step 1: Verify Enterprise license."""
    from charter.licensing import get_current_tier, TIER_ENTERPRISE, get_license_status

    tier = get_current_tier()
    if tier == TIER_ENTERPRISE:
        status = get_license_status()
        print("  License: Enterprise ACTIVE")
        print(f"  Seats:   {status.get('seats', 1)}")
        print(f"  Since:   {status.get('activated_at', 'unknown')}")
        _mark_step_complete(1)
        return True
    else:
        print(f"  Current tier: {tier}")
        print("  Enterprise license required. Run: charter activate <key>")
        return False


def _step_2_rbac():
    """Step 2: RBAC setup."""
    try:
        from charter.roles import get_team_roles
    except ImportError:
        print("  RBAC module not available.")
        _mark_step_complete(2)
        return True

    print("  RBAC (Role-Based Access Control) configures governance roles:")
    print("    - operator:  Full governance control")
    print("    - reviewer:  Can approve/reject rule proposals")
    print("    - auditor:   Read-only access to audit trails")
    print("    - observer:  Dashboard view only")
    print()
    print("  To assign roles:")
    print("    charter role assign --team <hash> --member <id> --role operator")
    print()
    print("  To propose new governance rules (requires dual signoff):")
    print("    charter role propose --team <hash> --rule 'Never ...' --layer a")
    print()
    _mark_step_complete(2)
    return True


def _step_3_alerting():
    """Step 3: Alerting configuration."""
    print("  Configure alerts for governance events:")
    print()
    print("  Add to your charter.yaml:")
    print("    alerting:")
    print("      webhooks:")
    print("        - url: 'https://hooks.slack.com/services/...'")
    print("          events: ['kill_trigger_fired', 'chain_integrity_failure']")
    print("          secret: 'optional-hmac-secret'")
    print()
    print("  Supported channels:")
    print("    - Webhooks (any URL, HMAC-SHA256 signed)")
    print("    - Slack (incoming webhook URL)")
    print("    - Email (SMTP, stdlib smtplib)")
    print()
    print("  Test your configuration:")
    print("    charter alert test")
    print()
    _mark_step_complete(3)
    return True


def _step_4_siem():
    """Step 4: SIEM integration."""
    print("  Connect governance events to your SIEM:")
    print()
    print("  Formats supported:")
    print("    - CEF (Common Event Format) — Splunk")
    print("    - Structured JSON — Datadog")
    print("    - RFC 5424 syslog — any syslog receiver")
    print()
    print("  Export existing events:")
    print("    charter siem export --format cef")
    print("    charter siem export --format json")
    print("    charter siem export --format syslog")
    print()
    print("  Stream in real-time:")
    print("    charter siem stream --format cef")
    print()
    _mark_step_complete(4)
    return True


def _step_5_compliance():
    """Step 5: Compliance framework selection."""
    print("  Select a compliance framework to map your governance controls against:")
    print()
    print("  Available standards:")
    print("    - SOX  (Sarbanes-Oxley, 10 controls)")
    print("    - HIPAA (Health Insurance Portability, 15 controls)")
    print("    - FERPA (Family Educational Rights, 12 controls)")
    print()
    print("  Generate a mapping:")
    print("    charter compliance map --standard hipaa")
    print()
    print("  View available standards:")
    print("    charter compliance standards")
    print()
    _mark_step_complete(5)
    return True


def _step_6_federation():
    """Step 6: Federation setup."""
    print("  Federated governance connects multiple Charter nodes:")
    print()
    print("  Each node is sovereign — owns its data, chain, and rules.")
    print("  Federation provides read-only aggregation. No centralization. Ever.")
    print()
    print("  Add a remote node:")
    print("    charter federation add --sse-url http://node:8375/sse --alias 'Production'")
    print()
    print("  View federated status:")
    print("    charter federation status")
    print()
    print("  View event stream across all nodes:")
    print("    charter federation events --limit 50")
    print()
    _mark_step_complete(6)
    return True


def _step_7_gap_analysis():
    """Step 7: Initial gap analysis."""
    print("  Running gap analysis against your governance configuration...")
    print()

    try:
        from charter.compliance import ComplianceMapper
        from charter.config import load_config, find_config

        config_path = find_config()
        if config_path:
            config = load_config(config_path)
            mapper = ComplianceMapper(config)
            # Try all standards
            for standard in ["sox", "hipaa", "ferpa"]:
                try:
                    gaps = mapper.gap_analysis(standard)
                    covered = gaps.get("covered", 0)
                    total = gaps.get("total", 0)
                    pct = (covered / total * 100) if total > 0 else 0
                    print(f"  {standard.upper()}: {covered}/{total} controls covered ({pct:.0f}%)")
                except Exception:
                    pass
            print()
        else:
            print("  No charter.yaml found. Run 'charter init' first.")
            print()
    except ImportError:
        print("  Compliance module not available.")
        print()

    print("  For detailed reports:")
    print("    charter compliance report --standard hipaa")
    print("    charter compliance gap --standard sox")
    print()
    _mark_step_complete(7)
    return True


def _step_8_first_audit():
    """Step 8: First audit."""
    print("  Generating initial governance audit...")
    print()

    try:
        from charter.audit import run_audit
        import argparse
        audit_args = argparse.Namespace(config="charter.yaml", period="session")
        run_audit(audit_args)
        print()
    except Exception as e:
        print(f"  Audit generation: {e}")
        print("  You can run manually: charter audit --period session")
        print()

    _mark_step_complete(8)
    return True


STEP_RUNNERS = {
    1: _step_1_license,
    2: _step_2_rbac,
    3: _step_3_alerting,
    4: _step_4_siem,
    5: _step_5_compliance,
    6: _step_6_federation,
    7: _step_7_gap_analysis,
    8: _step_8_first_audit,
}


# --- CLI entry point ---

def run_onboard(args):
    """Handle `charter onboard [--step N] [--status]`."""
    if getattr(args, "status", False):
        _show_status()
        return

    step = getattr(args, "step", None)
    if step is not None:
        if step < 1 or step > 8:
            print(f"Invalid step: {step}. Must be 1-8.")
            return
        _run_step(step)
    else:
        _run_all_steps()


def _show_status():
    """Show onboarding progress."""
    state = _load_onboard_state()
    completed = state["steps_completed"]

    print("Charter Enterprise Onboarding")
    print()

    if state["started_at"]:
        print(f"  Started: {state['started_at']}")
    if state["last_step_at"]:
        print(f"  Last:    {state['last_step_at']}")
    print(f"  Progress: {len(completed)}/8 steps")
    print()

    for step_info in ONBOARD_STEPS:
        num = step_info["number"]
        mark = "[x]" if num in completed else "[ ]"
        print(f"  {mark} Step {num}: {step_info['name']}")
        if num not in completed:
            print(f"        {step_info['description']}")
    print()

    if len(completed) == 8:
        print("  Onboarding complete!")
    else:
        next_step = None
        for s in range(1, 9):
            if s not in completed:
                next_step = s
                break
        if next_step:
            print(f"  Next: charter onboard --step {next_step}")


def _run_step(step_number):
    """Run a single onboarding step."""
    step_info = ONBOARD_STEPS[step_number - 1]

    print(f"Step {step_number}/8: {step_info['name']}")
    print(f"  {step_info['description']}")
    print()

    ok, msg = _check_prerequisites(step_number)
    if not ok:
        print(f"  Prerequisite not met: {msg}")
        return

    runner = STEP_RUNNERS.get(step_number)
    if runner:
        runner()


def _run_all_steps():
    """Run all incomplete onboarding steps sequentially."""
    state = _load_onboard_state()
    completed = state["steps_completed"]

    print("Charter Enterprise Onboarding Wizard")
    print("=" * 40)
    print()

    all_done = True
    for step_info in ONBOARD_STEPS:
        num = step_info["number"]
        if num in completed:
            print(f"Step {num}/8: {step_info['name']} — already complete")
            print()
            continue

        all_done = False
        print(f"Step {num}/8: {step_info['name']}")
        print(f"  {step_info['description']}")
        print()

        ok, msg = _check_prerequisites(num)
        if not ok:
            print(f"  Skipping: {msg}")
            print()
            continue

        runner = STEP_RUNNERS.get(num)
        if runner:
            runner()
        print()

    if all_done:
        print("All onboarding steps complete!")
    else:
        state = _load_onboard_state()
        completed = state["steps_completed"]
        print(f"Progress: {len(completed)}/8 steps complete")
