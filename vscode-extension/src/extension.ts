import * as vscode from "vscode";
import * as fs from "fs";
import * as path from "path";
import * as http from "http";
import { bootstrap, bootstrapWithDomain } from "./bootstrap";
import { ALL_DOMAINS, Domain } from "./types";

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
// Bootstrap with progress notification
// ---------------------------------------------------------------------------

/**
 * Run bootstrap with a VS Code progress notification.
 * Tries the Python CLI first, falls back to TypeScript native.
 */
async function runBootstrapWithProgress(
  workspaceRoot: string,
  outputChannel: vscode.OutputChannel,
  domain?: Domain
): Promise<boolean> {
  return vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "Charter",
      cancellable: false,
    },
    async (progress) => {
      progress.report({ message: "Initializing governance..." });
      outputChannel.appendLine(
        `[${new Date().toISOString()}] Bootstrap starting: root=${workspaceRoot}, domain=${domain ?? "auto-detect"}`
      );

      const result = domain
        ? await bootstrapWithDomain(workspaceRoot, domain)
        : await bootstrap(workspaceRoot);

      outputChannel.appendLine(
        `[${new Date().toISOString()}] Bootstrap result: success=${result.success}, method=${result.method}, domain=${result.domain}, files=[${result.filesCreated.join(", ")}]`
      );

      if (result.error) {
        outputChannel.appendLine(
          `[${new Date().toISOString()}] Bootstrap note: ${result.error}`
        );
      }

      if (result.success && result.filesCreated.length > 0) {
        progress.report({ message: `Governed (${result.domain}) via ${result.method}` });

        // Brief pause so the user sees the success message
        await new Promise((resolve) => setTimeout(resolve, 1500));
        return true;
      } else if (result.success && result.filesCreated.length === 0) {
        // Already governed or error with existing file
        if (result.error) {
          progress.report({ message: result.error });
          await new Promise((resolve) => setTimeout(resolve, 2000));
        }
        return true;
      } else {
        progress.report({ message: "Bootstrap failed. Check output channel." });
        await new Promise((resolve) => setTimeout(resolve, 2000));
        return false;
      }
    }
  );
}

// ---------------------------------------------------------------------------
// Extension core
// ---------------------------------------------------------------------------

