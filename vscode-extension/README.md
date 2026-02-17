# Charter Governance

VS Code extension that shows Charter governance status in the status bar.

## What it does

- Detects `charter.yaml` in the workspace root or any parent directory (walks up, like git).
- Shows **"Charter: Governed"** (shield icon) when a charter file is found.
- Shows **"Charter: Ungoverned"** (warning icon, yellow background) when no charter file exists.
- Monitors the Charter daemon on port 8374 and shows a **"Daemon Active"** indicator when it responds.
- Auto-refreshes when `charter.yaml` is created, deleted, or changed.
- Click the status bar item for a summary modal.

## Commands

- `Charter: Show Governance Status` -- modal with current state.
- `Charter: Refresh Governance Status` -- force re-check.

## Settings

| Setting | Default | Description |
|---|---|---|
| `charterGovernance.daemonPort` | `8374` | Port for the Charter daemon. |
| `charterGovernance.daemonPollInterval` | `30000` | Daemon poll interval in ms. |

## Install from source

```bash
cd charter/vscode-extension
npm install
npm run compile
```

Then in VS Code: `Developer: Install Extension from Location...` and select this directory.

Or package with `vsce`:

```bash
npx @vscode/vsce package
code --install-extension charter-governance-1.0.0.vsix
```
