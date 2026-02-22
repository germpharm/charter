# Charter Onboarding Friction Report

**Date:** 2026-02-21
**Context:** Initializing Charter on a new project folder (`AI Comedy`)
**Tester:** Project creator, via Claude Code

## What Happened

Charter was already installed on this machine (`pip install charter-governance`), yet
bootstrapping governance on a new folder required **8 discrete steps** across an
interactive back-and-forth that took roughly **3-4 minutes**:

| # | Step | Time | Problem |
|---|------|------|---------|
| 1 | "Find the Charter file" — agent searched Desktop, Documents, Downloads, home | ~30s | Charter is a CLI tool, not a file. No discoverability. |
| 2 | `charter init` — failed with EOFError | ~5s | Interactive prompts don't work in non-TTY shells (CI, Claude Code, scripts). |
| 3 | Ask user which domain to use | ~15s | Unnecessary round-trip. Could default to `general`. |
| 4 | `charter init --domain general --non-interactive` | ~2s | Works, but only creates charter.yaml. |
| 5 | `charter generate` | ~1s | Separate step to create CLAUDE.md. |
| 6 | `charter generate --format system-prompt -o system-prompt.txt` | ~1s | Another separate step. |
| 7 | `charter audit` | ~1s | Another separate step. |
| 8 | `charter status` | ~1s | Another separate step. |

**Total wall-clock time: ~3-4 minutes**
**Acceptable target: <5 seconds, one command**

## Root Causes

1. **`charter init` does not generate output files.** It only writes `charter.yaml`.
   The user must separately call `generate`, `audit`, etc.

2. **No single "bootstrap everything" command.** A new project needs: config + CLAUDE.md
   + system prompt + first audit. That's 4 commands minimum.

3. **Interactive mode is the default.** Fails in non-TTY environments. The
   `--non-interactive` flag exists but isn't the default when stdin is not a terminal.

4. **No auto-detection of domain.** Charter could infer domain from project contents
   (package.json, requirements.txt, HIPAA references, etc.) instead of always asking.

## Required Fix: `charter bootstrap`

A single command that does everything:

```bash
charter bootstrap [path]
```

Behavior:
- Detects if stdin is a TTY; if not, uses non-interactive defaults automatically
- Auto-detects domain from project contents (falls back to `general`)
- Creates `charter.yaml`
- Generates `CLAUDE.md`
- Generates `system-prompt.txt`
- Runs first audit
- Prints status summary
- Total time target: <3 seconds

### Alternative: Enhance `charter init --full`

Add a `--full` flag to `charter init` that runs all post-init steps:

```bash
charter init --domain general --non-interactive --full
```

This is simpler to implement but less discoverable than a dedicated `bootstrap` command.

## Resolution (2026-02-22)

All three fixes implemented and tested:

### 1. `charter bootstrap [path]` — NEW COMMAND
- Auto-detects domain from project contents
- Creates charter.yaml + CLAUDE.md + system-prompt.txt + first audit
- `--quiet` flag for automated/silent use
- `--force` flag to overwrite existing config
- Idempotent: keeps existing config if present, regenerates outputs
- **Tested: completes in <1 second**

### 2. `charter init --full` — ENHANCED
- Runs full bootstrap after init (generate + audit)
- Combines with existing `--domain` and `--non-interactive` flags

### 3. `charter init` non-TTY auto-detection — FIXED
- Detects `sys.stdin.isatty()` and auto-switches to `--non-interactive`
- No more EOFError in CI, Claude Code, scripts, etc.

### 4. VS Code extension auto-bootstrap — NEW
- On workspace open: detects ungoverned folder, runs `charter bootstrap --quiet`
- One attempt per session (no retry loops)
- Configurable via `charterGovernance.autoBootstrap` setting (default: true)
- Shows info message on success, warning with "Open Terminal" button on failure

### 5. Claude Code global instruction — NEW
- `~/.claude/CLAUDE.md` instructs Claude to auto-run `charter bootstrap --quiet`
  at session start if no charter.yaml exists
- Silent, no user interaction needed

### Before vs After

| Scenario | Before | After |
|----------|--------|-------|
| Open VS Code on new folder | 8 steps, ~3-4 min | 0 steps, automatic |
| Claude Code session on new folder | 8 steps, ~3-4 min | 0 steps, automatic |
| Manual CLI setup | 4+ commands | `charter bootstrap` (1 command, <1s) |
