/**
 * Charter Chrome Extension — Options Page (Self-Contained v3)
 *
 * No daemon settings. Governance runs locally.
 * Manages: display preferences, domain change, export, reset.
 */

import {
  getStatus,
  getChain,
  getConfig,
  initGovernance,
  resetGovernance,
  factoryReset,
} from "../src/governance.js";

// ---------------------------------------------------------------------------
// DOM
// ---------------------------------------------------------------------------

const els = {
  govStatus: document.getElementById("gov-status"),
  govDomain: document.getElementById("gov-domain"),
  govIdentity: document.getElementById("gov-identity"),
  govChain: document.getElementById("gov-chain"),
  domainSelect: document.getElementById("domain-select"),
  btnChangeDomain: document.getElementById("btn-change-domain"),
  badgeEnabled: document.getElementById("badge-enabled"),
  contentScriptEnabled: document.getElementById("content-script-enabled"),
  btnExport: document.getElementById("btn-export"),
  btnReset: document.getElementById("btn-reset"),
  btnFactoryReset: document.getElementById("btn-factory-reset"),
  btnSave: document.getElementById("btn-save"),
  saveStatus: document.getElementById("save-status"),
};

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", async () => {
  await loadStatus();
  await loadDisplaySettings();

  els.btnSave.addEventListener("click", saveSettings);
  els.btnChangeDomain.addEventListener("click", changeDomain);
  els.btnExport.addEventListener("click", exportChain);
  els.btnReset.addEventListener("click", handleReset);
  els.btnFactoryReset.addEventListener("click", handleFactoryReset);
});

// ---------------------------------------------------------------------------
// Load current state
// ---------------------------------------------------------------------------

async function loadStatus() {
  const status = await getStatus();

  if (status.governed) {
    els.govStatus.textContent = "Governed";
    els.govStatus.style.color = "#22c55e";
  } else if (status.onboarded) {
    els.govStatus.textContent = "Resetting...";
    els.govStatus.style.color = "#eab308";
  } else {
    els.govStatus.textContent = "Not set up";
    els.govStatus.style.color = "#8b8fa3";
  }

  els.govDomain.textContent = status.domain
    ? status.domain.charAt(0).toUpperCase() + status.domain.slice(1)
    : "—";

  els.govIdentity.textContent = status.identity
    ? status.identity.alias
    : "—";

  els.govChain.textContent = status.chain
    ? `${status.chain.length} entries (${status.chain.integrity})`
    : "—";
}

async function loadDisplaySettings() {
  const result = await chrome.storage.local.get([
    "badgeEnabled",
    "contentScriptEnabled",
  ]);
  els.badgeEnabled.checked = result.badgeEnabled !== false;
  els.contentScriptEnabled.checked = result.contentScriptEnabled !== false;
}

// ---------------------------------------------------------------------------
// Save display settings
// ---------------------------------------------------------------------------

function saveSettings() {
  const settings = {
    badgeEnabled: els.badgeEnabled.checked,
    contentScriptEnabled: els.contentScriptEnabled.checked,
  };

  chrome.storage.local.set(settings, () => {
    els.saveStatus.textContent = "Saved";
    els.saveStatus.classList.add("visible");
    setTimeout(() => els.saveStatus.classList.remove("visible"), 2000);

    chrome.runtime.sendMessage({ type: "settings_changed", settings });
  });
}

// ---------------------------------------------------------------------------
// Change domain
// ---------------------------------------------------------------------------

async function changeDomain() {
  const domain = els.domainSelect.value;
  if (!domain) return;

  if (!confirm(`Change governance domain to "${domain}"? Your rules will be reset, but your identity and audit chain are preserved.`)) {
    return;
  }

  els.btnChangeDomain.disabled = true;
  els.btnChangeDomain.textContent = "Changing...";

  await resetGovernance();
  await initGovernance(domain);

  els.btnChangeDomain.disabled = false;
  els.btnChangeDomain.textContent = "Change Domain";
  els.domainSelect.value = "";

  await loadStatus();
  chrome.runtime.sendMessage({ type: "settings_changed" });
}

// ---------------------------------------------------------------------------
// Export chain
// ---------------------------------------------------------------------------

async function exportChain() {
  const chain = await getChain();
  const blob = new Blob([JSON.stringify(chain, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);

  const a = document.createElement("a");
  a.href = url;
  a.download = `charter-chain-${new Date().toISOString().split("T")[0]}.json`;
  a.click();

  URL.revokeObjectURL(url);
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

async function handleReset() {
  if (!confirm("Reset governance? You will re-enter onboarding. Your identity and chain are preserved.")) {
    return;
  }

  await resetGovernance();
  await loadStatus();
  chrome.runtime.sendMessage({ type: "settings_changed" });
}

async function handleFactoryReset() {
  if (!confirm("Delete ALL Charter data from this browser? This cannot be undone.")) {
    return;
  }
  if (!confirm("Are you sure? Your identity, audit chain, and all governance data will be permanently deleted.")) {
    return;
  }

  await factoryReset();
  await loadStatus();
  chrome.runtime.sendMessage({ type: "settings_changed" });
}
