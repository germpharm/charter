# Charter

[![VS Code Extension](https://img.shields.io/badge/VS%20Code-Install%20Charter-007ACC?logo=visual-studio-code&logoColor=white&style=for-the-badge)](https://marketplace.visualstudio.com/items?itemName=germpharm.charter-governance)
[![PyPI](https://img.shields.io/pypi/v/charter-governance?style=for-the-badge&logo=python&logoColor=white&label=PyPI)](https://pypi.org/project/charter-governance/)
[![License](https://img.shields.io/badge/License-Apache%202.0-green?style=for-the-badge)](LICENSE)
[![Discord](https://img.shields.io/badge/Discord-Join%20Community-5865F2?logo=discord&logoColor=white&style=for-the-badge)](https://discord.gg/FTPczq4ngF)

**AI governance layer. Local-first. Open source.**

Three layers: hard constraints, gradient decisions, self-audit. Works with Claude, GPT, Copilot, Gemini, and any MCP-compatible AI.

> Every AI agent writing code in your project right now has zero rules. No audit trail. No compliance. No kill switch. Charter fixes this in 3 seconds.

## Install

### VS Code Extension (recommended — zero config)

Search **"Charter"** in VS Code Extensions, or [click here to install](https://marketplace.visualstudio.com/items?itemName=germpharm.charter-governance).

Open a folder. Governance is automatic.

### CLI

```
pip install charter-governance
```

## Quick Start

```bash
charter init                    # Create governance config + identity
charter generate                # Generate a CLAUDE.md with your rules
charter generate --format system-prompt  # Or a system prompt for any AI
charter audit                   # Run a governance audit
charter status                  # See everything at a glance
```

## What It Does

Charter creates a governance framework for your AI. You define the rules. The AI follows them. The system audits itself.

**Layer A: Hard Constraints.** Things your AI must never do. No exceptions.

**Layer B: Gradient Decisions.** Actions that require human judgment above certain thresholds.

**Layer C: Self-Audit.** The system reviews what it did and reports honestly.

## Domain Templates

Charter ships with governance presets for:
- Healthcare (HIPAA-aware, clinical safety)
- Finance (compliance-focused, transaction controls)
- Education (FERPA-aware, student protection)
- General (universal governance baseline)

## Identity

Charter creates a pseudonymous identity backed by a hash chain. Every action is signed and recorded. When you're ready, link your real identity and all prior work transfers to you. The chain is the proof.

```bash
charter identity              # View your identity
charter identity verify       # Link real identity (authorship transfer)
charter identity proof        # Generate a signed transfer proof
```

## Contexts

Separate work and personal knowledge with governed boundaries.

```bash
charter context create personal
charter context create work --type work --org "Your Org" --email you@org.com
charter context bridge personal --target work --policy read-only
charter context approve <bridge_id>     # Both parties must consent
charter context revoke <bridge_id>      # Either party can revoke
```

Knowledge does not flow between contexts by default. Bridging requires explicit consent from both sides.

## Identity Verification

Upgrade your pseudonymous identity with government ID verification via Persona or ID.me.

```bash
charter verify configure persona    # Set up Persona API credentials
charter verify start                # Open browser for ID verification
charter verify check <inquiry_id>   # Check verification status
charter verify status               # See configured providers
```

Free tier: 500 verifications per month via Persona. No credit card required.

## Network

Connect to the network. Register your expertise. Record contributions.

```bash
charter connect init                          # Create your node
charter connect source "My Data" shopify      # Register data sources
charter connect contribute "Title" governance # Record contributions
charter connect formation "Name"              # Recognize who shaped you
```

## MCP Server

Charter runs as an MCP (Model Context Protocol) server. Any AI model that supports MCP gets Charter governance.

```bash
pip install charter-governance[mcp]

# Local (Claude Code via .mcp.json)
charter mcp-serve --transport stdio

# Remote (Mac Mini, Grok via remote MCP)
charter mcp-serve --transport sse --port 8375
```

10 tools exposed: `charter_status`, `charter_stamp`, `charter_verify_stamp`, `charter_append_chain`, `charter_read_chain`, `charter_check_integrity`, `charter_get_config`, `charter_identity`, `charter_audit`, `charter_local_inference`.

Every action logged to an immutable hash chain. Same governance, any model.

## The Network

By installing Charter, you join a network of people who believe AI should be governed by the humans who use it. Every governed project strengthens the standard. Every audit builds accountability.

- [Discord Community](https://discord.gg/FTPczq4ngF)
- [Report Issues](https://github.com/germpharm/charter/issues)
- [Contribute](CONTRIBUTING.md)

## Philosophy

The value of AI is not in the tokens. Tokens are going to zero. The value is in the humans who provide judgment, context, and ethics. Charter is the governance layer that makes human judgment enforceable on AI systems.

Open source because we don't need more rent seekers. We need human creativity to thrive while being accountable for what it creates.

## License

Apache 2.0 — [GermPharm LLC](https://germpharm.org) — 2026
