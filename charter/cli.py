"""Charter CLI — governance layer for AI agents."""

import argparse
import sys

from charter import __version__


def main():
    parser = argparse.ArgumentParser(
        prog="charter",
        description="AI governance layer. Three layers: hard constraints, gradient decisions, self-audit.",
    )
    parser.add_argument("--version", action="version", version=f"charter {__version__}")

    sub = parser.add_subparsers(dest="command")

    # charter bootstrap
    boot_p = sub.add_parser("bootstrap", help="One command: init + generate + audit. Use this.")
    boot_p.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Project directory (default: current directory)",
    )
    boot_p.add_argument(
        "--domain",
        choices=["healthcare", "finance", "education", "general"],
        help="Domain preset (auto-detected if omitted)",
    )
    boot_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing charter.yaml",
    )
    boot_p.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Minimal output (for automated use)",
    )

    # charter init
    init_p = sub.add_parser("init", help="Create a governance config for your project")
    init_p.add_argument(
        "--domain",
        choices=["healthcare", "finance", "education", "general"],
        help="Domain preset (skips interactive prompt)",
    )
    init_p.add_argument(
        "--non-interactive",
        action="store_true",
        help="Use defaults without prompting",
    )
    init_p.add_argument(
        "--full",
        action="store_true",
        help="Also generate CLAUDE.md, system-prompt.txt, and first audit",
    )

    # charter generate
    gen_p = sub.add_parser("generate", help="Generate governance instructions from config")
    gen_p.add_argument(
        "--format",
        choices=["claude-md", "system-prompt", "raw"],
        default="claude-md",
        help="Output format (default: claude-md)",
    )
    gen_p.add_argument(
        "--output", "-o",
        help="Output file path (default: stdout for system-prompt/raw, CLAUDE.md for claude-md)",
    )
    gen_p.add_argument(
        "--config", "-c",
        default="charter.yaml",
        help="Path to charter.yaml (default: ./charter.yaml)",
    )

    # charter audit
    audit_p = sub.add_parser("audit", help="Generate a governance audit report")
    audit_p.add_argument(
        "--config", "-c",
        default="charter.yaml",
        help="Path to charter.yaml",
    )
    audit_p.add_argument(
        "--period",
        default="week",
        choices=["day", "week", "month", "session"],
        help="Audit period (default: week)",
    )

    # charter identity
    id_p = sub.add_parser("identity", help="Manage your pseudonymous identity")
    id_p.add_argument(
        "action",
        choices=["show", "verify", "proof", "export"],
        nargs="?",
        default="show",
        help="Identity action",
    )

    # charter context
    ctx_p = sub.add_parser("context", help="Manage work/personal knowledge contexts")
    ctx_p.add_argument(
        "action",
        choices=["list", "create", "switch", "show", "bridge", "approve", "revoke"],
        help="Context action",
    )
    ctx_p.add_argument("name", nargs="?", help="Context name or bridge ID")
    ctx_p.add_argument("--type", choices=["personal", "work"], help="Context type")
    ctx_p.add_argument("--target", help="Target context for bridge")
    ctx_p.add_argument("--policy", choices=["read-only", "bidirectional", "items-only"], help="Bridge policy")
    ctx_p.add_argument("--org", help="Organization name (for work contexts)")
    ctx_p.add_argument("--email", help="Work email (initial crosswalk to org systems)")

    # charter connect
    conn_p = sub.add_parser("connect", help="Network: create node, register expertise, connect to peers")
    conn_p.add_argument(
        "action",
        choices=["init", "status", "source", "formation", "contribute"],
        help="Network action",
    )
    conn_p.add_argument("name", nargs="?", help="Name/title for the action")
    conn_p.add_argument("extra", nargs="?", help="Additional parameter (type, etc.)")

    # charter verify
    verify_p = sub.add_parser("verify", help="Verify identity via Persona or ID.me")
    verify_p.add_argument(
        "action",
        choices=["configure", "start", "check", "status"],
        help="Verification action",
    )
    verify_p.add_argument("provider", nargs="?", help="Provider name (persona, id_me) or inquiry ID")
    verify_p.add_argument("name", nargs="?", help="Inquiry ID for check command")
    verify_p.add_argument("--provider", dest="provider_flag", help="Provider for start command")

    # charter serve
    serve_p = sub.add_parser("serve", help="Start the governance daemon and web dashboard")
    serve_p.add_argument(
        "--port", "-p",
        type=int,
        default=8374,
        help="Port for the web dashboard (default: 8374)",
    )
    serve_p.add_argument(
        "--interval",
        type=int,
        default=60,
        help="AI tool scan interval in seconds (default: 60)",
    )

    # charter detect
    sub.add_parser("detect", help="One-shot scan for AI tools on this machine")

    # charter install
    sub.add_parser("install", help="Install the daemon as a system service")

    # charter inject
    inject_p = sub.add_parser("inject", help="Inject governance rules into a project")
    inject_p.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Project directory path (default: current directory)",
    )
    inject_p.add_argument(
        "--config", "-c",
        default="charter.yaml",
        help="Path to charter.yaml",
    )

    # charter stamp
    stamp_p = sub.add_parser("stamp", help="Create an attribution stamp for a work product")
    stamp_p.add_argument(
        "--format", "-f",
        choices=["trailer", "json", "header"],
        default="trailer",
        help="Output format (default: trailer)",
    )
    stamp_p.add_argument(
        "--language", "-l",
        default="python",
        help="Language for header format (default: python)",
    )
    stamp_p.add_argument(
        "--description", "-d",
        help="Description of the work product",
    )

    # charter attest
    attest_p = sub.add_parser("attest", help="Attest an ungoverned work product for institutional use")
    attest_p.add_argument(
        "file",
        help="Path to the file to attest",
    )
    attest_p.add_argument(
        "--reason", "-r",
        help="Why this work product is acceptable (required for audit trail)",
    )
    attest_p.add_argument(
        "--reviewer",
        help="Reviewer name (defaults to identity alias)",
    )

    # charter check (verify a stamp file)
    check_p = sub.add_parser("check", help="Verify an attribution stamp file")
    check_p.add_argument(
        "stamp_file",
        help="Path to a stamp JSON file",
    )

    # charter mcp-serve
    mcp_p = sub.add_parser("mcp-serve", help="Start Charter as an MCP server")
    mcp_p.add_argument(
        "--transport", "-t",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport mode (default: stdio for Claude Code)",
    )
    mcp_p.add_argument(
        "--port", "-p",
        type=int,
        default=8375,
        help="Port for SSE transport (default: 8375)",
    )

    # charter join
    join_p = sub.add_parser("join", help="One command: decode invite token, create identity, join team")
    join_p.add_argument("token", help="Invite token from charter team invite")

    # charter team
    team_p = sub.add_parser("team", help="Create and manage governed teams")
    team_p.add_argument(
        "action",
        choices=["create", "invite", "accept", "leave", "revoke", "status", "list"],
        help="Team action",
    )
    team_p.add_argument("value", nargs="?", help="Team name, email, or team hash")
    team_p.add_argument("--role", help="Member role (for invite)")
    team_p.add_argument("--name", help="Member display name (for invite)")

    # charter merkle
    merkle_p = sub.add_parser("merkle", help="Merkle tree operations for production-scale verification")
    merkle_p.add_argument(
        "action",
        choices=["batch", "prove", "verify", "exchange", "status"],
        help="Merkle action",
    )
    merkle_p.add_argument(
        "index",
        nargs="?",
        type=int,
        help="Chain entry index (for prove, verify, exchange)",
    )
    merkle_p.add_argument(
        "--batch-size",
        type=int,
        default=256,
        help="Max entries per batch (default: 256)",
    )
    merkle_p.add_argument(
        "--min-entries",
        type=int,
        default=16,
        help="Min entries to trigger batching (default: 16)",
    )
    merkle_p.add_argument(
        "--output", "-o",
        help="Output file for exchange proof (default: stdout)",
    )

    # charter timestamp
    ts_p = sub.add_parser("timestamp", help="RFC 3161 timestamp anchoring for dispute-ready evidence")
    ts_p.add_argument(
        "action",
        choices=["anchor", "verify", "status"],
        nargs="?",
        default="status",
        help="Timestamp action (default: status)",
    )

    # charter dispute
    disp_p = sub.add_parser("dispute", help="Export chain evidence for dispute examination")
    disp_p.add_argument(
        "action",
        choices=["export", "verify", "inspect"],
        help="Dispute action",
    )
    disp_p.add_argument(
        "--from", dest="from_index",
        type=int,
        help="Starting chain index",
    )
    disp_p.add_argument(
        "--to", dest="to_index",
        type=int,
        help="Ending chain index",
    )
    disp_p.add_argument(
        "--output", "-o",
        help="Output file path (default: stdout)",
    )
    disp_p.add_argument(
        "--package",
        help="Path to dispute package file (for verify/inspect)",
    )

    # charter confidence
    conf_p = sub.add_parser(
        "confidence",
        help="Tag chain entries with confidence levels and revision linkage",
    )
    conf_p.add_argument(
        "action",
        choices=["tag", "revisions", "history"],
        help="Confidence action",
    )
    conf_p.add_argument(
        "target",
        nargs="?",
        help="Chain entry index (for tag) or entry hash (for revisions/history)",
    )
    conf_p.add_argument(
        "--level",
        choices=["verified", "inferred", "exploratory"],
        help="Confidence level (for tag)",
    )
    conf_p.add_argument(
        "--basis",
        help="Evidence basis for the confidence tag",
    )
    conf_p.add_argument(
        "--assumptions",
        help="Comma-separated constraint assumptions",
    )

    # charter redteam
    rt_p = sub.add_parser(
        "redteam",
        help="Adversarial testing of governance defenses",
    )
    rt_p.add_argument(
        "action",
        choices=["run", "generate", "report"],
        nargs="?",
        default="run",
        help="Red team action (default: run)",
    )
    rt_p.add_argument(
        "threats_file",
        nargs="?",
        help="Path to enterprise threat log (for generate)",
    )
    rt_p.add_argument(
        "--category",
        help="Comma-separated categories to test",
    )
    rt_p.add_argument(
        "--config", "-c",
        help="Path to charter.yaml",
    )

    # charter arbitrate
    arb_p = sub.add_parser(
        "arbitrate",
        help="Multi-model arbitration for critical decisions",
    )
    arb_p.add_argument(
        "--question", "-q",
        required=True,
        help="The question or decision to arbitrate",
    )
    arb_p.add_argument(
        "--models", "-m",
        help="Comma-separated model names (default: auto based on reversibility)",
    )
    arb_p.add_argument(
        "--reversibility",
        choices=["reversible", "low_reversibility", "irreversible"],
        help="Override reversibility classification",
    )

    # charter role
    role_p = sub.add_parser(
        "role",
        help="RBAC, dual signoff, and Layer 0 invariant enforcement",
    )
    role_p.add_argument(
        "action",
        choices=["assign", "propose", "sign", "status", "invariants"],
        help="Role action",
    )
    role_p.add_argument("--team", help="Team hash")
    role_p.add_argument("--member", help="Member public ID")
    role_p.add_argument(
        "--role",
        choices=["operator", "reviewer", "auditor", "observer"],
        help="Governance role to assign",
    )
    role_p.add_argument("--rule", help="Rule text for proposal")
    role_p.add_argument("--layer", choices=["a", "b"], help="Layer for proposed rule")
    role_p.add_argument("--proposal", help="Proposal ID to sign")
    role_p.add_argument(
        "--approve",
        action="store_true",
        default=True,
        help="Approve the proposal (default)",
    )
    role_p.add_argument(
        "--reject",
        action="store_true",
        help="Reject the proposal",
    )

    # charter alert
    alert_p = sub.add_parser(
        "alert",
        help="Alerting pipeline for governance events",
    )
    alert_p.add_argument(
        "action",
        choices=["test", "status", "configure"],
        nargs="?",
        default="status",
        help="Alert action (default: status)",
    )

    # charter siem
    siem_p = sub.add_parser(
        "siem",
        help="Export chain events for SIEM integration (Splunk, Datadog, syslog)",
    )
    siem_p.add_argument(
        "action",
        choices=["export", "stream", "status"],
        nargs="?",
        default="status",
        help="SIEM action (default: status)",
    )
    siem_p.add_argument(
        "--format", "-f",
        choices=["cef", "json", "syslog"],
        default="cef",
        help="Export format (default: cef)",
    )
    siem_p.add_argument("--from", dest="from_index", type=int, help="Starting chain index")
    siem_p.add_argument("--to", dest="to_index", type=int, help="Ending chain index")

    # charter compliance
    comp_p = sub.add_parser(
        "compliance",
        help="Map governance to regulatory compliance frameworks (SOX, HIPAA, FERPA, SOC 2, GDPR, EU AI Act, NIST AI RMF, ISO 27001)",
    )
    comp_p.add_argument(
        "action",
        choices=["map", "report", "gap", "standards"],
        nargs="?",
        default="map",
        help="Compliance action (default: map)",
    )
    comp_p.add_argument(
        "--standard", "-s",
        help="Compliance standard (sox, hipaa, ferpa, soc2, gdpr, eu_ai_act, nist_ai_rmf, iso27001)",
    )
    comp_p.add_argument(
        "--config", "-c",
        help="Path to charter.yaml",
    )
    comp_p.add_argument(
        "--output", "-o",
        help="Output file path (report action only)",
    )
    comp_p.add_argument(
        "--format", "-f",
        choices=["markdown"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    # charter federation
    fed_p = sub.add_parser(
        "federation",
        help="Federated governance dashboard — aggregate status across Charter nodes",
    )
    fed_p.add_argument(
        "action",
        choices=["status", "add", "remove", "events"],
        nargs="?",
        default="status",
        help="Federation action (default: status)",
    )
    fed_p.add_argument("--sse-url", help="SSE URL of the node to add")
    fed_p.add_argument("--alias", help="Alias for the node")
    fed_p.add_argument("--node-id", help="Node ID (for remove; auto-discovered for add)")
    fed_p.add_argument("--limit", type=int, default=50, help="Event stream limit (default: 50)")

    # charter activate
    act_p = sub.add_parser("activate", help="Activate a Charter Pro or Enterprise license key")
    act_p.add_argument("key", help="License key (e.g. CHARTER-PRO-a1b2c3d4-e5f6)")

    # charter license
    sub.add_parser("license", help="Show current license status and tier")

    # charter upgrade
    sub.add_parser("upgrade", help="Show upgrade options with payment links")

    # charter onboard
    onb_p = sub.add_parser("onboard", help="Enterprise onboarding wizard (Enterprise tier)")
    onb_p.add_argument(
        "--step",
        type=int,
        help="Run a specific onboarding step (1-8)",
    )
    onb_p.add_argument(
        "--status",
        action="store_true",
        help="Show onboarding progress",
    )

    # charter status
    sub.add_parser("status", help="Show current governance status")

    # charter update
    sub.add_parser("update", help="Check for and install newer versions")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Import license gating
    from charter.licensing import gate, LicenseError

    try:
        _run_command(args, gate)
    except LicenseError as e:
        print(str(e))
        sys.exit(1)


def _run_command(args, gate):
    """Dispatch to the appropriate command handler."""
    if args.command == "bootstrap":
        from charter.bootstrap import run_bootstrap
        run_bootstrap(args)
    elif args.command == "init":
        from charter.init_cmd import run_init
        run_init(args)
        if args.full:
            # Run bootstrap after init to generate all files
            import argparse as _ap
            boot_args = _ap.Namespace(path=".", domain=args.domain, force=False, quiet=False)
            from charter.bootstrap import run_bootstrap
            run_bootstrap(boot_args)
    elif args.command == "generate":
        from charter.generate import run_generate
        run_generate(args)
    elif args.command == "audit":
        from charter.audit import run_audit
        run_audit(args)
    elif args.command == "identity":
        from charter.identity import run_identity
        run_identity(args)
    elif args.command == "context":
        from charter.context import run_context
        run_context(args)
    elif args.command == "connect":
        from charter.network import run_connect
        run_connect(args)
    elif args.command == "verify":
        from charter.verify import run_verify
        run_verify(args)
    elif args.command == "serve":
        gate("serve")
        from charter.daemon.service import run_serve
        run_serve(args)
    elif args.command == "detect":
        from charter.daemon.service import run_detect
        run_detect(args)
    elif args.command == "install":
        from charter.daemon.service import run_install
        run_install(args)
    elif args.command == "inject":
        from charter.daemon.injector import inject_claude_md
        import os
        result = inject_claude_md(os.path.abspath(args.path), config_path=args.config)
        if result:
            print(f"Governance injected: {result}")
        else:
            print("No charter.yaml found. Run 'charter init' first.")
    elif args.command == "stamp":
        from charter.stamp import run_stamp
        run_stamp(args)
    elif args.command == "attest":
        from charter.stamp import run_attest
        run_attest(args)
    elif args.command == "check":
        from charter.stamp import run_verify
        run_verify(args)
    elif args.command == "mcp-serve":
        gate("mcp-serve")
        from charter.mcp_server import run_mcp_serve
        run_mcp_serve(args)
    elif args.command == "join":
        from charter.join import run_join
        run_join(args.token)
    elif args.command == "team":
        from charter.team import run_team
        run_team(args)
    elif args.command == "merkle":
        from charter.merkle import (
            batch_chain_entries,
            generate_proof,
            verify_chain_entry,
            create_exchange_proof,
            load_batch_index,
        )
        from charter.identity import get_chain_path
        import json as _json

        if args.action == "batch":
            chain_path = get_chain_path()
            result = batch_chain_entries(
                chain_path,
                batch_size=args.batch_size,
                min_entries=args.min_entries,
            )
            if result:
                print(f"Merkle Batch Created")
                print(f"  Batch ID:    {result['batch_id']}")
                print(f"  Root:        {result['root'][:32]}...")
                print(f"  Leaves:      {result['leaf_count']}")
                print(f"  Depth:       {result['depth']}")
                print(f"  Chain range: [{result['chain_range'][0]}, {result['chain_range'][1]}]")
            else:
                idx = load_batch_index()
                unbatched = "unknown"
                import os
                chain_path = get_chain_path()
                if os.path.isfile(chain_path):
                    with open(chain_path) as f:
                        total = sum(1 for line in f if line.strip())
                    batched = idx["last_chain_index"] + 1 if idx["last_chain_index"] >= 0 else 0
                    unbatched = total - batched
                print(f"Not enough unbatched entries (have {unbatched}, need {args.min_entries})")

        elif args.action == "prove":
            if args.index is None:
                print("Usage: charter merkle prove <chain_index>")
                return
            result = generate_proof(args.index)
            if result:
                print(f"Merkle Proof for chain entry {args.index}")
                print(f"  Batch:       {result['batch_id']}")
                print(f"  Root:        {result['merkle_root'][:32]}...")
                print(f"  Leaf:        {result['leaf_hash'][:32]}...")
                print(f"  Proof steps: {result['proof_length']}")
                print(f"  Dataset:     {result['batch_leaf_count']} entries")
                print()
                print(f"  {result['verification']['equivalent_dataset_size']}")
            else:
                print(f"Chain entry {args.index} not yet batched. Run 'charter merkle batch' first.")

        elif args.action == "verify":
            if args.index is None:
                print("Usage: charter merkle verify <chain_index>")
                return
            # Load the entry hash from chain
            chain_path = get_chain_path()
            import os
            if not os.path.isfile(chain_path):
                print("No chain found.")
                return
            with open(chain_path) as f:
                entries = [_json.loads(line) for line in f if line.strip()]
            entry = None
            for e in entries:
                if e.get("index") == args.index:
                    entry = e
                    break
            if not entry:
                print(f"Chain entry {args.index} not found.")
                return
            result = verify_chain_entry(args.index, entry["hash"])
            status = "VERIFIED" if result["verified"] else "FAILED"
            print(f"Merkle Verification: {status}")
            print(f"  Chain index: {result['chain_index']}")
            print(f"  Reason:      {result['reason']}")
            if result.get("batch_id"):
                print(f"  Batch:       {result['batch_id']}")
                print(f"  Root:        {result['merkle_root'][:32]}...")
                print(f"  Proof steps: {result['proof_steps']}")

        elif args.action == "exchange":
            if args.index is None:
                print("Usage: charter merkle exchange <chain_index>")
                return
            result = create_exchange_proof(args.index)
            if not result:
                print(f"Could not create exchange proof for entry {args.index}.")
                return
            output = _json.dumps(result, indent=2)
            if args.output:
                with open(args.output, "w") as f:
                    f.write(output)
                print(f"Exchange proof saved to: {args.output}")
            else:
                print(output)

        elif args.action == "status":
            idx = load_batch_index()
            chain_path = get_chain_path()
            total_chain = 0
            import os
            if os.path.isfile(chain_path):
                with open(chain_path) as f:
                    total_chain = sum(1 for line in f if line.strip())
            batched = idx["last_chain_index"] + 1 if idx["last_chain_index"] >= 0 else 0
            unbatched = total_chain - batched

            print(f"Merkle Tree Status")
            print(f"  Chain entries:   {total_chain}")
            print(f"  Batched:         {batched}")
            print(f"  Unbatched:       {unbatched}")
            print(f"  Total batches:   {len(idx['batches'])}")
            if idx["batches"]:
                latest = idx["batches"][-1]
                print(f"  Latest batch:    {latest['batch_id']}")
                print(f"  Latest root:     {latest['root'][:32]}...")
                print(f"  Latest range:    [{latest['chain_range'][0]}, {latest['chain_range'][1]}]")

    elif args.command == "confidence":
        gate("confidence")
        from charter.confidence import run_confidence
        run_confidence(args)
    elif args.command == "redteam":
        gate("redteam")
        from charter.redteam import run_redteam
        run_redteam(args)
    elif args.command == "arbitrate":
        gate("arbitrate")
        from charter.arbitration import run_arbitrate
        run_arbitrate(args)
    elif args.command == "role":
        gate("role")
        from charter.roles import run_roles
        # Translate --reject flag to approve=False
        if getattr(args, "reject", False):
            args.approve = False
        run_roles(args)
    elif args.command == "alert":
        gate("alert")
        from charter.alerting import run_alerting
        run_alerting(args)
    elif args.command == "siem":
        gate("siem")
        from charter.siem import run_siem
        run_siem(args)
    elif args.command == "compliance":
        gate("compliance")
        from charter.compliance import run_compliance
        run_compliance(args)
    elif args.command == "federation":
        gate("federation")
        from charter.federation import run_federation
        run_federation(args)
    elif args.command == "timestamp":
        from charter.timestamp import run_timestamp
        run_timestamp(args)
    elif args.command == "dispute":
        from charter.dispute import run_dispute
        run_dispute(args)
    elif args.command == "activate":
        from charter.licensing import run_activate
        run_activate(args)
    elif args.command == "license":
        from charter.licensing import run_license
        run_license(args)
    elif args.command == "upgrade":
        from charter.licensing import run_upgrade
        run_upgrade(args)
    elif args.command == "onboard":
        gate("onboard")
        from charter.onboard import run_onboard
        run_onboard(args)
    elif args.command == "status":
        from charter.status import run_status
        run_status(args)
    elif args.command == "update":
        from charter.update import run_update
        run_update(args)
