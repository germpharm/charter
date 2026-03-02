/**
 * Context manager for Charter governance sessions.
 *
 * When a governed workspace opens, reads the hash chain to determine
 * the last session state and prompts the user to either continue
 * the existing session or start a new context.
 *
 * A "context boundary" is a chain entry that marks a logical break
 * between work sessions. This gives the audit trail semantic structure —
 * not just a flat list of events, but identifiable work sessions.
 *
 * Zero external dependencies. Uses Node.js fs/path/os only.
 */

import * as vscode from "vscode";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { appendToChain } from "./identity";
import { ChainEntry } from "./types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHAIN_FILE = path.join(os.homedir(), ".charter", "chain.jsonl");

// Key for tracking whether we've prompted this session
const KEY_CONTEXT_PROMPTED = "charter.contextPromptedThisSession";

// ---------------------------------------------------------------------------
// Chain reading helpers
// ---------------------------------------------------------------------------

interface SessionSummary {
  totalEntries: number;
  lastEntry: ChainEntry | null;
  lastTimestamp: string | null;
  lastEvent: string | null;
  lastContextBoundary: ChainEntry | null;
  entriesSinceLastBoundary: number;
  lastAnchorTimestamp: string | null;
  domain: string | null;
  organization: string | null;
}

/**
 * Read the chain and produce a summary of the current session state.
 * Reads only the tail of the chain to avoid loading huge files.
 */
function getSessionSummary(charterPath: string): SessionSummary {
  const summary: SessionSummary = {
    totalEntries: 0,
    lastEntry: null,
    lastTimestamp: null,
    lastEvent: null,
    lastContextBoundary: null,
    entriesSinceLastBoundary: 0,
    lastAnchorTimestamp: null,
    domain: null,
    organization: null,
  };

  // Read charter.yaml for domain/org info
  try {
    const charterContent = fs.readFileSync(charterPath, "utf8");
    const domainMatch = charterContent.match(/^domain:\s*(.+)$/m);
    if (domainMatch) {
      summary.domain = domainMatch[1].trim();
    }
    const orgMatch = charterContent.match(/^\s*organization:\s*(.+)$/m);
    if (orgMatch) {
      summary.organization = orgMatch[1].trim();
    }
  } catch {
    // Non-critical — proceed without domain/org
  }

  // Read chain file
  if (!fs.existsSync(CHAIN_FILE)) {
    return summary;
  }

  try {
    const content = fs.readFileSync(CHAIN_FILE, "utf8");
    const lines = content.split("\n").filter((line) => line.trim());
    summary.totalEntries = lines.length;

    if (lines.length === 0) {
      return summary;
    }

    // Parse last entry
    const lastLine = lines[lines.length - 1];
    summary.lastEntry = JSON.parse(lastLine) as ChainEntry;
    summary.lastTimestamp = summary.lastEntry.timestamp;
    summary.lastEvent = summary.lastEntry.event;

    // Scan backwards for context boundary and anchor (limit to last 500 entries)
    const scanStart = Math.max(0, lines.length - 500);
    let countSinceBoundary = 0;

    for (let i = lines.length - 1; i >= scanStart; i--) {
      const entry = JSON.parse(lines[i]) as ChainEntry;

      if (
        entry.event === "context_boundary" &&
        !summary.lastContextBoundary
      ) {
        summary.lastContextBoundary = entry;
        summary.entriesSinceLastBoundary = countSinceBoundary;
      }

      if (entry.event === "timestamp_anchor" && !summary.lastAnchorTimestamp) {
        const tsaTime = (entry.data as Record<string, string>)?.tsa_timestamp;
        summary.lastAnchorTimestamp = tsaTime || entry.timestamp;
      }

      if (summary.lastContextBoundary && summary.lastAnchorTimestamp) {
        break;
      }

      countSinceBoundary++;
    }

    // If no boundary found, all scanned entries are since last boundary
    if (!summary.lastContextBoundary) {
      summary.entriesSinceLastBoundary = countSinceBoundary;
    }
  } catch {
    // Chain unreadable — non-critical
  }

  return summary;
}

// ---------------------------------------------------------------------------
// Time formatting
// ---------------------------------------------------------------------------

function formatRelativeTime(isoTimestamp: string): string {
  try {
    const then = new Date(isoTimestamp).getTime();
    const now = Date.now();
    const diffMs = now - then;

    if (diffMs < 0) return "just now";

    const minutes = Math.floor(diffMs / 60000);
    const hours = Math.floor(diffMs / 3600000);
    const days = Math.floor(diffMs / 86400000);

    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
    if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
    if (days < 7) return `${days} day${days === 1 ? "" : "s"} ago`;

    return new Date(isoTimestamp).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return isoTimestamp;
  }
}

