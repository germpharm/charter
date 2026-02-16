# Charter

AI governance layer. Local-first. Open source.

Three layers: hard constraints, gradient decisions, self-audit.

## Install

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

## Network

Connect to the network. Register your expertise. Record contributions.

```bash
charter connect init                          # Create your node
charter connect source "My Data" shopify      # Register data sources
charter connect contribute "Title" governance # Record contributions
charter connect formation "Name"              # Recognize who shaped you
```

## Philosophy

The value of AI is not in the tokens. Tokens are going to zero. The value is in the humans who provide judgment, context, and ethics. Charter is the governance layer that makes human judgment enforceable on AI systems.

Open source because we don't need more rent seekers. We need human creativity to thrive while being accountable for what it creates.

## License

Apache 2.0
