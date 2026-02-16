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

    # charter status
    sub.add_parser("status", help="Show current governance status")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    if args.command == "init":
        from charter.init_cmd import run_init
        run_init(args)
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
    elif args.command == "status":
        from charter.status import run_status
        run_status(args)
