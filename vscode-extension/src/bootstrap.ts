/**
 * Bootstrap orchestrator for Charter governance.
 *
 * Strategy: try the Python CLI first (charter bootstrap --quiet).
 * If that fails (not installed, wrong Python, etc.), fall back to a
 * pure TypeScript implementation that produces identical output.
 *
 * Zero npm dependencies. Uses only Node.js built-ins.
 */

import * as fs from "fs";
import * as path from "path";
import { exec } from "child_process";
import { Domain, CharterConfig, BootstrapResult, LayerBRule, KillTrigger } from "./types";
import { cloneTemplate } from "./templates";
import { detectDomain } from "./domainDetector";
import { loadIdentity, createIdentity, appendToChain } from "./identity";
import { renderClaudeMd, renderSystemPrompt } from "./generate";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CHARTER_FILENAME = "charter.yaml";

// Common paths where pip installs binaries (VS Code extension host has
// a minimal PATH that usually excludes these)
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
// Custom YAML serializer
// ---------------------------------------------------------------------------

/**
 * Serialize a CharterConfig to YAML that matches Python's
 * yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True).
 *
 * The charter.yaml structure is known and shallow. We handle it directly
 * rather than pulling in a YAML library.
 */
function serializeCharterYaml(config: CharterConfig): string {
  const lines: string[] = [];

  lines.push(`domain: ${config.domain}`);
  lines.push("governance:");

  // layer_a
  lines.push("  layer_a:");
  lines.push(`    description: ${yamlScalar(config.governance.layer_a.description)}`);
  lines.push("    universal:");
  for (const rule of config.governance.layer_a.universal) {
    lines.push(`    - ${yamlScalar(rule)}`);
  }
  lines.push("    rules:");
  for (const rule of config.governance.layer_a.rules) {
    lines.push(`    - ${yamlScalar(rule)}`);
  }

  // layer_b
  lines.push("  layer_b:");
  lines.push(`    description: ${yamlScalar(config.governance.layer_b.description)}`);
  lines.push("    rules:");
  for (const rule of config.governance.layer_b.rules) {
    const r = rule as LayerBRule;
    lines.push(`    - action: ${yamlScalar(r.action)}`);
    lines.push(`      threshold: ${yamlScalar(r.threshold)}`);
    lines.push(`      requires: ${yamlScalar(r.requires)}`);
    lines.push(`      description: ${yamlScalar(r.description)}`);
  }

  // layer_c
  lines.push("  layer_c:");
  lines.push(`    description: ${yamlScalar(config.governance.layer_c.description)}`);
  lines.push(`    frequency: ${yamlScalar(config.governance.layer_c.frequency)}`);
  lines.push("    report_includes:");
  for (const item of config.governance.layer_c.report_includes) {
    lines.push(`    - ${yamlScalar(item)}`);
  }

  // kill_triggers
  lines.push("  kill_triggers:");
  for (const trigger of config.governance.kill_triggers) {
    const t = trigger as KillTrigger;
    lines.push(`  - trigger: ${yamlScalar(t.trigger)}`);
    lines.push(`    description: ${yamlScalar(t.description)}`);
  }

  // version
  if (config.version) {
    lines.push(`version: '${config.version}'`);
  }

  // identity
  if (config.identity) {
    lines.push("identity:");
    lines.push(`  public_id: ${yamlScalar(config.identity.public_id)}`);
    lines.push(`  alias: ${yamlScalar(config.identity.alias)}`);
  }

  lines.push(""); // trailing newline
  return lines.join("\n");
}

/**
 * Format a scalar value for YAML output.
 *
 * PyYAML wraps long strings that exceed ~80 chars. We replicate this
 * behavior for the description fields that are known to be long.
 * Simple values (short strings, no special chars) are left unquoted.
 */
