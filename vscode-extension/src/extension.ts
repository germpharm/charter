import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as http from "http";
import { exec } from "child_process";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHARTER_FILENAME = "charter.yaml";
const STATUS_BAR_PRIORITY = 100; // higher = further left
const STATUS_BAR_ALIGNMENT = vscode.StatusBarAlignment.Left;

// Common paths where pip installs binaries — VS Code extension host
// does NOT inherit the user's shell PATH.
const EXTRA_PATH_DIRS = [
  "/Library/Frameworks/Python.framework/Versions/Current/bin",
  "/Library/Frameworks/Python.framework/Versions/3.13/bin",
  "/Library/Frameworks/Python.framework/Versions/3.12/bin",
  "/Library/Frameworks/Python.framework/Versions/3.11/bin",
  "/opt/homebrew/bin",
  "/usr/local/bin",
  "/usr/bin",
  `${process.env.HOME}/.local/bin`,
  `${process.env.HOME}/Library/Python/3.13/bin`,
  `${process.env.HOME}/Library/Python/3.12/bin`,
  `${process.env.HOME}/Library/Python/3.11/bin`,
];

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

/**
 * Build a PATH that includes common Python/pip install locations.
 * The VS Code extension host often has a minimal PATH that excludes
 * where `charter` is installed.
 */
