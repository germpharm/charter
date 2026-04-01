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

import {
  isOnboarded,
  initGovernance,
  getStatus,
  getChain,
  runAudit,
  getConfig,
} from "../src/governance.js";

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
