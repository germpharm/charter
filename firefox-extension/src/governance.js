/**
 * Charter Governance Engine — runs entirely inside the Chrome extension.
 *
 * No daemon. No CLI. No pip install. No terminal.
 *
 * This module provides:
 * - Identity creation (SHA-256 pseudonymous)
 * - Hash chain (HMAC-SHA256 tamper-evident audit trail)
 * - Governance state management
 * - Self-audit on a timer
 *
 * All data stored in chrome.storage.local.
 * Zero dependencies. Zero network calls.
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const VERSION = "3.0.0";

export const DOMAINS = ["general", "healthcare", "finance", "education", "personal"];

// Storage keys
const STORE = {
  identity: "charter_identity",
  config: "charter_config",
  chain: "charter_chain",
  onboarded: "charter_onboarded",
  auditDue: "charter_audit_due",
};

// ---------------------------------------------------------------------------
// Crypto helpers (Web Crypto API — available in extensions)
// ---------------------------------------------------------------------------

async function sha256(message) {
  const encoder = new TextEncoder();
  const data = encoder.encode(message);
  const hash = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(hash))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

async function hmacSha256(key, message) {
  const encoder = new TextEncoder();
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    encoder.encode(key),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", cryptoKey, encoder.encode(message));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function generateId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// ---------------------------------------------------------------------------
// Identity
// ---------------------------------------------------------------------------

/**
 * Create a new pseudonymous identity.
 * Returns { public_id, alias, created_at }
 */
export async function createIdentity() {
  const raw = generateId();
  const public_id = await sha256(raw);
  const shortId = public_id.substring(0, 8);

  // Generate a human-friendly alias
  const adjectives = [
    "swift", "bright", "calm", "keen", "bold",
    "clear", "fair", "true", "wise", "warm",
  ];
  const nouns = [
    "node", "agent", "spark", "pulse", "core",
    "leaf", "wave", "star", "beam", "link",
  ];
  const adj = adjectives[Math.floor(Math.random() * adjectives.length)];
  const noun = nouns[Math.floor(Math.random() * nouns.length)];
  const alias = `${adj}-${noun}-${shortId.substring(0, 4)}`;

  const identity = {
    public_id,
    alias,
    created_at: new Date().toISOString(),
    source: "chrome-extension",
  };

  await chrome.storage.local.set({ [STORE.identity]: identity });
  return identity;
}

/**
 * Load existing identity, or null if none.
 */
export async function getIdentity() {
  const result = await chrome.storage.local.get([STORE.identity]);
  return result[STORE.identity] || null;
}

// ---------------------------------------------------------------------------
// Governance Config
// ---------------------------------------------------------------------------

/**
 * Initialize governance with a domain template.
 * Stores the full config in chrome.storage.local.
 */
export async function initGovernance(domain) {
  const { TEMPLATES } = await import("./templates.js");
  const template = TEMPLATES[domain];
  if (!template) {
    throw new Error(`Unknown domain: ${domain}. Valid: ${DOMAINS.join(", ")}`);
  }

  // Ensure identity exists
  let identity = await getIdentity();
  if (!identity) {
    identity = await createIdentity();
  }

  const config = {
    domain,
    version: VERSION,
    identity: {
      public_id: identity.public_id,
      alias: identity.alias,
    },
    governance: JSON.parse(JSON.stringify(template)), // deep clone
    initialized_at: new Date().toISOString(),
    source: "chrome-extension",
  };

  await chrome.storage.local.set({
    [STORE.config]: config,
    [STORE.onboarded]: true,
  });

  // Log to chain
  await appendToChain("governance_initialized", {
    domain,
    source: "chrome-extension",
    version: VERSION,
  });

  return config;
}

/**
 * Get current governance config, or null if not set up.
 */
export async function getConfig() {
  const result = await chrome.storage.local.get([STORE.config]);
  return result[STORE.config] || null;
}

/**
 * Check if user has completed onboarding.
 */
export async function isOnboarded() {
  const result = await chrome.storage.local.get([STORE.onboarded]);
  return result[STORE.onboarded] === true;
}

// ---------------------------------------------------------------------------
// Hash Chain
// ---------------------------------------------------------------------------

/**
 * Append an event to the hash chain.
 * Each entry is: { index, timestamp, event, data, prev_hash, hash }
 * The hash = HMAC-SHA256(prev_hash, timestamp + event + JSON(data))
 */
export async function appendToChain(event, data = {}) {
  const chain = await getChain();
  const index = chain.length;
  const timestamp = new Date().toISOString();
  const prevHash = index > 0 ? chain[index - 1].hash : "genesis";

  const message = `${timestamp}${event}${JSON.stringify(data)}`;
  const hash = await hmacSha256(prevHash, message);

  const entry = { index, timestamp, event, data, prev_hash: prevHash, hash };
  chain.push(entry);

  await chrome.storage.local.set({ [STORE.chain]: chain });
  return entry;
}