function formatTimestamp(isoTimestamp: string): string {
  try {
    return new Date(isoTimestamp).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZoneName: "short",
    });
  } catch {
    return isoTimestamp;
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Show the context continuation prompt when a governed workspace opens.
 *
 * Called once per VS Code session (tracked via globalState).
 * Shows a summary of the last session and asks the user to continue
 * or start a new context.
 */
export async function promptForContext(
  context: vscode.ExtensionContext,
  charterPath: string,
  outputChannel: vscode.OutputChannel
): Promise<void> {
  // Only prompt once per VS Code session
  const alreadyPrompted = context.globalState.get<boolean>(
    KEY_CONTEXT_PROMPTED,
    false
  );
  if (alreadyPrompted) {
    return;
  }

  // Mark as prompted immediately to prevent double-prompts
  await context.globalState.update(KEY_CONTEXT_PROMPTED, true);

  const summary = getSessionSummary(charterPath);

  // If there's no chain at all, this is a fresh project — no prompt needed
  if (summary.totalEntries === 0) {
    outputChannel.appendLine(
      `[${new Date().toISOString()}] No chain entries found. Skipping context prompt.`
    );
    return;
  }

  // Build the context panel content
  const orgLine = summary.organization || "Unknown";
  const domainLine = summary.domain || "general";
  const lastActivityLine = summary.lastTimestamp
    ? `${formatRelativeTime(summary.lastTimestamp)} (${formatTimestamp(summary.lastTimestamp)})`
    : "Unknown";
  const entriesLine = summary.totalEntries.toLocaleString();
  const anchorLine = summary.lastAnchorTimestamp
    ? formatTimestamp(summary.lastAnchorTimestamp)
    : "None";

  // Context from last boundary
  let contextNote = "";
  if (summary.lastContextBoundary) {
    const boundaryData = summary.lastContextBoundary.data as Record<
      string,
      string
    >;
    const prevContext = boundaryData?.new_context || boundaryData?.note;
    if (prevContext) {
      contextNote = `\nLast context: "${prevContext}"`;
    }
  }

  outputChannel.appendLine(
    `[${new Date().toISOString()}] Context prompt: org=${orgLine}, domain=${domainLine}, entries=${entriesLine}, last=${summary.lastTimestamp}`
  );

  // Show the prompt as an information message with actions
  const message = [
    `Charter — ${orgLine}`,
    `Domain: ${domainLine} | Chain: ${entriesLine} entries`,
    `Last activity: ${lastActivityLine}`,
    `Last anchor: ${anchorLine}`,
    contextNote,
  ]
    .filter(Boolean)
    .join("\n");

  const action = await vscode.window.showInformationMessage(
    message,
    { modal: false },
    "Continue Session",
    "New Context",
    "View Audit"
  );

  if (action === "New Context") {
    // Ask for a brief description of the new context
    const note = await vscode.window.showInputBox({
      prompt: "Briefly describe what you're working on (optional)",
      placeHolder: "e.g., CSO review, label preparation, regulatory filing",
    });

    // Get previous context for the boundary entry
    let previousContext = "";
    if (summary.lastContextBoundary) {
      const boundaryData = summary.lastContextBoundary.data as Record<
        string,
        string
      >;
      previousContext = boundaryData?.new_context || "";
    }

    // Write context boundary to chain
    const entry = appendToChain("context_boundary", {
      previous_context: previousContext,
      new_context: note || "New session",
      reason: "user_initiated",
      previous_entries: summary.totalEntries,
    });

    if (entry) {
      outputChannel.appendLine(
        `[${new Date().toISOString()}] Context boundary recorded at index ${entry.index}: "${note || "New session"}"`
      );
      vscode.window.showInformationMessage(
        `Charter: New context started${note ? ` — "${note}"` : ""}.`
      );
    } else {
      outputChannel.appendLine(
        `[${new Date().toISOString()}] Failed to write context boundary to chain.`
      );
    }
  } else if (action === "Continue Session") {
    // Record session continuation (lightweight chain entry)
    appendToChain("session_continued", {
      entries_at_resume: summary.totalEntries,
    });
    outputChannel.appendLine(
      `[${new Date().toISOString()}] Session continued. Chain at ${summary.totalEntries} entries.`
    );
  } else if (action === "View Audit") {
    // Open the audit directory or the chain file
    const auditDir = path.join(path.dirname(charterPath), "charter_audits");
    if (fs.existsSync(auditDir)) {
      const uri = vscode.Uri.file(auditDir);
      vscode.commands.executeCommand("revealFileInOS", uri);
    } else if (fs.existsSync(CHAIN_FILE)) {
      const doc = await vscode.workspace.openTextDocument(CHAIN_FILE);
      await vscode.window.showTextDocument(doc);
    }
  }
  // If user dismisses (clicks away), no action — session continues implicitly
}

/**
 * Reset the context prompt flag. Call this on deactivation so the
 * next VS Code session will prompt again.
 */
export async function resetContextPrompt(
  context: vscode.ExtensionContext
): Promise<void> {
  await context.globalState.update(KEY_CONTEXT_PROMPTED, false);
}