export function activate(context: vscode.ExtensionContext): void {
  const outputChannel = vscode.window.createOutputChannel("Charter Governance");
  outputChannel.appendLine("Charter Governance extension activated (v2.0.0).");

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
      outputChannel.appendLine(
        `[${new Date().toISOString()}] Ungoverned workspace detected. Auto-bootstrapping...`
      );

      const ok = await runBootstrapWithProgress(root, outputChannel);

      if (ok) {
        // Re-check — charter.yaml should now exist
        const found = findCharterYaml(root);
        state.governed = found !== null;
        state.charterPath = found;
        outputChannel.appendLine(
          `[${new Date().toISOString()}] Post-bootstrap check: governed=${state.governed}`
        );
        render();

        if (state.governed) {
          const action = await vscode.window.showInformationMessage(
            "Charter: Governance initialized for this workspace.",
            "View charter.yaml",
            "View CLAUDE.md"
          );
          if (action === "View charter.yaml" && state.charterPath) {
            const doc = await vscode.workspace.openTextDocument(state.charterPath);
            await vscode.window.showTextDocument(doc);
          } else if (action === "View CLAUDE.md") {
            const claudePath = path.join(root, "CLAUDE.md");
            if (fs.existsSync(claudePath)) {
              const doc = await vscode.workspace.openTextDocument(claudePath);
              await vscode.window.showTextDocument(doc);
            }
          }
        }
      } else {
        const choice = await vscode.window.showWarningMessage(
          "Charter: Could not auto-initialize governance.",
          "Try Again",
          "Select Domain",
          "Open Terminal"
        );
        if (choice === "Try Again") {
          bootstrapAttempted = false;
          await refreshCharterFile();
        } else if (choice === "Select Domain") {
          await vscode.commands.executeCommand("charterGovernance.selectDomain");
        } else if (choice === "Open Terminal") {
          const term = vscode.window.createTerminal("Charter");
          term.show();
          term.sendText(`charter bootstrap "${root}"`);
        }
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

  // Show status (existing)
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

  // Refresh (existing)
  context.subscriptions.push(
    vscode.commands.registerCommand("charterGovernance.refresh", async () => {
      await fullRefresh();
      vscode.window.showInformationMessage("Charter governance status refreshed.");
    })
  );

  // Bootstrap (new) — manually trigger bootstrap with auto-detect
  context.subscriptions.push(
    vscode.commands.registerCommand("charterGovernance.bootstrap", async () => {
      const root = getWorkspaceRoot();
      if (!root) {
        vscode.window.showWarningMessage(
          "Charter: No workspace folder open. Open a folder first."
        );
        return;
      }

      const charterPath = path.join(root, CHARTER_FILENAME);
      if (fs.existsSync(charterPath)) {
        const action = await vscode.window.showInformationMessage(
          "Charter: This workspace is already governed.",
          "View charter.yaml"
        );
        if (action === "View charter.yaml") {
          const doc = await vscode.workspace.openTextDocument(charterPath);
          await vscode.window.showTextDocument(doc);
        }
        return;
      }

      const ok = await runBootstrapWithProgress(root, outputChannel);
      if (ok) {
        const found = findCharterYaml(root);
        state.governed = found !== null;
        state.charterPath = found;
        render();

        if (state.governed) {
          const action = await vscode.window.showInformationMessage(
            "Charter: Governance initialized.",
            "View charter.yaml",
            "View CLAUDE.md"
          );
          if (action === "View charter.yaml" && state.charterPath) {
            const doc = await vscode.workspace.openTextDocument(state.charterPath);
            await vscode.window.showTextDocument(doc);
          } else if (action === "View CLAUDE.md") {
            const claudePath = path.join(root, "CLAUDE.md");
            if (fs.existsSync(claudePath)) {
              const doc = await vscode.workspace.openTextDocument(claudePath);
              await vscode.window.showTextDocument(doc);
            }
          }
        }
      } else {
        vscode.window.showErrorMessage(
          "Charter: Bootstrap failed. Check the Charter Governance output channel for details."
        );
      }
    })
  );

  // Select Domain (new) — pick a domain then bootstrap
  context.subscriptions.push(
    vscode.commands.registerCommand("charterGovernance.selectDomain", async () => {
      const root = getWorkspaceRoot();
      if (!root) {
        vscode.window.showWarningMessage(
          "Charter: No workspace folder open. Open a folder first."
        );
        return;
      }

      // Show quick pick with domain descriptions
      const domainItems: vscode.QuickPickItem[] = [
        {
          label: "$(heart) Healthcare",
          description: "HIPAA, clinical safety, medication checks",
          detail: "healthcare",
        },
        {
          label: "$(graph) Finance",
          description: "SOX compliance, trade authorization, client data protection",
          detail: "finance",
        },
        {
          label: "$(book) Education",
          description: "FERPA, student records, assessment oversight",
          detail: "education",
        },
        {
          label: "$(globe) General",
          description: "Standard governance for any project",
          detail: "general",
        },
        {
          label: "$(person) Personal",
          description: "Plain English governance for individual use",
          detail: "personal",
        },
      ];

      const selected = await vscode.window.showQuickPick(domainItems, {
        placeHolder: "Select a governance domain for this workspace",
        title: "Charter: Select Domain",
      });

      if (!selected || !selected.detail) {
        return; // User cancelled
      }

      const domain = selected.detail as Domain;

      const charterPath = path.join(root, CHARTER_FILENAME);
      if (fs.existsSync(charterPath)) {
        const overwrite = await vscode.window.showWarningMessage(
          `Charter: charter.yaml already exists. Delete it and re-bootstrap as "${domain}"?`,
          "Yes, replace",
          "Cancel"
        );
        if (overwrite !== "Yes, replace") {
          return;
        }
        // Remove existing files so bootstrap can create fresh ones
        try {
          fs.unlinkSync(charterPath);
          const claudePath = path.join(root, "CLAUDE.md");
          if (fs.existsSync(claudePath)) {
            fs.unlinkSync(claudePath);
          }
          const promptPath = path.join(root, "system-prompt.txt");
          if (fs.existsSync(promptPath)) {
            fs.unlinkSync(promptPath);
          }
        } catch (err) {
          outputChannel.appendLine(
            `[${new Date().toISOString()}] Error removing old files: ${err}`
          );
        }
      }

      const ok = await runBootstrapWithProgress(root, outputChannel, domain);
      if (ok) {
        const found = findCharterYaml(root);
        state.governed = found !== null;
        state.charterPath = found;
        render();

        if (state.governed) {
          const action = await vscode.window.showInformationMessage(
            `Charter: Governed as "${domain}".`,
            "View charter.yaml",
            "View CLAUDE.md"
          );
          if (action === "View charter.yaml" && state.charterPath) {
            const doc = await vscode.workspace.openTextDocument(state.charterPath);
            await vscode.window.showTextDocument(doc);
          } else if (action === "View CLAUDE.md") {
            const claudePath = path.join(root, "CLAUDE.md");
            if (fs.existsSync(claudePath)) {
              const doc = await vscode.workspace.openTextDocument(claudePath);
              await vscode.window.showTextDocument(doc);
            }
          }
        }
      } else {
        vscode.window.showErrorMessage(
          "Charter: Bootstrap failed. Check the Charter Governance output channel for details."
        );
      }
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
