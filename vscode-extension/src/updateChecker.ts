/**
 * PyPI update checker for Charter governance.
 *
 * Checks once per 24 hours whether a newer version of charter-governance
 * is available on PyPI. Results are cached to globalState so we don't
 * hit the network on every window open.
 *
 * Non-blocking. Never throws. If the check fails (offline, timeout),
 * it silently skips until the next window.
 *
 * Zero external dependencies — uses Node.js https module only.
 */

import * as vscode from "vscode";
import * as https from "https";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PYPI_URL = "https://pypi.org/pypi/charter-governance/json";
const CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000; // 24 hours
const HTTP_TIMEOUT_MS = 5000;

// Keys for vscode.ExtensionContext.globalState
const KEY_LATEST_VERSION = "charter.latestVersion";
const KEY_LAST_CHECK = "charter.lastUpdateCheck";
const KEY_DISMISSED_VERSION = "charter.dismissedVersion";

// ---------------------------------------------------------------------------
// Version comparison
// ---------------------------------------------------------------------------

function versionTuple(v: string): number[] {
  return v.split(".").map((n) => parseInt(n, 10) || 0);
}

function isNewer(latest: string, current: string): boolean {
  const a = versionTuple(latest);
  const b = versionTuple(current);
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const ai = a[i] || 0;
    const bi = b[i] || 0;
    if (ai > bi) return true;
    if (ai < bi) return false;
  }
  return false;
}

// ---------------------------------------------------------------------------
// HTTP fetch (zero-dependency)
// ---------------------------------------------------------------------------

function fetchLatestVersion(): Promise<string | null> {
  return new Promise((resolve) => {
    const req = https.get(
      PYPI_URL,
      { headers: { Accept: "application/json" }, timeout: HTTP_TIMEOUT_MS },
      (res) => {
        if (res.statusCode !== 200) {
          res.resume();
          resolve(null);
          return;
        }
        let data = "";
        res.on("data", (chunk: Buffer) => {
          data += chunk.toString();
        });
        res.on("end", () => {
          try {
            const json = JSON.parse(data);
            const version = json?.info?.version;
            resolve(typeof version === "string" ? version : null);
          } catch {
            resolve(null);
          }
        });
      }
    );
    req.on("error", () => resolve(null));
    req.on("timeout", () => {
      req.destroy();
      resolve(null);
    });
  });
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface UpdateCheckResult {
  updateAvailable: boolean;
  currentVersion: string;
  latestVersion: string | null;
}

/**
 * Check for updates, respecting the 24-hour cache.
 *
 * Call this once during activation. It will:
 * 1. Check globalState for a cached result
 * 2. If stale (>24h), fetch from PyPI in the background
 * 3. If an update is available AND not dismissed, show a toast
 * 4. Update the status bar text if an update exists
 */
export async function checkForUpdates(
  context: vscode.ExtensionContext,
  currentVersion: string,
  outputChannel: vscode.OutputChannel,
  statusBarItem: vscode.StatusBarItem
): Promise<UpdateCheckResult> {
  const now = Date.now();
  const lastCheck = context.globalState.get<number>(KEY_LAST_CHECK, 0);
  const cachedLatest = context.globalState.get<string>(KEY_LATEST_VERSION, "");
  const dismissedVersion = context.globalState.get<string>(
    KEY_DISMISSED_VERSION,
    ""
  );

  let latestVersion = cachedLatest;

  // Check PyPI if cache is stale
  if (now - lastCheck > CHECK_INTERVAL_MS) {
    outputChannel.appendLine(
      `[${new Date().toISOString()}] Checking PyPI for Charter updates...`
    );

    const fetched = await fetchLatestVersion();
    if (fetched) {
      latestVersion = fetched;
      await context.globalState.update(KEY_LATEST_VERSION, fetched);
      outputChannel.appendLine(
        `[${new Date().toISOString()}] PyPI latest: ${fetched}, installed: ${currentVersion}`
      );
    } else {
      outputChannel.appendLine(
        `[${new Date().toISOString()}] PyPI check failed (offline or timeout). Using cached.`
      );
    }
    await context.globalState.update(KEY_LAST_CHECK, now);
  }

  const updateAvailable = !!latestVersion && isNewer(latestVersion, currentVersion);

  if (updateAvailable) {
    // Update status bar to show version info
    const currentText = statusBarItem.text;
    if (!currentText.includes("↑")) {
      statusBarItem.text = `${currentText}  $(arrow-up) ${latestVersion}`;
      statusBarItem.tooltip += `\n\nUpdate available: v${currentVersion} → v${latestVersion}\nRun 'charter update' to upgrade`;
    }

    // Show toast (once per new version, dismissible)
    if (latestVersion !== dismissedVersion) {
      const action = await vscode.window.showInformationMessage(
        `Charter v${latestVersion} is available (you have v${currentVersion}).`,
        "Update Now",
        "Release Notes",
        "Dismiss"
      );

      if (action === "Update Now") {
        const terminal = vscode.window.createTerminal("Charter Update");
        terminal.show();
        terminal.sendText("charter update");
      } else if (action === "Release Notes") {
        vscode.env.openExternal(
          vscode.Uri.parse(
            "https://github.com/germpharm/charter/blob/main/CHANGELOG.md"
          )
        );
      } else if (action === "Dismiss") {
        await context.globalState.update(KEY_DISMISSED_VERSION, latestVersion);
      }
    }
  }

  return { updateAvailable, currentVersion, latestVersion };
}