/**
 * Get the full chain.
 */
export async function getChain() {
  const result = await chrome.storage.local.get([STORE.chain]);
  return result[STORE.chain] || [];
}

/**
 * Verify chain integrity. Returns { intact, length, broken_at }.
 */
export async function verifyChain() {
  const chain = await getChain();

  if (chain.length === 0) {
    return { intact: true, length: 0, broken_at: null };
  }

  for (let i = 0; i < chain.length; i++) {
    const entry = chain[i];

    // Check prev_hash linkage
    const expectedPrev = i === 0 ? "genesis" : chain[i - 1].hash;
    if (entry.prev_hash !== expectedPrev) {
      return { intact: false, length: chain.length, broken_at: i };
    }

    // Verify hash
    const message = `${entry.timestamp}${entry.event}${JSON.stringify(entry.data)}`;
    const computedHash = await hmacSha256(entry.prev_hash, message);
    if (entry.hash !== computedHash) {
      return { intact: false, length: chain.length, broken_at: i };
    }
  }

  return { intact: true, length: chain.length, broken_at: null };
}

// ---------------------------------------------------------------------------
// Status (unified view)
// ---------------------------------------------------------------------------

/**
 * Get full governance status — everything the popup and badge need.
 */
export async function getStatus() {
  const identity = await getIdentity();
  const config = await getConfig();
  const chain = await getChain();
  const chainVerify = await verifyChain();
  const onboarded = await isOnboarded();

  return {
    onboarded,
    governed: !!config,
    version: VERSION,
    domain: config ? config.domain : null,
    identity: identity
      ? { alias: identity.alias, public_id: identity.public_id }
      : null,
    chain: {
      length: chain.length,
      integrity: chainVerify.intact ? "verified" : "broken",
      broken_at: chainVerify.broken_at,
      last_event: chain.length > 0 ? chain[chain.length - 1].event : null,
      last_timestamp: chain.length > 0 ? chain[chain.length - 1].timestamp : null,
    },
    governance: config
      ? {
          layer_a_count:
            (config.governance.layer_a.universal || []).length +
            (config.governance.layer_a.rules || []).length,
          layer_b_count: (config.governance.layer_b.rules || []).length,
          layer_c_frequency: config.governance.layer_c.frequency,
          kill_trigger_count: (config.governance.kill_triggers || []).length,
        }
      : null,
    source: "chrome-extension",
  };
}

// ---------------------------------------------------------------------------
// Self-Audit
// ---------------------------------------------------------------------------

/**
 * Run a self-audit. Logs the result to the chain.
 * Returns the audit report.
 */
export async function runAudit() {
  const config = await getConfig();
  if (!config) return null;

  const chain = await getChain();
  const chainVerify = await verifyChain();

  // Count events since last audit
  let lastAuditIndex = -1;
  for (let i = chain.length - 1; i >= 0; i--) {
    if (chain[i].event === "self_audit") {
      lastAuditIndex = i;
      break;
    }
  }

  const eventsSinceAudit = chain.slice(lastAuditIndex + 1);
  const eventCounts = {};
  for (const entry of eventsSinceAudit) {
    eventCounts[entry.event] = (eventCounts[entry.event] || 0) + 1;
  }

  const report = {
    timestamp: new Date().toISOString(),
    domain: config.domain,
    chain_length: chain.length,
    chain_integrity: chainVerify.intact ? "verified" : "broken",
    events_since_last_audit: eventsSinceAudit.length,
    event_breakdown: eventCounts,
    layer_a_rules: (config.governance.layer_a.universal || []).length +
      (config.governance.layer_a.rules || []).length,
    layer_b_rules: (config.governance.layer_b.rules || []).length,
    kill_triggers: (config.governance.kill_triggers || []).length,
    ethical_flags: 0,
    source: "chrome-extension-self-audit",
  };

  // Log the audit itself
  await appendToChain("self_audit", report);

  return report;
}

// ---------------------------------------------------------------------------
// Reset (for settings page)
// ---------------------------------------------------------------------------

/**
 * Clear all governance data. Returns to onboarding state.
 */
export async function resetGovernance() {
  await appendToChain("governance_reset", {
    reason: "user_initiated",
    timestamp: new Date().toISOString(),
  });

  await chrome.storage.local.remove([
    STORE.config,
    STORE.onboarded,
    STORE.auditDue,
  ]);
  // Keep identity and chain — those persist across resets
}

/**
 * Full factory reset — clears everything including identity and chain.
 */
export async function factoryReset() {
  await chrome.storage.local.remove([
    STORE.identity,
    STORE.config,
    STORE.chain,
    STORE.onboarded,
    STORE.auditDue,
  ]);
}
