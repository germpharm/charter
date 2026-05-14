import * as vscode from "vscode";
import * as cp from "child_process";
import * as path from "path";

// ---------------------------------------------------------------------------
// Charter CLI wrapper — exec with graceful fallback
// ---------------------------------------------------------------------------

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

function runCharterCli(
  args: string,
  outputChannel: vscode.OutputChannel,
  cwd?: string
): Promise<{ stdout: string; stderr: string; code: number }> {
  return new Promise((resolve) => {
    const workDir = cwd || getWorkspaceRoot() || process.env.HOME || "/tmp";
    const cmd = `charter ${args}`;
    outputChannel.appendLine(`[${new Date().toISOString()}] Running: ${cmd}`);

    cp.exec(cmd, { cwd: workDir, timeout: 30000 }, (error, stdout, stderr) => {
      const code = error ? (error as any).code ?? 1 : 0;
      if (stdout) {
        outputChannel.appendLine(stdout);
      }
      if (stderr) {
        outputChannel.appendLine(stderr);
      }
      resolve({ stdout: stdout || "", stderr: stderr || "", code });
    });
  });
}

function requireCharterCli(outputChannel: vscode.OutputChannel): boolean {
  try {
    cp.execSync("which charter", { timeout: 5000 });
    return true;
  } catch {
    outputChannel.appendLine("Charter CLI not found in PATH.");
    vscode.window
      .showErrorMessage(
        "Charter CLI not found. Install it with: pip install charter-governance",
        "Copy Install Command"
      )
      .then((action) => {
        if (action === "Copy Install Command") {
          vscode.env.clipboard.writeText("pip install charter-governance");
        }
      });
    return false;
  }
}

// ---------------------------------------------------------------------------
// Webview panel helper
// ---------------------------------------------------------------------------

function showResultPanel(
  title: string,
  content: string,
  context: vscode.ExtensionContext
): void {
  const panel = vscode.window.createWebviewPanel(
    "charterResult",
    title,
    vscode.ViewColumn.One,
    { enableScripts: false }
  );
  panel.webview.html = `<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
body { font-family: var(--vscode-font-family); color: var(--vscode-foreground); background: var(--vscode-editor-background); padding: 16px; line-height: 1.6; }
pre { background: var(--vscode-textBlockQuote-background); padding: 12px; border-radius: 4px; overflow-x: auto; font-size: 13px; }
h1 { font-size: 20px; margin-bottom: 16px; }
h2 { font-size: 16px; margin-top: 20px; margin-bottom: 8px; }
.stat { display: inline-block; background: var(--vscode-badge-background); color: var(--vscode-badge-foreground); padding: 2px 8px; border-radius: 4px; font-weight: bold; margin: 2px; }
.warning { color: var(--vscode-editorWarning-foreground); }
.success { color: var(--vscode-testing-iconPassed); }
.section { margin: 16px 0; padding: 12px; border: 1px solid var(--vscode-panel-border); border-radius: 4px; }
</style>
</head>
<body>
${content}
</body>
</html>`;
}

// ---------------------------------------------------------------------------
// Connector commands
// ---------------------------------------------------------------------------

