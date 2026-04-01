// === BUNDLED FOR SAFARI ===

/**
 * Charter Domain Templates — identical to Python/TypeScript versions.
 *
 * Five domains: general, healthcare, finance, education, personal.
 * Each template defines Layer A (hard constraints), Layer B (gradient decisions),
 * Layer C (self-audit), and kill triggers.
 */

const TEMPLATES = {
  // -------------------------------------------------------------------------
  general: {
    layer_a: {
      description: "Hard constraints. The system will never do these.",
      universal: [
        "Never violate applicable law in the jurisdiction where this system operates",
        "Never fabricate data, citations, or evidence",
        "Never conceal, alter, or destroy the audit trail",
        "Never impersonate a real person",
      ],
      rules: [
        "Never send external communications without human approval",
        "Never access financial accounts without explicit authorization",
        "Never delete data without human confirmation",
      ],
    },
    layer_b: {
      description: "Gradient decisions. These require human judgment above thresholds.",
      rules: [
        {
          action: "financial_transaction",
          threshold: "always",
          requires: "human_approval",
          description: "All spending requires human approval",
        },
        {
          action: "external_communication",
          threshold: "always",
          requires: "human_approval",
          description: "All outbound messages require human review before sending",
        },
        {
          action: "data_access",
          threshold: "sensitive",
          requires: "human_review",
          description: "Access to sensitive data requires human awareness",
        },
        {
          action: "code_deployment",
          threshold: "production",
          requires: "human_approval",
          description: "Production deployments require human authorization",
        },
      ],
    },
    layer_c: {
      description: "Self-audit. The system reviews itself and reports what it did and why.",
      frequency: "weekly",
      report_includes: [
        "decisions_made",
        "rules_applied",
        "escalations_to_human",
        "ethical_flags",
      ],
    },
    kill_triggers: [
      {
        trigger: "ethical_gradient_acceleration",
        description: "Ethics compliance declining across sessions",
      },
      {
        trigger: "audit_friction",
        description: "Audit process being bypassed or delayed",
      },
      {
        trigger: "conscience_conflict",
        description: "System flags internal conflict between instruction and ethics",
      },
    ],
  },

  // -------------------------------------------------------------------------
  healthcare: {
    layer_a: {
      description: "Hard constraints. The system will never do these.",
      universal: [
        "Never violate applicable law in the jurisdiction where this system operates",
        "Never fabricate data, citations, or evidence",
        "Never conceal, alter, or destroy the audit trail",
        "Never impersonate a real person",
      ],
      rules: [
        "Never disclose patient health information without explicit consent",
        "Never make clinical decisions without human review",
        "Never send external communications without human approval",
        "Never access financial accounts without explicit authorization",
        "Never bypass medication safety checks",
      ],
    },
    layer_b: {
      description: "Gradient decisions. These require human judgment above thresholds.",
      rules: [
        {
          action: "financial_transaction",
          threshold: "always",
          requires: "human_approval",
          description: "All spending requires human approval",
        },
        {
          action: "external_communication",
          threshold: "always",
          requires: "human_approval",
          description: "All outbound messages require human review before sending",
        },
        {
          action: "data_access",
          threshold: "sensitive",
          requires: "human_review",
          description: "Access to sensitive data requires human awareness",
        },
        {
          action: "clinical_recommendation",
          threshold: "always",
          requires: "human_approval",
          description: "All clinical recommendations require licensed provider review",
        },
        {
          action: "code_deployment",
          threshold: "production",
          requires: "human_approval",
          description: "Production deployments require human authorization",
        },
      ],
    },
    layer_c: {
      description: "Self-audit. The system reviews itself and reports what it did and why.",
      frequency: "weekly",
      report_includes: [
        "decisions_made",
        "rules_applied",
        "escalations_to_human",
        "ethical_flags",
        "data_accessed",
        "external_communications",
      ],
    },
    kill_triggers: [
      {
        trigger: "ethical_gradient_acceleration",
        description: "Ethics compliance declining across sessions",
      },
      {
        trigger: "audit_friction",
        description: "Audit process being bypassed or delayed",
      },
      {
        trigger: "conscience_conflict",
        description: "System flags internal conflict between instruction and ethics",
      },
    ],
  },

  // -------------------------------------------------------------------------
  finance: {
    layer_a: {
      description: "Hard constraints. The system will never do these.",
      universal: [
        "Never violate applicable law in the jurisdiction where this system operates",
        "Never fabricate data, citations, or evidence",
        "Never conceal, alter, or destroy the audit trail",
        "Never impersonate a real person",
      ],
      rules: [
        "Never execute trades without human authorization",
        "Never send external communications without human approval",
        "Never access client accounts without explicit authorization",
        "Never bypass compliance checks or regulatory requirements",
        "Never share client financial information with unauthorized parties",
        "Never provide specific investment advice without licensed advisor review",
      ],
    },
    layer_b: {
      description: "Gradient decisions. These require human judgment above thresholds.",
      rules: [
        {
          action: "financial_transaction",
          threshold: "always",
          requires: "human_approval",
          description: "All spending requires human approval",
        },
        {
          action: "external_communication",
          threshold: "always",
          requires: "human_approval",
          description:
            "All outbound messages to clients or regulators require review",
        },
        {
          action: "data_access",
          threshold: "client_data",
          requires: "human_review",
          description: "Client data access requires human awareness",
        },
        {
          action: "report_generation",
          threshold: "external",
          requires: "human_approval",
          description: "Reports shared externally require human review",
        },
      ],
    },
    layer_c: {
      description: "Self-audit. The system reviews itself and reports what it did and why.",
      frequency: "daily",
      report_includes: [
        "decisions_made",
        "rules_applied",
        "escalations_to_human",
        "ethical_flags",
        "transactions_processed",
        "client_data_accessed",
        "compliance_checks",
      ],
    },
    kill_triggers: [
      {
        trigger: "ethical_gradient_acceleration",
        description: "Ethics compliance declining across sessions",
      },
      {
        trigger: "audit_friction",
        description: "Audit process being bypassed or delayed",
      },
      {
        trigger: "conscience_conflict",
        description: "System flags internal conflict between instruction and ethics",
      },
      {
        trigger: "compliance_deviation",
        description: "Actions deviating from regulatory requirements",
      },
    ],
  },

  // -------------------------------------------------------------------------
  education: {
    layer_a: {
      description: "Hard constraints. The system will never do these.",
      universal: [
        "Never violate applicable law in the jurisdiction where this system operates",
        "Never fabricate data, citations, or evidence",
        "Never conceal, alter, or destroy the audit trail",
        "Never impersonate a real person",
      ],
      rules: [
        "Never disclose student records without authorization (FERPA)",
        "Never complete assignments on behalf of students without instructor approval",
        "Never send external communications without human approval",
        "Never bypass accessibility requirements",
        "Never collect student data beyond what is educationally necessary",
      ],
    },
    layer_b: {
      description: "Gradient decisions. These require human judgment above thresholds.",
      rules: [
        {
          action: "student_assessment",
          threshold: "always",
          requires: "instructor_review",
          description: "All grading and assessment requires instructor oversight",
        },
        {
          action: "external_communication",
          threshold: "always",
          requires: "human_approval",
          description: "All outbound messages require human review",
        },
        {
          action: "content_generation",
          threshold: "curriculum",
          requires: "instructor_review",
          description: "Curriculum content requires instructor approval",
        },
        {
          action: "student_data_access",
          threshold: "always",
          requires: "human_review",
          description: "Student data access requires human awareness",
        },
      ],
    },
    layer_c: {
      description: "Self-audit. The system reviews itself and reports what it did and why.",
      frequency: "weekly",
      report_includes: [
        "decisions_made",
        "rules_applied",
        "escalations_to_human",
        "ethical_flags",
        "student_data_accessed",
        "content_generated",
      ],
    },
    kill_triggers: [
      {
        trigger: "ethical_gradient_acceleration",
        description: "Ethics compliance declining across sessions",
      },
      {
        trigger: "audit_friction",
        description: "Audit process being bypassed or delayed",
      },
      {
        trigger: "conscience_conflict",
        description: "System flags internal conflict between instruction and ethics",
      },
    ],
  },

  // -------------------------------------------------------------------------
  personal: {
    layer_a: {
      description: "Hard constraints. Your AI will never do these.",
      universal: [
        "You will never break the law where you operate",
        "You will never fabricate data, citations, or evidence",
        "You will never hide, alter, or destroy your audit trail",
        "You will never impersonate a real person",
      ],
      rules: [
        "You will never send messages on your behalf without your approval",
        "You will never access your financial accounts without your explicit say-so",
        "You will never delete your data without your confirmation",
      ],
    },
    layer_b: {
      description: "Gradient decisions. These need your judgment.",
      rules: [
        {
          action: "spending",
          threshold: "always",
          requires: "your_approval",
          description: "Any spending requires your approval first",
        },
        {
          action: "outbound_messages",
          threshold: "always",
          requires: "your_approval",
          description:
            "Any message sent on your behalf needs your review first",
        },
        {
          action: "personal_data",
          threshold: "sensitive",
          requires: "your_awareness",
          description: "Accessing your sensitive data requires your awareness",
        },
        {
          action: "publishing",
          threshold: "public",
          requires: "your_approval",
          description: "Anything published publicly requires your authorization",
        },
      ],
    },
    layer_c: {
      description: "Self-audit. Your AI reviews itself and reports what it did and why.",
      frequency: "weekly",
      report_includes: [
        "decisions_made",
        "rules_applied",
        "escalations_to_you",
        "ethical_flags",
      ],
    },
    kill_triggers: [
      {
        trigger: "ethical_drift",
        description: "Your AI is following your rules less closely over time",
      },
      {
        trigger: "audit_avoidance",
        description: "The audit process is being skipped or delayed",
      },
      {
        trigger: "conscience_conflict",
        description:
          "Your AI flags a conflict between what it was told and what is right",
      },
    ],
  },
};

