# Charter — AI Governance & Safety

**Every AI agent in your project. Governed. Automatically.**

Charter is the open-source governance layer for AI coding assistants. It works with Claude, GPT, Copilot, Gemini, and any MCP-compatible AI. Install the extension, open a folder, and your AI agents follow rules you define.

No configuration. No setup wizard. Open a folder — governance is there.

## Why Charter?

AI agents are writing code, accessing data, and making decisions in your projects right now. Without governance:

- There are no rules they can't break
- There is no audit trail of what they did
- There is no way to enforce compliance (HIPAA, SOX, FERPA)
- There is no kill switch when something goes wrong

Charter fixes all of this in one extension.

## Three Layers of Governance

| Layer | What It Does |
| --- | --- |
| **Layer A: Hard Constraints** | Things your AI must never do. No exceptions. You define the rules, the system enforces them. |
| **Layer B: Gradient Decisions** | Actions that require human approval above thresholds — financial transactions, external communications, sensitive data access. |
| **Layer C: Self-Audit** | The AI reviews what it did and reports honestly. Accountability, not perfection. |

## How It Works

1. **Install this extension**
2. **Open any folder** — Charter automatically creates governance files (`charter.yaml`, `CLAUDE.md`, `system-prompt.txt`)
3. **Status bar shows GOVERNED** — your AI agents now follow the rules

That's it. Three seconds. Zero configuration.

## Features

- **Auto-bootstrap** — Opens an ungoverned workspace? Charter creates governance files automatically
- **Status bar indicator** — Green shield = governed. Red alert = ungoverned
- **Domain templates** — Healthcare (HIPAA), Finance (SOX), Education (FERPA), General
- **Works with every AI** — Claude, GPT, Copilot, Gemini, and any MCP-compatible agent
- **Pseudonymous identity** — SHA-256 hash chain. Every action signed and verifiable
- **Context isolation** — Separate work and personal knowledge. No cross-context leaks
- **Kill triggers** — Ethics declining? Audit bypassed? The system shuts itself down
- **Daemon monitoring** — Real-time governance enforcement when the Charter daemon is active
- **File watching** — Detects changes to `charter.yaml` in real time

## Requirements

Install the Charter CLI:

```bash
pip install charter-governance
```

Requires Python 3.9+.

## Commands

| Command | Description |
| --- | --- |
| `Charter: Show Governance Status` | Shows current governance state in a modal |
| `Charter: Refresh Governance Status` | Force re-check governance files |

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `charterGovernance.autoBootstrap` | `true` | Auto-create governance files when opening ungoverned workspaces |
| `charterGovernance.daemonPort` | `8374` | Port for the Charter daemon |
| `charterGovernance.daemonPollInterval` | `30000` | Daemon health check interval in ms |

## The Network

By installing Charter, you join a network of people who believe AI should be governed by the humans who use it. Every governed project strengthens the standard. Every audit builds accountability.

Charter is open source (Apache 2.0) because governance should not be a product you rent. It should be infrastructure you own.

## Links

- [Discord Community](https://discord.gg/FTPczq4ngF)
- [Website](https://germpharm.org)
- [GitHub](https://github.com/germpharm/charter)
- [PyPI](https://pypi.org/project/charter-governance/)
- [Report Issues](https://github.com/germpharm/charter/issues)

---

**Apache 2.0** | **GermPharm LLC** | **2026**