export function registerConnectorCommands(
  context: vscode.ExtensionContext,
  outputChannel: vscode.OutputChannel
): void {
  // List connectors
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.connectors.list", async () => {
      if (!requireCharterCli(outputChannel)) { return; }
      const result = await runCharterCli("connectors list", outputChannel);
      if (result.code === 0) {
        showResultPanel("Charter Connectors", `<h1>Available Connectors</h1><pre>${escapeHtml(result.stdout)}</pre>`, context);
      } else {
        vscode.window.showErrorMessage(`Charter connectors list failed: ${result.stderr}`);
      }
    })
  );

  // Run connector
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.connectors.run", async () => {
      if (!requireCharterCli(outputChannel)) { return; }

      const connectors = [
        { label: "gmail", description: "Gmail — OAuth, read + send" },
        { label: "shopify", description: "Shopify — products, orders, customers" },
        { label: "google_calendar", description: "Google Calendar — events, attendees" },
        { label: "instagram", description: "Instagram — Meta Graph API v21.0" },
        { label: "tiktok", description: "TikTok — Display API v2" },
        { label: "youtube", description: "YouTube — Data API v3" },
        { label: "stripe", description: "Stripe — charges, subscriptions, invoices" },
        { label: "apple_messages", description: "Apple Messages — macOS chat.db" },
        { label: "json_ingestion", description: "JSON Ingestion — HTTP/MCP endpoint" },
      ];

      const selected = await vscode.window.showQuickPick(connectors, {
        placeHolder: "Select a connector to run",
        title: "Charter: Run Connector",
      });

      if (!selected) { return; }

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `Charter: Running ${selected.label} connector...` },
        async () => {
          const result = await runCharterCli(`connectors run --connector ${selected.label}`, outputChannel);
          if (result.code === 0) {
            vscode.window.showInformationMessage(`Charter: ${selected.label} connector completed.`);
          } else {
            vscode.window.showErrorMessage(`Charter: ${selected.label} connector failed. Check output channel.`);
          }
        }
      );
    })
  );

  // Connector info
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.connectors.info", async () => {
      if (!requireCharterCli(outputChannel)) { return; }
      const result = await runCharterCli("connectors list --verbose", outputChannel);
      if (result.code === 0) {
        showResultPanel(
          "Charter Connector Details",
          `<h1>Connector Details</h1><pre>${escapeHtml(result.stdout)}</pre>
          <div class="section">
            <h2>JSON Ingestion Endpoint</h2>
            <p>Any ETL tool (Airbyte, Fivetran, n8n, Zapier, Make.com, Pipedream) can POST to the JSON ingestion endpoint.</p>
            <pre>charter connectors run --connector json_ingestion</pre>
          </div>`,
          context
        );
      } else {
        vscode.window.showErrorMessage(`Charter connector info failed: ${result.stderr}`);
      }
    })
  );
}

// ---------------------------------------------------------------------------
// Analytics commands
// ---------------------------------------------------------------------------