/**
 * Human-friendly domain labels for the onboarding UI.
 */
const DOMAIN_INFO = {
  personal: {
    label: "Personal",
    emoji: "person",
    description: "For your personal AI assistant. Plain language rules.",
    color: "#3b82f6",
  },
  general: {
    label: "General",
    emoji: "briefcase",
    description: "For work projects. Standard professional governance.",
    color: "#22c55e",
  },
  healthcare: {
    label: "Healthcare",
    emoji: "health",
    description: "HIPAA-aware. Patient privacy, clinical safety checks.",
    color: "#ef4444",
  },
  finance: {
    label: "Finance",
    emoji: "finance",
    description: "Compliance-first. Trade authorization, client data protection.",
    color: "#f59e0b",
  },
  education: {
    label: "Education",
    emoji: "education",
    description: "FERPA-compliant. Student privacy, academic integrity.",
    color: "#a78bfa",
  },
};


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

const VERSION = "3.0.0";

const DOMAINS = ["general", "healthcare", "finance", "education", "personal"];

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
async function createIdentity() {
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
async function getIdentity() {
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
async function initGovernance(domain) {
  // Templates are inlined above
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
async function getConfig() {
  const result = await chrome.storage.local.get([STORE.config]);
  return result[STORE.config] || null;
}

/**
 * Check if user has completed onboarding.
 */
async function isOnboarded() {
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
async function appendToChain(event, data = {}) {
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
async function getChain() {
  const result = await chrome.storage.local.get([STORE.chain]);
  return result[STORE.chain] || [];
}

/**
 * Verify chain integrity. Returns { intact, length, broken_at }.
 */
async function verifyChain() {
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
async function getStatus() {
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
async function runAudit() {
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
async function resetGovernance() {
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
async function factoryReset() {
  await chrome.storage.local.remove([
    STORE.identity,
    STORE.config,
    STORE.chain,
    STORE.onboarded,
    STORE.auditDue,
  ]);
}


// === POPUP ===

/**
 * Charter Chrome Extension — Popup Script (Self-Contained v3)
 *
 * No daemon. No CLI. No terminal.
 * All governance runs inside the extension via chrome.storage.local.
 *
 * Screens:
 *   1. Onboarding — pick your domain (shown once)
 *   2. Setup spinner — brief animation while governance initializes
 *   3. Dashboard — daily view (governance status, events, actions)
 *   4. Rules — view your governance rules
 */


// ---------------------------------------------------------------------------
// Screens
// ---------------------------------------------------------------------------

const screens = {
  onboarding: document.getElementById("screen-onboarding"),
  setup: document.getElementById("screen-setup"),
  dashboard: document.getElementById("screen-dashboard"),
  rules: document.getElementById("screen-rules"),
};

function showScreen(name) {
  for (const [key, el] of Object.entries(screens)) {
    el.style.display = key === name ? "" : "none";
  }
}

// ---------------------------------------------------------------------------
// Initialization
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  const onboarded = await isOnboarded();

  if (onboarded) {
    showScreen("dashboard");
    await refreshDashboard();
  } else {
    showScreen("onboarding");
    wireOnboarding();
  }

  // Wire dashboard buttons
  document.getElementById("btn-audit").addEventListener("click", handleAudit);
  document.getElementById("btn-rules").addEventListener("click", handleShowRules);
  document.getElementById("btn-settings").addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
  });
  document.getElementById("btn-back-rules").addEventListener("click", () => {
    showScreen("dashboard");
  });
});

// ---------------------------------------------------------------------------
// Onboarding
// ---------------------------------------------------------------------------

function wireOnboarding() {
  const cards = document.querySelectorAll(".domain-card");
  for (const card of cards) {
    card.addEventListener("click", async () => {
      const domain = card.dataset.domain;
      await startGovernance(domain);
    });
  }
}

async function startGovernance(domain) {
  showScreen("setup");

  try {
    await initGovernance(domain);

    // Brief pause so the spinner feels intentional
    await new Promise((r) => setTimeout(r, 800));

    // Notify background to update badge
    const status = await getStatus();
    chrome.runtime.sendMessage({ type: "governance_initialized", status });

    showScreen("dashboard");
    await refreshDashboard();
  } catch (err) {
    // Show error in setup screen
    document.querySelector(".setup-text").textContent =
      `Error: ${err.message}. Please try again.`;
  }
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

async function refreshDashboard() {
  const status = await getStatus();
  const chain = await getChain();

  // Status badge
  const badge = document.getElementById("status-badge");
  badge.textContent = "Governed";
  badge.className = "badge badge-governed";

  // Identity bar
  document.getElementById("identity-alias").textContent =
    status.identity ? status.identity.alias : "—";
  document.getElementById("identity-domain").textContent =
    status.domain ? capitalize(status.domain) : "—";

  // Stats
  document.getElementById("rule-count").textContent =
    status.governance ? status.governance.layer_a_count + status.governance.layer_b_count : "—";
  document.getElementById("chain-length").textContent =
    `${status.chain.length}`;

  const intEl = document.getElementById("chain-integrity");
  if (status.chain.integrity === "verified") {
    intEl.textContent = "Verified";
    intEl.className = "stat-value good";
  } else {
    intEl.textContent = "Broken";
    intEl.className = "stat-value bad";
  }

  document.getElementById("audit-freq").textContent =
    status.governance ? capitalize(status.governance.layer_c_frequency) : "—";

  // Footer identity
  document.getElementById("footer-id").textContent =
    status.identity ? status.identity.public_id.substring(0, 12) : "";

  // Events
  renderEvents(chain);

  // Update background badge
  chrome.runtime.sendMessage({ type: "status_update", status });
}

function renderEvents(chain) {
  const list = document.getElementById("events-list");

  if (!chain || chain.length === 0) {
    list.innerHTML = '<div class="event-empty">No events yet</div>';
    return;
  }

  list.innerHTML = "";
  const recent = chain.slice(-5).reverse();

  for (const entry of recent) {
    const row = document.createElement("div");
    row.className = "event-row";

    const typeSpan = document.createElement("span");
    typeSpan.className = `event-type ${getEventTypeClass(entry.event)}`;
    typeSpan.textContent = formatEventType(entry.event);

    const timeSpan = document.createElement("span");
    timeSpan.className = "event-time";
    timeSpan.textContent = formatTime(entry.timestamp);

    row.appendChild(typeSpan);
    row.appendChild(timeSpan);
    list.appendChild(row);
  }
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------

async function handleAudit() {
  const btn = document.getElementById("btn-audit");
  btn.disabled = true;
  btn.textContent = "Running...";

  const report = await runAudit();

  btn.textContent = "Done!";
  setTimeout(() => {
    btn.disabled = false;
    btn.textContent = "\u{1F4CB} Audit";
  }, 1500);

  // Refresh to show new chain entry
  await refreshDashboard();
}

// ---------------------------------------------------------------------------
// Rules Viewer
// ---------------------------------------------------------------------------

async function handleShowRules() {
  const config = await getConfig();
  if (!config) return;

  showScreen("rules");

  // Domain badge
  const domainBadge = document.getElementById("rules-domain-badge");
  domainBadge.textContent = capitalize(config.domain);

  const container = document.getElementById("rules-content");
  container.innerHTML = "";

  const gov = config.governance;

  // Layer A — Universal
  addRulesSection(container, "Layer A — Universal", gov.layer_a.universal);

  // Layer A — Domain Rules
  addRulesSection(container, `Layer A — ${capitalize(config.domain)} Rules`, gov.layer_a.rules);

  // Layer B — Gradient Decisions
  const layerBItems = gov.layer_b.rules.map((r) => {
    const meta = `${r.threshold} → ${r.requires}`;
    return { text: r.description, meta };
  });
  addRulesSectionWithMeta(container, "Layer B — Gradient Decisions", layerBItems);

  // Layer C
  addRulesSection(container, "Layer C — Self-Audit", [
    `Frequency: ${gov.layer_c.frequency}`,
    `Reports: ${gov.layer_c.report_includes.join(", ")}`,
  ]);

  // Kill Triggers
  const killItems = gov.kill_triggers.map((t) => t.description);
  addRulesSection(container, "Kill Triggers", killItems, true);
}

function addRulesSection(container, title, items, isKill = false) {
  const section = document.createElement("div");
  section.className = "rules-section";

  const h = document.createElement("div");
  h.className = "rules-section-title";
  h.textContent = title;
  section.appendChild(h);

  for (const item of items) {
    const div = document.createElement("div");
    div.className = `rule-item${isKill ? " kill" : ""}`;
    div.textContent = item;
    section.appendChild(div);
  }

  container.appendChild(section);
}

function addRulesSectionWithMeta(container, title, items) {
  const section = document.createElement("div");
  section.className = "rules-section";

  const h = document.createElement("div");
  h.className = "rules-section-title";
  h.textContent = title;
  section.appendChild(h);

  for (const item of items) {
    const div = document.createElement("div");
    div.className = "rule-item";
    div.textContent = item.text;

    const meta = document.createElement("div");
    meta.className = "rule-meta";
    meta.textContent = item.meta;
    div.appendChild(meta);

    section.appendChild(div);
  }

  container.appendChild(section);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function capitalize(str) {
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function formatEventType(type) {
  return type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function getEventTypeClass(type) {
  if (type.includes("identity")) return "event-type-identity";
  if (type.includes("governance") || type.includes("initialized")) return "event-type-governance";
  if (type.includes("audit")) return "event-type-audit";
  return "event-type-governance";
}

function formatTime(timestamp) {
  if (!timestamp) return "";
  try {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMin = Math.floor(diffMs / 60000);
    const diffHr = Math.floor(diffMs / 3600000);
    const diffDay = Math.floor(diffMs / 86400000);

    if (diffMin < 1) return "just now";
    if (diffMin < 60) return `${diffMin}m ago`;
    if (diffHr < 24) return `${diffHr}h ago`;
    if (diffDay < 7) return `${diffDay}d ago`;
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}
