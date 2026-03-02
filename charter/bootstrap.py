"""charter bootstrap — one command to fully govern a project."""

import json
import os
import shutil
import sys
import time
import argparse

from charter.config import load_config, save_config, CONFIG_NAME
from charter.identity import load_identity, create_identity, append_to_chain


def detect_domain(path="."):
    """Infer project domain from files present in the directory."""
    path = os.path.abspath(path)
    indicators = {
        "healthcare": [
            "hipaa", "hl7", "fhir", "dicom", "clinical", "patient",
            "pharmacy", "medication", "diagnosis", "ehr",
        ],
        "finance": [
            "transaction", "ledger", "payment", "invoice", "banking",
            "trading", "portfolio", "compliance", "kyc", "aml",
        ],
        "education": [
            "ferpa", "student", "curriculum", "grading", "enrollment",
            "classroom", "syllabus", "lms",
        ],
    }

    # Check file names and contents of key files
    signal_files = []
    for f in os.listdir(path):
        signal_files.append(f.lower())

    # Also check README, package files for keywords
    content_files = ["README.md", "README.txt", "README", "package.json",
                     "pyproject.toml", "setup.py", "setup.cfg", "Cargo.toml"]
    text_blob = " ".join(signal_files)
    for cf in content_files:
        cf_path = os.path.join(path, cf)
        if os.path.isfile(cf_path):
            try:
                with open(cf_path, "r", errors="ignore") as fh:
                    text_blob += " " + fh.read(4096).lower()
            except Exception:
                pass

    scores = {}
    for domain, keywords in indicators.items():
        scores[domain] = sum(1 for kw in keywords if kw in text_blob)

    best = max(scores, key=scores.get)
    if scores[best] >= 2:
        return best
    return "general"


def _find_charter_command():
    """Find the charter CLI command path.

    Tries in order:
    1. `charter` on PATH (pip install)
    2. `python3 -m charter.mcp_server` (module invocation)
    """
    charter_path = shutil.which("charter")
    if charter_path:
        return charter_path, [charter_path, "mcp-serve", "--transport", "stdio"]

    # Fallback: use python module invocation
    python_path = shutil.which("python3") or shutil.which("python") or sys.executable
    return python_path, [python_path, "-m", "charter.mcp_server"]


def _mcp_server_entry():
    """Build the MCP server config dict for .mcp.json files."""
    cmd_path, args = _find_charter_command()
    return {
        "command": args[0],
        "args": args[1:],
    }


def generate_mcp_configs(target_dir, quiet=False):
    """Generate MCP config files for Claude Code and Cursor.

    Creates/updates:
    - .mcp.json (Claude Code) — project-level
    - .cursor/mcp.json (Cursor) — project-level

    If these files already exist, merges the charter server entry
    without overwriting other MCP server configs.

    Returns list of files created/updated.
    """
    server_config = _mcp_server_entry()
    files_touched = []

    # --- Claude Code: .mcp.json ---
    claude_mcp_path = os.path.join(target_dir, ".mcp.json")
    _merge_mcp_config(claude_mcp_path, "charter-governance", server_config)
    files_touched.append(".mcp.json")

    # --- Cursor: .cursor/mcp.json ---
    cursor_dir = os.path.join(target_dir, ".cursor")
    cursor_mcp_path = os.path.join(cursor_dir, "mcp.json")
    os.makedirs(cursor_dir, exist_ok=True)
    _merge_mcp_config(cursor_mcp_path, "charter-governance", server_config)
    files_touched.append(".cursor/mcp.json")

    return files_touched


def _merge_mcp_config(filepath, server_name, server_config):
    """Merge a server entry into an MCP config file.

    If the file exists, loads it and adds/updates the server entry.
    If not, creates a new file with just the charter server.
    Preserves all other server configs.
    """
    existing = {}
    if os.path.isfile(filepath):
        try:
            with open(filepath) as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            existing = {}

    if "mcpServers" not in existing:
        existing["mcpServers"] = {}

    existing["mcpServers"][server_name] = server_config

    with open(filepath, "w") as f:
        json.dump(existing, f, indent=2)
        f.write("\n")


