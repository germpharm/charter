import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as http from "http";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHARTER_FILENAME = "charter.yaml";
const STATUS_BAR_PRIORITY = 100; // higher = further left
const STATUS_BAR_ALIGNMENT = vscode.StatusBarAlignment.Left;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GovernanceState {
  governed: boolean;
  charterPath: string | null;
  daemonActive: boolean;
}

// ---------------------------------------------------------------------------
// Charter file discovery — walks up from a directory, like git does
// ---------------------------------------------------------------------------

function findCharterYaml(startDir: string): string | null {
  let current = path.resolve(startDir);

  // Safety: stop after a reasonable depth to avoid infinite loops on
  // unusual filesystem layouts.
  const MAX_DEPTH = 64;
  let depth = 0;

  while (depth < MAX_DEPTH) {
    const candidate = path.join(current, CHARTER_FILENAME);
    if (fs.existsSync(candidate)) {
      return candidate;
    }
    const parent = path.dirname(current);
    if (parent === current) {
      // Reached filesystem root
      break;
    }
    current = parent;
    depth++;
  }

  return null;
}

/**
 * Resolve the workspace root. Prefers the first workspace folder but falls
 * back to the directory of the active text editor if no folder is open.
 */
function getWorkspaceRoot(): string | null {
  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length > 0) {
    return folders[0].uri.fsPath;
  }
  const editor = vscode.window.activeTextEditor;
  if (editor) {
    return path.dirname(editor.document.uri.fsPath);
  }
  return null;
}

// ---------------------------------------------------------------------------
// Daemon health check — plain HTTP GET to localhost
// ---------------------------------------------------------------------------

function pingDaemon(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const req = http.get(`http://127.0.0.1:${port}/`, (res) => {
      // Any response at all means the daemon is listening.
      res.resume();
      resolve(true);
    });
    req.on("error", () => resolve(false));
    req.setTimeout(2000, () => {
      req.destroy();
      resolve(false);
    });
  });
}

// ---------------------------------------------------------------------------
// Extension core
// ---------------------------------------------------------------------------