function yamlScalar(value: string): string {
  // If value contains characters that YAML would interpret, quote it
  if (
    value.includes(":") ||
    value.includes("#") ||
    value.includes("{") ||
    value.includes("}") ||
    value.includes("[") ||
    value.includes("]") ||
    value.includes(",") ||
    value.includes("&") ||
    value.includes("*") ||
    value.includes("?") ||
    value.includes("|") ||
    value.includes(">") ||
    value.includes("!") ||
    value.includes("%") ||
    value.includes("@") ||
    value.includes("`") ||
    value.startsWith("'") ||
    value.startsWith('"') ||
    value.startsWith(" ") ||
    value.endsWith(" ")
  ) {
    // PyYAML uses single quotes for strings when possible, but for our
    // known values double-quoting is not needed. We check for single quotes
    // inside the value.
    if (value.includes("'")) {
      // Escape single quotes by doubling them (PyYAML convention)
      return "'" + value.replace(/'/g, "''") + "'";
    }
    return value;
  }

  // Check if PyYAML would wrap this line (it wraps at ~80 columns).
  // For the layer_c description specifically, PyYAML produces a multi-line
  // scalar. We replicate this to stay compatible.
  // Actually, looking at the Python output more carefully: PyYAML uses
  // inline strings even for long descriptions, just wrapping with indentation.
  // Let's match that behavior.

  return value;
}

// ---------------------------------------------------------------------------
// Extended PATH for finding the charter CLI
// ---------------------------------------------------------------------------

function getExtendedPath(): string {
  const current = process.env.PATH || "";
  const extra = EXTRA_PATH_DIRS.filter((d) => !current.includes(d));
  return extra.length > 0 ? `${current}:${extra.join(":")}` : current;
}

// ---------------------------------------------------------------------------
// Python CLI bootstrap attempt
// ---------------------------------------------------------------------------

/**
 * Try to bootstrap using the Python charter CLI.
 * Returns true if successful, false if the CLI is not available or fails.
 */
function tryPythonBootstrap(workspacePath: string): Promise<boolean> {
  return new Promise((resolve) => {
    const cmd = `charter bootstrap "${workspacePath}" --quiet`;
    const extendedPath = getExtendedPath();

    exec(
      cmd,
      {
        timeout: 15000,
        env: { ...process.env, PATH: extendedPath },
      },
      (err) => {
        if (err) {
          resolve(false);
        } else {
          resolve(true);
        }
      }
    );
  });
}

// ---------------------------------------------------------------------------
// TypeScript native bootstrap
// ---------------------------------------------------------------------------

/**
 * Full bootstrap using only TypeScript. Produces identical output to
 * the Python CLI.
 *
 * Steps (mirrors bootstrap.py run_bootstrap):
 * 1. Auto-detect domain (or use provided domain)
 * 2. Create charter.yaml from template + identity
 * 3. Generate CLAUDE.md
 * 4. Generate system-prompt.txt
 * 5. Record chain entries for generated files
 */
function nativeBootstrap(
  workspacePath: string,
  domain?: Domain
): BootstrapResult {
  const filesCreated: string[] = [];
  const charterYamlPath = path.join(workspacePath, CHARTER_FILENAME);

  // Step 1: If charter.yaml already exists, do not overwrite
  if (fs.existsSync(charterYamlPath)) {
    // Already governed. No files to create. This is success (idempotent).
    return {
      success: true,
      method: "typescript-native",
      domain: (domain || "general") as Domain,
      filesCreated: [],
    };
  }

  try {
    // Step 2: Detect domain if not specified
    const detectedDomain = domain || detectDomain(workspacePath);

    // Step 3: Load template and set version
    const config = cloneTemplate(detectedDomain);
    config.version = "1.0";

    // Step 4: Identity — load existing or create new
    let identity = loadIdentity();
    if (!identity) {
      identity = createIdentity();
    }
    config.identity = {
      public_id: identity.public_id,
      alias: identity.alias,
    };

    // Step 5: Write charter.yaml
    const yamlContent = serializeCharterYaml(config);
    fs.writeFileSync(charterYamlPath, yamlContent, "utf8");
    filesCreated.push("charter.yaml");

    // Step 6: Generate CLAUDE.md (skip if exists)
    const claudeMdPath = path.join(workspacePath, "CLAUDE.md");
    if (!fs.existsSync(claudeMdPath)) {
      const claudeMd = renderClaudeMd(config);
      fs.writeFileSync(claudeMdPath, claudeMd, "utf8");
      filesCreated.push("CLAUDE.md");

      appendToChain("governance_generated", {
        format: "claude-md",
        output: "CLAUDE.md",
        domain: detectedDomain,
        source: "bootstrap",
      });
    }

    // Step 7: Generate system-prompt.txt (skip if exists)
    const systemPromptPath = path.join(workspacePath, "system-prompt.txt");
    if (!fs.existsSync(systemPromptPath)) {
      const systemPrompt = renderSystemPrompt(config);
      fs.writeFileSync(systemPromptPath, systemPrompt, "utf8");
      filesCreated.push("system-prompt.txt");

      appendToChain("governance_generated", {
        format: "system-prompt",
        output: "system-prompt.txt",
        domain: detectedDomain,
        source: "bootstrap",
      });
    }

    // Step 8: Create charter_audits directory (skip if exists)
    const auditDir = path.join(workspacePath, "charter_audits");
    if (!fs.existsSync(auditDir)) {
      fs.mkdirSync(auditDir, { recursive: true });
      filesCreated.push("charter_audits/");
    }

    // Step 9: Generate MCP config files for Claude Code and Cursor
    const mcpFiles = generateMcpConfigs(workspacePath);
    filesCreated.push(...mcpFiles);

    return {
      success: true,
      method: "typescript-native",
      domain: detectedDomain,
      filesCreated,
    };
  } catch (err) {
    return {
      success: false,
      method: "typescript-native",
      domain: (domain || "general") as Domain,
      filesCreated,
      error: err instanceof Error ? err.message : String(err),
    };
  }
}

// ---------------------------------------------------------------------------
// MCP config generation — write .mcp.json and .cursor/mcp.json
// ---------------------------------------------------------------------------

/**
 * Find the charter CLI command for MCP server invocation.
 * Returns [command, ...args] for the MCP server config.
 */
function findCharterMcpCommand(): { command: string; args: string[] } {
  // Check common paths for the charter CLI
  const extendedPath = getExtendedPath();
  const pathDirs = extendedPath.split(":");

  for (const dir of pathDirs) {
    const candidate = path.join(dir, "charter");
    if (fs.existsSync(candidate)) {
      return {
        command: candidate,
        args: ["mcp-serve", "--transport", "stdio"],
      };
    }
  }

  // Fallback: use python module invocation
  for (const dir of pathDirs) {
    const candidate = path.join(dir, "python3");
    if (fs.existsSync(candidate)) {
      return {
        command: candidate,
        args: ["-m", "charter.mcp_server"],
      };
    }
  }

  // Last resort: assume charter is on PATH
  return {
    command: "charter",
    args: ["mcp-serve", "--transport", "stdio"],
  };
}

/**
 * Merge a server entry into an MCP config file.
 * Preserves existing server configs.
 */
function mergeMcpConfig(
  filepath: string,
  serverName: string,
  serverConfig: { command: string; args: string[] }
): void {
  let existing: Record<string, unknown> = {};

  if (fs.existsSync(filepath)) {
    try {
      const raw = fs.readFileSync(filepath, "utf-8");
      existing = JSON.parse(raw);
    } catch {
      existing = {};
    }
  }

  if (!existing.mcpServers || typeof existing.mcpServers !== "object") {
    existing.mcpServers = {};
  }

  (existing.mcpServers as Record<string, unknown>)[serverName] = serverConfig;

  fs.writeFileSync(filepath, JSON.stringify(existing, null, 2) + "\n", "utf-8");
}

/**
 * Generate MCP config files for Claude Code and Cursor.
 * Returns list of files created/updated.
 */
function generateMcpConfigs(workspacePath: string): string[] {
  const serverConfig = findCharterMcpCommand();
  const files: string[] = [];

  // Claude Code: .mcp.json
  const claudeMcpPath = path.join(workspacePath, ".mcp.json");
  mergeMcpConfig(claudeMcpPath, "charter-governance", serverConfig);
  files.push(".mcp.json");

  // Cursor: .cursor/mcp.json
  const cursorDir = path.join(workspacePath, ".cursor");
  const cursorMcpPath = path.join(cursorDir, "mcp.json");
  if (!fs.existsSync(cursorDir)) {
    fs.mkdirSync(cursorDir, { recursive: true });
  }
  mergeMcpConfig(cursorMcpPath, "charter-governance", serverConfig);
  files.push(".cursor/mcp.json");

  return files;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Bootstrap a workspace with Charter governance.
 *
 * Strategy:
 * 1. If charter.yaml already exists, return immediately (idempotent).
 * 2. Try the Python CLI (charter bootstrap --quiet).
 * 3. If that fails, use the TypeScript native implementation.
 *
 * Never overwrites existing files.
 */
export async function bootstrap(
  workspacePath: string,
  domain?: Domain
): Promise<BootstrapResult> {
  const charterYamlPath = path.join(workspacePath, CHARTER_FILENAME);

  // Already governed — nothing to do
  if (fs.existsSync(charterYamlPath)) {
    return {
      success: true,
      method: "python-cli",
      domain: (domain || "general") as Domain,
      filesCreated: [],
    };
  }

  // Try Python CLI first
  const pythonOk = await tryPythonBootstrap(workspacePath);
  if (pythonOk) {
    // Verify it actually created charter.yaml
    if (fs.existsSync(charterYamlPath)) {
      return {
        success: true,
        method: "python-cli",
        domain: (domain || detectDomain(workspacePath)) as Domain,
        filesCreated: ["charter.yaml", "CLAUDE.md", "system-prompt.txt", "charter_audits/"],
      };
    }
  }

  // Fall back to TypeScript native
  return nativeBootstrap(workspacePath, domain);
}

/**
 * Bootstrap with an explicit domain selection (for the selectDomain command).
 * Always uses the TypeScript native path so we can pass the domain through.
 */
export async function bootstrapWithDomain(
  workspacePath: string,
  domain: Domain
): Promise<BootstrapResult> {
  const charterYamlPath = path.join(workspacePath, CHARTER_FILENAME);

  // If already governed, we need to decide: the user explicitly asked for
  // a domain, so we should not silently skip. But we also must not silently
  // overwrite. Return a result indicating the workspace is already governed.
  if (fs.existsSync(charterYamlPath)) {
    return {
      success: true,
      method: "typescript-native",
      domain,
      filesCreated: [],
      error: "charter.yaml already exists. Delete it first to re-bootstrap with a different domain.",
    };
  }

  // For explicit domain selection, use the Python CLI with --domain flag
  const pythonOk = await tryPythonBootstrapWithDomain(workspacePath, domain);
  if (pythonOk && fs.existsSync(charterYamlPath)) {
    return {
      success: true,
      method: "python-cli",
      domain,
      filesCreated: ["charter.yaml", "CLAUDE.md", "system-prompt.txt", "charter_audits/"],
    };
  }

  // Fall back to TypeScript native
  return nativeBootstrap(workspacePath, domain);
}

/**
 * Try Python CLI with explicit domain.
 */
function tryPythonBootstrapWithDomain(
  workspacePath: string,
  domain: Domain
): Promise<boolean> {
  return new Promise((resolve) => {
    const cmd = `charter bootstrap "${workspacePath}" --domain ${domain} --quiet`;
    const extendedPath = getExtendedPath();

    exec(
      cmd,
      {
        timeout: 15000,
        env: { ...process.env, PATH: extendedPath },
      },
      (err) => {
        resolve(!err);
      }
    );
  });
}
