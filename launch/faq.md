# Charter — Frequently Asked Questions

## Getting Started

**What is Charter?**
Charter is an open-source governance layer for AI agents. It enforces rules on any AI tool working in your project — Claude, GPT, Copilot, Gemini, or any MCP-compatible AI. Three layers: hard constraints (things AI can never do), gradient decisions (things that need human approval), and self-audit (AI reports what it did honestly).

**How do I install it?**
Two options:
1. **VS Code Extension** (easiest): Search "Charter" in VS Code Extensions. Open any folder. Done.
2. **CLI**: `pip install charter-governance` then `charter bootstrap` in your project folder.

**What does it do when I install the VS Code extension?**
When you open a folder, the extension automatically creates three governance files: `charter.yaml` (your rules), `CLAUDE.md` (governance instructions for Claude), and `system-prompt.txt` (governance instructions for any AI). Your status bar shows "GOVERNED."

**Does it slow down my AI tools?**
No. Charter creates governance files. Your AI tools read those files as instructions. There is no middleware, no proxy, no latency added.

**Does it work offline?**
Yes. Charter is local-first. Everything runs on your machine. No internet required after installation.

## Privacy & Security

**Does Charter send my data anywhere?**
No. Charter is entirely local. Your governance rules, audit trail, identity, and project data never leave your machine. There is no telemetry, no analytics, no phone-home.

**What data does the VS Code extension access?**
The extension only checks if `charter.yaml` exists in your workspace. It reads no code, no files, no project content. It pings localhost to check if the optional daemon is running. That's it.

**Is my identity anonymous?**
Yes, by default. Charter creates a pseudonymous identity (a SHA-256 hash). Your node ID is random — nobody can trace it back to you. You can optionally link your real identity later if you choose to.

**Can two people get the same identity hash?**
No. The hash is generated from 32 cryptographically random bytes plus a nanosecond timestamp, then run through SHA-256. The probability of a collision is approximately 1 in 10^77 — effectively zero. For reference, there are about 10^80 atoms in the observable universe.

## How It Works

**What's in charter.yaml?**
Your governance rules. Hard constraints (things AI must never do), gradient decisions (things that need human approval above thresholds), self-audit schedule, and kill triggers (conditions that immediately stop AI work).

**What are kill triggers?**
Conditions that automatically halt all AI activity. Examples: ethics compliance declining across sessions, audit process being bypassed, system flagging internal conflict between instructions and ethics.

**What domains are supported?**
Four built-in templates: General, Healthcare (HIPAA), Finance (SOX), Education (FERPA). Charter auto-detects your domain based on project contents.

**Can I customize the rules?**
Yes. Edit `charter.yaml` directly. Add constraints, change thresholds, modify audit frequency. The extension detects changes in real time.

**What AI tools does Charter work with?**
Any AI tool that reads instruction files. Specifically:
- **Claude** (Claude Code, Claude Desktop) — reads `CLAUDE.md`
- **GPT, Copilot, Gemini, any AI** — reads `system-prompt.txt`
- **MCP-compatible tools** — Charter runs as an MCP server

## The Network

**What is "The Network"?**
Everyone who installs Charter is part of a community that believes AI should be governed by humans. The network is not a technical system that connects your machines — it's a community standard. Every governed project strengthens the norm.

**Is Charter free?**
Yes, forever. The CLI, the VS Code extension, and the governance layer are free and open source (Apache 2.0). There is no freemium tier, no enterprise gate, no feature lock.

**How do I contribute?**
See [CONTRIBUTING.md](https://github.com/germpharm/charter/blob/main/CONTRIBUTING.md) on GitHub, or join the Discord community.

## Troubleshooting

**The status bar shows UNGOVERNED**
Make sure you have a folder open in VS Code (not a blank window). The extension only activates when a workspace folder is present. If you just opened the folder, wait 2-3 seconds — Charter auto-creates governance files.

**The Charter CLI command is not found**
Make sure you installed with `pip install charter-governance` and that your Python bin directory is in your PATH. On macOS: `python3 -m pip install charter-governance`.

**The daemon indicator doesn't show**
The daemon is optional. It only appears if you've started `charter daemon` separately. The extension works without it.

**I want to start fresh**
Delete `charter.yaml`, `CLAUDE.md`, and `system-prompt.txt` from your project folder. Reopen the folder. The extension will auto-bootstrap new governance files.