export function activate(context: vscode.ExtensionContext): void {
  const outputChannel = vscode.window.createOutputChannel("Charter Governance");
  outputChannel.appendLine("Charter Governance extension activated.");

  // ---- Status bar item ----
  const statusBarItem = vscode.window.createStatusBarItem(
    STATUS_BAR_ALIGNMENT,
    STATUS_BAR_PRIORITY
  );
  statusBarItem.command = "charterGovernance.showStatus";
  statusBarItem.name = "Charter Governance";
  context.subscriptions.push(statusBarItem);

  // ---- Daemon indicator (separate item, shown next to the main one) ----
  const daemonBarItem = vscode.window.createStatusBarItem(
    STATUS_BAR_ALIGNMENT,
    STATUS_BAR_PRIORITY - 1
  );
  daemonBarItem.name = "Charter Daemon";
  daemonBarItem.command = "charterGovernance.showStatus";
  context.subscriptions.push(daemonBarItem);

  // ---- Shared state ----
  let state: GovernanceState = {
    governed: false,
    charterPath: null,
    daemonActive: false,
  };

  // ---- Read configuration ----
  function getConfig() {
    const cfg = vscode.workspace.getConfiguration("charterGovernance");
    return {
      daemonPort: cfg.get<number>("daemonPort", 8374),
      daemonPollInterval: cfg.get<number>("daemonPollInterval", 30000),
    };
  }

  // ---- Render the status bar based on current state ----
  function render(): void {
    if (state.governed) {
      statusBarItem.text = "$(shield) GOVERNED";
      statusBarItem.tooltip = state.charterPath
        ? `Charter governance active\n${state.charterPath}`
        : "Charter governance active";
      // Green prominent background so it's visible without looking
      statusBarItem.backgroundColor = new vscode.ThemeColor(
        "statusBarItem.prominentBackground"
      );
      statusBarItem.color = undefined;
    } else {
      statusBarItem.text = "$(alert) UNGOVERNED";
      statusBarItem.tooltip = "No charter.yaml found. AI work in this workspace is ungoverned.";
      statusBarItem.backgroundColor = new vscode.ThemeColor(
        "statusBarItem.errorBackground"
      );
      statusBarItem.color = undefined;
    }
    statusBarItem.show();

    if (state.daemonActive) {
      const { daemonPort } = getConfig();
      daemonBarItem.text = "$(radio-tower) Daemon Active";
      daemonBarItem.tooltip = `Charter daemon responding on port ${daemonPort}`;
      daemonBarItem.backgroundColor = undefined;
      daemonBarItem.show();
    } else {
      daemonBarItem.hide();
    }
  }

  // ---- Check charter.yaml presence ----
  function refreshCharterFile(): void {
    const root = getWorkspaceRoot();
    if (root) {
      const found = findCharterYaml(root);
      state.governed = found !== null;
      state.charterPath = found;
    } else {
      state.governed = false;
      state.charterPath = null;
    }
    outputChannel.appendLine(
      `[${new Date().toISOString()}] Charter file check: ${state.governed ? state.charterPath : "not found"}`
    );
    render();
  }

  // ---- Check daemon ----
  async function refreshDaemon(): Promise<void> {
    const { daemonPort } = getConfig();
    const active = await pingDaemon(daemonPort);
    if (active !== state.daemonActive) {
      state.daemonActive = active;
      outputChannel.appendLine(
        `[${new Date().toISOString()}] Daemon status: ${active ? "active" : "inactive"} (port ${daemonPort})`
      );
    }
    render();
  }

  // ---- Full refresh ----
  async function fullRefresh(): Promise<void> {
    refreshCharterFile();
    await refreshDaemon();
  }

  // ---- Commands ----
  context.subscriptions.push(
    vscode.commands.registerCommand("charterGovernance.showStatus", () => {
      const lines: string[] = [];

      if (state.governed) {
        lines.push("Status: Governed");
        lines.push(`Charter file: ${state.charterPath}`);
      } else {
        lines.push("Status: Ungoverned");
        lines.push("No charter.yaml found in workspace or parent directories.");
      }

      lines.push("");
      const { daemonPort } = getConfig();
      if (state.daemonActive) {
        lines.push(`Daemon: Active on port ${daemonPort}`);
      } else {
        lines.push(`Daemon: Inactive (port ${daemonPort})`);
      }

      vscode.window.showInformationMessage(lines.join("\n"), { modal: true });
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("charterGovernance.refresh", async () => {
      await fullRefresh();
      vscode.window.showInformationMessage("Charter governance status refreshed.");
    })
  );

  // ---- File system watcher for charter.yaml ----
  // Watch across all workspace folders. The glob pattern picks up
  // charter.yaml at the workspace root or any subdirectory.
  const charterWatcher = vscode.workspace.createFileSystemWatcher(
    `**/${CHARTER_FILENAME}`
  );

  charterWatcher.onDidCreate(() => {
    outputChannel.appendLine("charter.yaml created.");
    refreshCharterFile();
  });
  charterWatcher.onDidDelete(() => {
    outputChannel.appendLine("charter.yaml deleted.");
    refreshCharterFile();
  });
  charterWatcher.onDidChange(() => {
    outputChannel.appendLine("charter.yaml changed.");
    refreshCharterFile();
  });

  context.subscriptions.push(charterWatcher);

  // Re-evaluate when workspace folders change (e.g. user opens a folder).
  context.subscriptions.push(
    vscode.workspace.onDidChangeWorkspaceFolders(() => {
      outputChannel.appendLine("Workspace folders changed. Re-evaluating.");
      fullRefresh();
    })
  );

  // Re-evaluate when configuration changes.
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("charterGovernance")) {
        outputChannel.appendLine("Configuration changed. Re-evaluating.");
        fullRefresh();
      }
    })
  );

  // ---- Daemon polling timer ----
  let daemonTimer: ReturnType<typeof setInterval> | undefined;

  function startDaemonPolling(): void {
    stopDaemonPolling();
    const { daemonPollInterval } = getConfig();
    daemonTimer = setInterval(() => {
      refreshDaemon();
    }, daemonPollInterval);
  }

  function stopDaemonPolling(): void {
    if (daemonTimer !== undefined) {
      clearInterval(daemonTimer);
      daemonTimer = undefined;
    }
  }

  context.subscriptions.push({ dispose: stopDaemonPolling });

  // ---- Initial run ----
  fullRefresh();
  startDaemonPolling();

  outputChannel.appendLine("Charter Governance extension ready.");
}

export function deactivate(): void {
  // Cleanup is handled by disposables registered on the ExtensionContext.
}