function getExtendedPath(): string {
  const current = process.env.PATH || "";
  const extra = EXTRA_PATH_DIRS.filter((d) => !current.includes(d));
  return extra.length > 0 ? `${current}:${extra.join(":")}` : current;
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
// Auto-bootstrap — run `charter bootstrap --quiet` when ungoverned
// ---------------------------------------------------------------------------

function runBootstrap(workspaceRoot: string, outputChannel: vscode.OutputChannel): Promise<boolean> {
  return new Promise((resolve) => {
    const cmd = `charter bootstrap "${workspaceRoot}" --quiet`;
    outputChannel.appendLine(`[${new Date().toISOString()}] Auto-bootstrapping: ${cmd}`);

    const extendedPath = getExtendedPath();
    outputChannel.appendLine(`[${new Date().toISOString()}] PATH: ${extendedPath}`);

    exec(cmd, {
      timeout: 15000,
      env: { ...process.env, PATH: extendedPath },
    }, (err, stdout, stderr) => {
      if (err) {
        outputChannel.appendLine(`[${new Date().toISOString()}] Bootstrap failed: ${err.message}`);
        if (stderr) { outputChannel.appendLine(stderr); }
        resolve(false);
      } else {
        outputChannel.appendLine(`[${new Date().toISOString()}] Bootstrap succeeded.`);
        if (stdout.trim()) { outputChannel.appendLine(stdout); }
        resolve(true);
      }
    });
  });
}

// ---------------------------------------------------------------------------
// Extension core
// ---------------------------------------------------------------------------

export function activate(context: vscode.ExtensionContext): void {
  const outputChannel = vscode.window.createOutputChannel("Charter Governance");
  outputChannel.appendLine("Charter Governance extension activated.");

  // Log workspace info immediately for debugging
  const folders = vscode.workspace.workspaceFolders;
  if (folders) {
    outputChannel.appendLine(`Workspace folders: ${folders.map((f) => f.uri.fsPath).join(", ")}`);
  } else {
    outputChannel.appendLine("No workspace folders detected at activation.");
  }

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
      autoBootstrap: cfg.get<boolean>("autoBootstrap", true),
    };
  }

  // ---- Render the status bar based on current state ----
  function render(): void {
    // No folder open — hide the status bar entirely. Nothing to govern.
    if (!getWorkspaceRoot()) {
      statusBarItem.hide();
      daemonBarItem.hide();
      return;
    }

    if (state.governed) {
      statusBarItem.text = "$(shield) GOVERNED";
      statusBarItem.tooltip = state.charterPath
        ? `Charter governance active\n${state.charterPath}`
        : "Charter governance active";
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

  // ---- Track whether we've already attempted bootstrap this session ----
  let bootstrapAttempted = false;

  // ---- Check charter.yaml presence (auto-bootstrap if missing) ----
  async function refreshCharterFile(): Promise<void> {
    const root = getWorkspaceRoot();
    outputChannel.appendLine(
      `[${new Date().toISOString()}] refreshCharterFile: root=${root ?? "null"}`
    );

    if (root) {
      const found = findCharterYaml(root);
      state.governed = found !== null;
      state.charterPath = found;
      outputChannel.appendLine(
        `[${new Date().toISOString()}] findCharterYaml result: ${found ?? "null"}`
      );
    } else {
      state.governed = false;
      state.charterPath = null;
    }

    render();

    // Auto-bootstrap: if ungoverned, enabled, and we haven't tried yet this session
    const { autoBootstrap } = getConfig();
    if (!state.governed && !bootstrapAttempted && autoBootstrap && root) {
      bootstrapAttempted = true;
      outputChannel.appendLine(`[${new Date().toISOString()}] Ungoverned workspace detected. Auto-bootstrapping...`);
      const ok = await runBootstrap(root, outputChannel);
      if (ok) {
        // Re-check — charter.yaml should now exist
        const found = findCharterYaml(root);
        state.governed = found !== null;
        state.charterPath = found;
        outputChannel.appendLine(
          `[${new Date().toISOString()}] Post-bootstrap check: governed=${state.governed}`
        );
        render();
        vscode.window.showInformationMessage("Charter: Governance auto-initialized for this workspace.");
      } else {
        vscode.window.showWarningMessage(
          "Charter: Could not auto-initialize governance. Run `charter bootstrap` manually.",
          "Open Terminal"
        ).then((choice) => {
          if (choice === "Open Terminal") {
            const term = vscode.window.createTerminal("Charter");
            term.show();
            term.sendText(`charter bootstrap "${root}"`);
          }
        });
      }
    }
  }

  // ---- Check daemon (does NOT call render — only updates daemon state) ----
  async function refreshDaemon(): Promise<void> {
    const { daemonPort } = getConfig();
    const active = await pingDaemon(daemonPort);
    if (active !== state.daemonActive) {
      state.daemonActive = active;
      outputChannel.appendLine(
        `[${new Date().toISOString()}] Daemon status: ${active ? "active" : "inactive"} (port ${daemonPort})`
      );
    }
  }

  // ---- Full refresh ----
  async function fullRefresh(): Promise<void> {
    await refreshCharterFile();
    await refreshDaemon();
    render(); // Single render after both checks complete
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

  charterWatcher.onDidCreate(async () => {
    outputChannel.appendLine("charter.yaml created.");
    await refreshCharterFile();
  });
  charterWatcher.onDidDelete(async () => {
    outputChannel.appendLine("charter.yaml deleted.");
    await refreshCharterFile();
  });
  charterWatcher.onDidChange(async () => {
    outputChannel.appendLine("charter.yaml changed.");
    await refreshCharterFile();
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
      refreshDaemon().then(() => render());
    }, daemonPollInterval);
  }

  function stopDaemonPolling(): void {
    if (daemonTimer !== undefined) {
      clearInterval(daemonTimer);
      daemonTimer = undefined;
    }
  }

  context.subscriptions.push({ dispose: stopDaemonPolling });

  // ---- Initial run (with retry if workspace not ready) ----
  fullRefresh().then(() => {
    outputChannel.appendLine("Charter Governance extension ready.");

    // VS Code sometimes activates extensions before workspace folders
    // are available (restored windows, slow workspace loading).
    // If we got no workspace root on the first try, retry a few times.
    if (!getWorkspaceRoot()) {
      const retryDelays = [1000, 3000, 6000]; // 1s, 3s, 6s
      for (const delay of retryDelays) {
        setTimeout(async () => {
          const root = getWorkspaceRoot();
          if (root && !state.governed) {
            outputChannel.appendLine(
              `[${new Date().toISOString()}] Retry: workspace root now available: ${root}`
            );
            await fullRefresh();
          }
        }, delay);
      }
    }
  });
  startDaemonPolling();
}

export function deactivate(): void {
  // Cleanup is handled by disposables registered on the ExtensionContext.
}
