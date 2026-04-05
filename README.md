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
charter join <token>            # Join a governed team with one command
```

## What It Does

Charter creates a governance framework for your AI. You define the rules. The AI follows them. The system audits itself.

**Layer 0: The Zeroth Law.** The chain must always be recording. Who did it. What they did. When. This cannot be turned off.

**Layer A: Hard Constraints.** Things your AI must never do. No exceptions.

**Layer B: Gradient Decisions.** Actions that require human judgment above certain thresholds.

**Layer C: Self-Audit.** The system reviews what it did and reports honestly.

## Always-On Attribution

Every interaction is hashed and attributed: **human**, **AI**, or **collaborative**.

```bash
charter log file_introduced --actor human -m "Uploaded lab results"
charter log design_decision --actor collaborative --edge caused_by:a1b2c3
charter graph summary                   # Who did what (% breakdown)
charter graph actor human --since 2026-03-22  # All human contributions
charter graph provenance a1b2c3         # Trace who thought what → who built what
charter graph mermaid                   # Render as network diagram
charter hooks install                   # Auto-hash every git commit
```

Graph edges (`caused_by`, `revision_of`, `input_to`, `part_of`, `approved_by`) are stored inside chain entries and included in the hash — relationships are immutable once signed.

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

## Teams

Create governed teams with cryptographic identity. No sign-up page. No onboarding funnel. One command.

```bash
charter team create "My Team"                          # Create a team
charter team invite user@example.com --name "Alice"    # Generate an invite token
charter team status                                    # View your teams
charter team list <team_hash>                          # List team members
```

### Joining a Team

Got an invite token? One command to create your identity, join the team chain, and scaffold a network node:

```bash
charter join <token>
```

That's it. No account creation. No OAuth. No email verification. The token contains everything: team hash, your role, and a cryptographic signature from the person who invited you.

If you already have an identity, it reuses it. If you're already a member, it tells you. Fully idempotent.

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

55 tools exposed including governance, identity, chain operations, graph queries, compliance mapping, federation, always-on attribution, and analytics. Key analytics tools: `charter_analytics_summary`, `charter_analytics_profile`, `charter_analytics_compare`, `charter_analytics_timeline`, `charter_analytics_flow`, `charter_analytics_sequences`, `charter_analytics_anomalies`, `charter_analytics_causes`, `charter_analytics_export`.

Every action logged to an immutable hash chain. Same governance, any model.

## Analytics Engine (v3.2.0)

Turn your governance chain into an analytical data warehouse. DuckDB-backed, millisecond queries, zero cloud dependency.

```bash
pip install charter-governance[analytics]

charter analytics sync              # ETL chain → DuckDB analytical store
charter analytics status            # Store health, event counts, velocity
charter analytics summary           # Org-wide governance dashboard
```

### What You Can Do

- **Actor profiling** — Deep behavioral profiles with session patterns and temporal distribution
- **Behavioral comparison** — Rank actors by volume, diversity, escalation rate, cadence
- **Sequence mining** — Discover frequent event patterns via PrefixSpan algorithm
- **Anomaly detection** — Flag behavioral deviations from historical baselines
- **Causal discovery** — Link event patterns to outcome differences
- **Timeline analysis** — Activity density with 7d/30d/90d trend detection
- **Flow analysis** — Event predecessors, successors, and common sequences
- **Data export** — Parquet, CSV, or JSON for notebooks and external tools

### Wolfram Engine Bridge

For publication-grade statistical analysis, Charter bridges to Wolfram Language Engine:

- Causal inference (FindCausalModel)
- Time series modeling (SequencePredict)
- Graph community detection (FindGraphCommunities)
- Hypothesis testing (LocationTest)

All analytics work without Wolfram. Wolfram adds depth when available.

## Charter KB — Governed Institutional Memory (v3.3)

Charter KB adds a queryable wiki layer on top of the immutable hash chain. Turn raw audit events and project documents into structured, linked knowledge articles with full provenance. Obsidian-native frontend with Graph View and backlinks.

```bash
cd charter-kb && ./setup.sh    # One-command activation
```

- Dedicated wikis per project/domain (raw → wiki → output)
- Every index, compile, and lint is automatically logged to the chain
- Zero migration — existing v3.2 installations are unaffected
- Hospital systems and auditors get clean answers instead of raw logs

See [`charter-kb/README.md`](charter-kb/README.md) for full details.

## The Network

By installing Charter, you join a network of people who believe AI should be governed by the humans who use it. Every governed project strengthens the standard. Every audit builds accountability.

- [Discord Community](https://discord.gg/FTPczq4ngF)
- [Report Issues](https://github.com/germpharm/charter/issues)
- [Contribute](CONTRIBUTING.md)

## Philosophy

The value of AI is not in the tokens. Tokens are going to zero. The value is in the humans who provide judgment, context, and ethics. Charter is the governance layer that makes human judgment enforceable on AI systems.

Open source because we don't need more rent seekers. We need human creativity to thrive while being accountable for what it creates.

## License

Apache 2.0 — [Charter Governance Inc](https://charteragent.ai) — 2026