def run_bootstrap(args):
    """Execute charter bootstrap — full project setup in one command."""
    target = os.path.abspath(args.path if hasattr(args, "path") and args.path else ".")
    original_dir = os.getcwd()

    try:
        os.chdir(target)

        start = time.time()

        domain = args.domain if hasattr(args, "domain") and args.domain else None
        quiet = hasattr(args, "quiet") and args.quiet

        if not quiet:
            print("Charter — Bootstrap")
            print("=" * 40)

        # Step 1: Auto-detect domain if not specified
        if not domain:
            domain = detect_domain(target)
            if not quiet:
                print(f"  Domain detected: {domain}")

        # Step 2: Create charter.yaml (skip if exists, unless --force)
        force = hasattr(args, "force") and args.force
        if os.path.isfile(CONFIG_NAME) and not force:
            if not quiet:
                print(f"  Config exists:   {CONFIG_NAME} (keeping)")
            config = load_config(CONFIG_NAME)
        else:
            from charter.init_cmd import load_template
            config = load_template(domain)
            config["version"] = "1.0"

            identity = load_identity()
            if identity:
                if not quiet:
                    print(f"  Identity:        {identity['alias']} (existing)")
                config["identity"] = {
                    "public_id": identity["public_id"],
                    "alias": identity["alias"],
                }
            else:
                identity = create_identity()
                if not quiet:
                    print(f"  Identity:        {identity['alias']} (created)")
                config["identity"] = {
                    "public_id": identity["public_id"],
                    "alias": identity["alias"],
                }

            save_config(config)
            if not quiet:
                print(f"  Config:          {CONFIG_NAME} (created)")

        # Step 3: Generate CLAUDE.md
        from charter.generate import render_claude_md, render_system_prompt
        claude_md = render_claude_md(config)
        with open("CLAUDE.md", "w") as f:
            f.write(claude_md)
        append_to_chain("governance_generated", {
            "format": "claude-md",
            "output": "CLAUDE.md",
            "domain": config.get("domain", "general"),
            "source": "bootstrap",
        })
        if not quiet:
            print(f"  CLAUDE.md:       generated")

        # Step 4: Generate system-prompt.txt
        system_prompt = render_system_prompt(config)
        with open("system-prompt.txt", "w") as f:
            f.write(system_prompt)
        append_to_chain("governance_generated", {
            "format": "system-prompt",
            "output": "system-prompt.txt",
            "domain": config.get("domain", "general"),
            "source": "bootstrap",
        })
        if not quiet:
            print(f"  system-prompt:   generated")

        # Step 5: Generate MCP config files for Claude Code and Cursor
        mcp_files = generate_mcp_configs(target, quiet=quiet)
        append_to_chain("mcp_configs_generated", {
            "files": mcp_files,
            "source": "bootstrap",
        })
        if not quiet:
            print(f"  MCP configs:     {', '.join(mcp_files)}")

        # Step 6: Run first audit
        audit_dir = "charter_audits"
        os.makedirs(audit_dir, exist_ok=True)

        # Build a minimal args object for audit
        audit_args = argparse.Namespace(config=CONFIG_NAME, period="week")
        from charter.audit import run_audit as _run_audit

        # Capture audit output
        from io import StringIO
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            _run_audit(audit_args)
            audit_output = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        if not quiet:
            print(f"  Audit:           completed")

        elapsed = time.time() - start

        if not quiet:
            print(f"\n  Done in {elapsed:.1f}s")
            print(f"\n  Files created in {target}:")
            print(f"    charter.yaml")
            print(f"    CLAUDE.md")
            print(f"    system-prompt.txt")
            for mf in mcp_files:
                print(f"    {mf}")
            print(f"    charter_audits/")
            print(f"\n  Run 'charter status' to verify.")

    finally:
        os.chdir(original_dir)