export function registerAnalyticsCommands(
  context: vscode.ExtensionContext,
  outputChannel: vscode.OutputChannel
): void {
  // Absence detection
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.analytics.absence", async () => {
      if (!requireCharterCli(outputChannel)) { return; }

      const actor = await vscode.window.showInputBox({
        prompt: "Actor name (leave empty for all actors)",
        placeHolder: "e.g., matt",
      });

      const actorArg = actor ? ` --actor ${actor}` : "";

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Charter: Running absence detection..." },
        async () => {
          const result = await runCharterCli(`analytics absence${actorArg} --json`, outputChannel);
          if (result.code === 0) {
            let content = `<h1>Bias Detection by Absence</h1>`;
            try {
              const data = JSON.parse(result.stdout);
              const declarations = data.declarations || data;
              if (Array.isArray(declarations)) {
                content += `<p><span class="stat">${declarations.length} declarations</span></p>`;
                const subtypes: Record<string, number> = {};
                for (const d of declarations) {
                  const st = d.subtype || "unknown";
                  subtypes[st] = (subtypes[st] || 0) + 1;
                }
                for (const [st, count] of Object.entries(subtypes)) {
                  content += `<p><span class="stat">${count}</span> ${escapeHtml(st)}</p>`;
                }
                content += `<h2>Full Results</h2><pre>${escapeHtml(JSON.stringify(declarations, null, 2))}</pre>`;
              } else {
                content += `<pre>${escapeHtml(result.stdout)}</pre>`;
              }
            } catch {
              content += `<pre>${escapeHtml(result.stdout)}</pre>`;
            }
            showResultPanel("Absence Detection", content, context);
          } else {
            vscode.window.showErrorMessage(`Absence detection failed. Check output channel.`);
          }
        }
      );
    })
  );

  // Analytics summary
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.analytics.summary", async () => {
      if (!requireCharterCli(outputChannel)) { return; }

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Charter: Loading analytics summary..." },
        async () => {
          const result = await runCharterCli("status --json", outputChannel);
          if (result.code === 0) {
            let content = `<h1>Chain Summary</h1>`;
            try {
              const data = JSON.parse(result.stdout);
              content += `<div class="section">`;
              content += `<p>Chain length: <span class="stat">${data.chain_length ?? "?"}</span></p>`;
              content += `<p>Integrity: <span class="stat ${data.integrity === "ok" ? "success" : "warning"}">${data.integrity ?? "?"}</span></p>`;
              content += `<p>Identity: <span class="stat">${data.alias ?? data.identity ?? "?"}</span></p>`;
              content += `<p>Domain: <span class="stat">${data.domain ?? "?"}</span></p>`;
              content += `</div>`;
              content += `<h2>Raw Output</h2><pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
            } catch {
              content += `<pre>${escapeHtml(result.stdout)}</pre>`;
            }
            showResultPanel("Analytics Summary", content, context);
          } else {
            vscode.window.showErrorMessage(`Analytics summary failed. Check output channel.`);
          }
        }
      );
    })
  );
}

// ---------------------------------------------------------------------------
// Cross-verification commands
// ---------------------------------------------------------------------------

export function registerCrossVerifyCommands(
  context: vscode.ExtensionContext,
  outputChannel: vscode.OutputChannel
): void {
  // Publish attestation
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.crossVerify.publish", async () => {
      if (!requireCharterCli(outputChannel)) { return; }

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Charter: Publishing attestation..." },
        async () => {
          const result = await runCharterCli("cross-verify publish", outputChannel);
          if (result.code === 0) {
            vscode.window.showInformationMessage(
              "Charter: Attestation published successfully.",
              "View Output"
            ).then((action) => {
              if (action === "View Output") {
                outputChannel.show();
              }
            });
          } else {
            vscode.window.showErrorMessage(`Charter: Attestation publish failed. Check output channel.`);
          }
        }
      );
    })
  );

  // Witness a file
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.crossVerify.witness", async () => {
      if (!requireCharterCli(outputChannel)) { return; }

      const fileUri = await vscode.window.showOpenDialog({
        canSelectMany: false,
        openLabel: "Select attestation file to witness",
        filters: { "Attestation files": ["json", "jsonl"], "All files": ["*"] },
      });

      if (!fileUri || fileUri.length === 0) { return; }

      const filePath = fileUri[0].fsPath;

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Charter: Witnessing attestation..." },
        async () => {
          const result = await runCharterCli(`cross-verify witness "${filePath}"`, outputChannel);
          if (result.code === 0) {
            vscode.window.showInformationMessage("Charter: Attestation witnessed successfully.");
          } else {
            vscode.window.showErrorMessage(`Charter: Witness failed. Check output channel.`);
          }
        }
      );
    })
  );

  // List cross-verifications
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.crossVerify.list", async () => {
      if (!requireCharterCli(outputChannel)) { return; }
      const result = await runCharterCli("cross-verify list", outputChannel);
      if (result.code === 0) {
        showResultPanel("Cross-Verifications", `<h1>Cross-Verification History</h1><pre>${escapeHtml(result.stdout)}</pre>`, context);
      } else {
        vscode.window.showErrorMessage(`Charter: cross-verify list failed. Check output channel.`);
      }
    })
  );

  // Check a manifest
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.crossVerify.check", async () => {
      if (!requireCharterCli(outputChannel)) { return; }

      const fileUri = await vscode.window.showOpenDialog({
        canSelectMany: false,
        openLabel: "Select manifest to check",
        filters: { "JSON files": ["json"], "All files": ["*"] },
      });

      if (!fileUri || fileUri.length === 0) { return; }

      const filePath = fileUri[0].fsPath;

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Charter: Checking manifest..." },
        async () => {
          const result = await runCharterCli(`cross-verify check "${filePath}"`, outputChannel);
          if (result.code === 0) {
            showResultPanel("Manifest Check", `<h1>Manifest Verification</h1><pre>${escapeHtml(result.stdout)}</pre>`, context);
          } else {
            vscode.window.showErrorMessage(`Charter: Manifest check failed. Check output channel.`);
          }
        }
      );
    })
  );
}

// ---------------------------------------------------------------------------
// Manifest commands
// ---------------------------------------------------------------------------

export function registerManifestCommands(
  context: vscode.ExtensionContext,
  outputChannel: vscode.OutputChannel
): void {
  // Export manifest
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.manifest.export", async () => {
      if (!requireCharterCli(outputChannel)) { return; }

      const scopes = [
        { label: "individual", description: "Export for a single operator" },
        { label: "organization", description: "Export for the entire organization" },
      ];

      const selected = await vscode.window.showQuickPick(scopes, {
        placeHolder: "Select export scope",
        title: "Charter: Manifest Export Scope",
      });

      if (!selected) { return; }

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Charter: Exporting manifest..." },
        async () => {
          const result = await runCharterCli(`manifest export --scope ${selected.label}`, outputChannel);
          if (result.code === 0) {
            showResultPanel("Manifest Export", `<h1>Manifest Export (${selected.label})</h1><pre>${escapeHtml(result.stdout)}</pre>`, context);
          } else {
            vscode.window.showErrorMessage(`Charter: Manifest export failed. Check output channel.`);
          }
        }
      );
    })
  );

  // Verify manifest
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.manifest.verify", async () => {
      if (!requireCharterCli(outputChannel)) { return; }

      const fileUri = await vscode.window.showOpenDialog({
        canSelectMany: false,
        openLabel: "Select manifest to verify",
        filters: { "JSON files": ["json"], "All files": ["*"] },
      });

      if (!fileUri || fileUri.length === 0) { return; }

      const filePath = fileUri[0].fsPath;

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Charter: Verifying manifest..." },
        async () => {
          const result = await runCharterCli(`manifest verify "${filePath}"`, outputChannel);
          if (result.code === 0) {
            const isValid = result.stdout.toLowerCase().includes("valid");
            showResultPanel(
              "Manifest Verification",
              `<h1>Manifest Verification</h1>
              <p class="${isValid ? "success" : "warning"}">${isValid ? "Manifest is valid." : "Verification completed."}</p>
              <pre>${escapeHtml(result.stdout)}</pre>`,
              context
            );
          } else {
            vscode.window.showErrorMessage(`Charter: Manifest verify failed. Check output channel.`);
          }
        }
      );
    })
  );

  // Adapt manifest for platform
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.manifest.adapt", async () => {
      if (!requireCharterCli(outputChannel)) { return; }

      const platforms = [
        { label: "claude", description: "Claude / Anthropic" },
        { label: "openai", description: "OpenAI / GPT" },
        { label: "xai", description: "xAI / Grok" },
        { label: "rag", description: "RAG / Open Source" },
      ];

      const platform = await vscode.window.showQuickPick(platforms, {
        placeHolder: "Select target platform",
        title: "Charter: Adapt Manifest",
      });

      if (!platform) { return; }

      const fileUri = await vscode.window.showOpenDialog({
        canSelectMany: false,
        openLabel: "Select manifest.json to adapt",
        filters: { "JSON files": ["json"] },
      });

      if (!fileUri || fileUri.length === 0) { return; }

      const filePath = fileUri[0].fsPath;
      const outputDir = path.join(path.dirname(filePath), platform.label);

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `Charter: Adapting for ${platform.label}...` },
        async () => {
          const result = await runCharterCli(
            `manifest adapt --platform ${platform.label} --output "${outputDir}" -i "${filePath}"`,
            outputChannel
          );
          if (result.code === 0) {
            vscode.window.showInformationMessage(
              `Charter: Manifest adapted for ${platform.label}. Output: ${outputDir}`,
              "Open Folder"
            ).then((action) => {
              if (action === "Open Folder") {
                vscode.commands.executeCommand("revealFileInOS", vscode.Uri.file(outputDir));
              }
            });
          } else {
            vscode.window.showErrorMessage(`Charter: Adapt failed. Check output channel.`);
          }
        }
      );
    })
  );
}

// ---------------------------------------------------------------------------
// Identity commands
// ---------------------------------------------------------------------------

export function registerIdentityCommands(
  context: vscode.ExtensionContext,
  outputChannel: vscode.OutputChannel
): void {
  // Show identity
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.identity.show", async () => {
      if (!requireCharterCli(outputChannel)) { return; }
      const result = await runCharterCli("identity", outputChannel);
      if (result.code === 0) {
        showResultPanel("Charter Identity", `<h1>Identity</h1><pre>${escapeHtml(result.stdout)}</pre>`, context);
      } else {
        vscode.window.showErrorMessage(`Charter: identity command failed. Check output channel.`);
      }
    })
  );

  // Check integrity
  context.subscriptions.push(
    vscode.commands.registerCommand("charter.chain.integrity", async () => {
      if (!requireCharterCli(outputChannel)) { return; }

      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Charter: Checking chain integrity..." },
        async () => {
          const result = await runCharterCli("check-integrity", outputChannel);
          if (result.code === 0) {
            const isOk = result.stdout.toLowerCase().includes("ok") || result.stdout.toLowerCase().includes("valid") || result.stdout.toLowerCase().includes("pass");
            vscode.window.showInformationMessage(
              isOk ? "Charter: Chain integrity verified." : "Charter: Integrity check completed. See output for details.",
              "View Details"
            ).then((action) => {
              if (action === "View Details") {
                outputChannel.show();
              }
            });
          } else {
            vscode.window.showWarningMessage("Charter: Integrity check found issues. Check output channel.");
            outputChannel.show();
          }
        }
      );
    })
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
