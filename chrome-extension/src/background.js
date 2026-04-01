/**
 * Charter Chrome Extension — Background Service Worker (Self-Contained v3)
 *
 * No daemon. Governance engine runs entirely in the extension.
 * This service worker:
 * 1. Updates the toolbar badge based on governance state
 * 2. Runs scheduled self-audits
 * 3. Relays state to content scripts
 */

import { getStatus, isOnboarded, runAudit, getConfig } from "./governance.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AUDIT_ALARM = "charter-audit";
const BADGE_GOVERNED = { text: "GOV", color: "#22c55e" };
const BADGE_SETUP = { text: "NEW", color: "#3b82f6" };
const BADGE_NONE = { text: "", color: "#8b8fa3" };

// ---------------------------------------------------------------------------
// Installation
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === "install") {
    // First install — show NEW badge to invite setup
    chrome.action.setBadgeText({ text: BADGE_SETUP.text });
    chrome.action.setBadgeBackgroundColor({ color: BADGE_SETUP.color });
  }

  // Schedule audit check (every 6 hours)
  chrome.alarms.create(AUDIT_ALARM, { periodInMinutes: 360 });

  // Update badge based on current state
  await updateBadge();
});

// Start audit alarm on service worker wake
chrome.alarms.create(AUDIT_ALARM, { periodInMinutes: 360 });

// ---------------------------------------------------------------------------
// Alarms
// ---------------------------------------------------------------------------

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === AUDIT_ALARM) {
    await checkAndRunAudit();
  }
});

/**
 * Check if an audit is due based on the config frequency, and run it.
 */
async function checkAndRunAudit() {
  const config = await getConfig();
  if (!config) return;

  const freq = config.governance.layer_c.frequency;
  const stored = await chrome.storage.local.get(["charter_last_audit"]);
  const lastAudit = stored.charter_last_audit
    ? new Date(stored.charter_last_audit)
    : null;

  if (!lastAudit) {
    // Never audited — run now
    await runAudit();
    await chrome.storage.local.set({ charter_last_audit: new Date().toISOString() });
    return;
  }

  const now = new Date();
  const diffHours = (now - lastAudit) / (1000 * 60 * 60);

  const thresholds = { daily: 24, weekly: 168, monthly: 720 };
  const threshold = thresholds[freq] || 168;

  if (diffHours >= threshold) {
    await runAudit();
    await chrome.storage.local.set({ charter_last_audit: new Date().toISOString() });
  }
}

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message.type) {
    case "governance_initialized":
    case "status_update":
      updateBadge();
      broadcastToContentScripts();
      break;

    case "get_status":
      getStatus().then((status) => sendResponse(status));
      return true; // async

    case "settings_changed":
      updateBadge();
      break;
  }
});

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------

async function updateBadge() {
  const stored = await chrome.storage.local.get(["badgeEnabled"]);
  if (stored.badgeEnabled === false) {
    chrome.action.setBadgeText({ text: "" });
    return;
  }

  const onboarded = await isOnboarded();
  if (!onboarded) {
    chrome.action.setBadgeText({ text: BADGE_SETUP.text });
    chrome.action.setBadgeBackgroundColor({ color: BADGE_SETUP.color });
    return;
  }

  chrome.action.setBadgeText({ text: BADGE_GOVERNED.text });
  chrome.action.setBadgeBackgroundColor({ color: BADGE_GOVERNED.color });
}

// ---------------------------------------------------------------------------
// Content script broadcast
// ---------------------------------------------------------------------------

async function broadcastToContentScripts() {
  const stored = await chrome.storage.local.get(["contentScriptEnabled"]);
  if (stored.contentScriptEnabled === false) return;

  const status = await getStatus();

  try {
    const tabs = await chrome.tabs.query({
      url: [
        "https://chat.openai.com/*",
        "https://chatgpt.com/*",
        "https://claude.ai/*",
        "https://gemini.google.com/*",
        "https://copilot.microsoft.com/*",
        "https://chat.mistral.ai/*",
        "https://poe.com/*",
      ],
    });

    for (const tab of tabs) {
      try {
        await chrome.tabs.sendMessage(tab.id, {
          type: "governance_state",
          data: status,
        });
      } catch {
        // Content script not loaded yet
      }
    }
  } catch {
    // No matching tabs
  }
}
