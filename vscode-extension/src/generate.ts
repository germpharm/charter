/**
 * CLAUDE.md and system-prompt.txt rendering from governance config.
 *
 * Port of charter/generate.py render_claude_md() and render_system_prompt().
 * Produces output identical to the Python CLI.
 *
 * Zero external dependencies.
 */

import { CharterConfig, LayerBRule, KillTrigger } from "./types";

// ---------------------------------------------------------------------------
// UTC timestamp — matches Python time.strftime("%Y-%m-%d %H:%M UTC", gmtime())
// ---------------------------------------------------------------------------

function utcDatetime(): string {
  const d = new Date();
  const pad = (n: number): string => n.toString().padStart(2, "0");
  return (
    d.getUTCFullYear() +
    "-" +
    pad(d.getUTCMonth() + 1) +
    "-" +
    pad(d.getUTCDate()) +
    " " +
    pad(d.getUTCHours()) +
    ":" +
    pad(d.getUTCMinutes()) +
    " UTC"
  );
}

// ---------------------------------------------------------------------------
// Title case for report items: "decisions_made" -> "Decisions Made"
// Mirrors Python: item.replace("_", " ").title()
// ---------------------------------------------------------------------------

function titleCase(s: string): string {
  return s
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// CLAUDE.md renderer — exact port of Python render_claude_md()
// ---------------------------------------------------------------------------

/**
 * Render governance config as a CLAUDE.md file.
 * Output matches the Python CLI character-for-character.
 */
export function renderClaudeMd(config: CharterConfig): string {
  const gov = config.governance;
  const domain = config.domain || "general";
  const identity = config.identity;
  const version = config.version || "1.0";

  const lines: string[] = [];

  lines.push(`# Governance Layer — Charter v${version}`);
  lines.push("");
  lines.push(`Domain: ${domain}`);
  lines.push(`Generated: ${utcDatetime()}`);
  if (identity?.alias) {
    lines.push(`Node: ${identity.alias}`);
  }
  lines.push("");
  lines.push("This file defines the governance rules for AI agents in this project.");
  lines.push("These rules are mandatory. Follow them exactly as written.");
  lines.push("");

  // Layer A
  lines.push("## Layer A: Hard Constraints");
  lines.push("");
  lines.push(gov.layer_a.description);
  lines.push("You MUST comply with every rule below. No exceptions.");
  lines.push("");

  // Universal floor
  const universal = gov.layer_a.universal || [];
  if (universal.length > 0) {
    lines.push("### Universal (accountability floor)");
    lines.push("These constraints are structural. They cannot be removed.");
    lines.push("");
    for (const rule of universal) {
      lines.push(`- ${rule}`);
    }
    lines.push("");
  }

  // Domain rules
  if (gov.layer_a.rules && gov.layer_a.rules.length > 0) {
    lines.push("### Domain Rules");
    lines.push("");
    for (const rule of gov.layer_a.rules) {
      lines.push(`- ${rule}`);
    }
    lines.push("");
  }

  // Layer B
  lines.push("## Layer B: Gradient Decisions");
  lines.push("");
  lines.push(gov.layer_b.description);
  lines.push(
    "Before taking any of these actions, check the threshold and get approval if required."
  );
  lines.push("");

  for (const rule of gov.layer_b.rules) {
    const r = rule as LayerBRule;
    const action = r.action || "unknown";
    const threshold = r.threshold || "N/A";
    const requires = r.requires || "human_review";
    const desc = r.description || "";
    lines.push(
      `- **${action}**: Threshold: ${threshold}. Requires: ${requires}. ${desc}`
    );
  }
  lines.push("");

  // Layer C
  lines.push("## Layer C: Self-Audit");
  lines.push("");
  lines.push(gov.layer_c.description);
  const freq = gov.layer_c.frequency;
  lines.push(`Audit frequency: ${freq}`);
  lines.push("");
  lines.push(`At the end of each ${freq}, generate an audit report that includes:`);
  for (const item of gov.layer_c.report_includes) {
    lines.push(`- ${titleCase(item)}`);
  }
  lines.push("");
  lines.push(
    "The audit report must be honest. If rules were bent or gray areas were navigated,"
  );
  lines.push(
    "report them transparently. The purpose of the audit is accountability, not perfection."
  );
  lines.push("");

  // Kill triggers
  if (gov.kill_triggers && gov.kill_triggers.length > 0) {
    lines.push("## Kill Triggers");
    lines.push("");
    lines.push(
      "Immediately stop all work and alert the human operator if any of these occur:"
    );
    lines.push("");
    for (const trigger of gov.kill_triggers) {
      const t = trigger as KillTrigger;
      lines.push(`- **${t.trigger}**: ${t.description}`);
    }
    lines.push("");
  }

  return lines.join("\n");
}

// ---------------------------------------------------------------------------
// system-prompt.txt renderer — exact port of Python render_system_prompt()
// ---------------------------------------------------------------------------

/**
 * Render governance config as a system prompt for any AI.
 * Output matches the Python CLI character-for-character.
 */
export function renderSystemPrompt(config: CharterConfig): string {
  const gov = config.governance;
  const domain = config.domain || "general";

  const lines: string[] = [];

  lines.push(
    `You are operating under a governance framework (Charter). Domain: ${domain}.`
  );
  lines.push("");
  lines.push("HARD CONSTRAINTS (never violate):");
  lines.push("");

  // Universal
  const universal = gov.layer_a.universal || [];
  if (universal.length > 0) {
    lines.push("Universal (accountability floor):");
    for (const rule of universal) {
      lines.push(`- ${rule}`);
    }
    lines.push("");
  }

  // Domain rules
  if (gov.layer_a.rules && gov.layer_a.rules.length > 0) {
    lines.push("Domain rules:");
    for (const rule of gov.layer_a.rules) {
      lines.push(`- ${rule}`);
    }
  }
  lines.push("");

  // Approval required
  lines.push("APPROVAL REQUIRED (check before acting):");
  for (const rule of gov.layer_b.rules) {
    const r = rule as LayerBRule;
    const action = r.action || "";
    const desc = r.description || "";
    lines.push(`- ${action}: ${desc}`);
  }
  lines.push("");

  // Self-audit
  lines.push(
    `SELF-AUDIT: At the end of each ${gov.layer_c.frequency}, report what you did and why.`
  );
  lines.push("Be transparent about gray areas. Accountability, not perfection.");
  lines.push("");

  // Kill triggers
  if (gov.kill_triggers && gov.kill_triggers.length > 0) {
    lines.push("KILL TRIGGERS (stop immediately and alert human):");
    for (const trigger of gov.kill_triggers) {
      const t = trigger as KillTrigger;
      lines.push(`- ${t.trigger}: ${t.description}`);
    }
  }

  return lines.join("\n");
}
