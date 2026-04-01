/**
 * Charter Chrome Extension — Content Script (Badge)
 * Self-contained v3 — reads from chrome.storage.local, no daemon needed.
 *
 * Injects a subtle governance indicator badge into AI chat pages.
 * Non-intrusive, minimizable, adapts to light/dark themes.
 */

(function charterBadgeInit() {
  "use strict";

  if (document.getElementById("charter-governance-badge")) return;

  let governanceState = null;
  let minimized = false;

  function createBadge() {
    const badge = document.createElement("div");
    badge.id = "charter-governance-badge";
    badge.className = "charter-offline charter-animate-in";

    const diamond = document.createElement("span");
    diamond.className = "charter-diamond";
    diamond.textContent = "\u25C6";
    badge.appendChild(diamond);

    const label = document.createElement("span");
    label.className = "charter-label";
    label.textContent = "Charter";
    badge.appendChild(label);

    const tooltip = document.createElement("div");
    tooltip.id = "charter-governance-tooltip";

    badge.addEventListener("dblclick", (e) => {
      e.preventDefault();
      minimized = !minimized;
      badge.classList.toggle("charter-minimized", minimized);
      chrome.storage.local.set({ badgeMinimized: minimized });
    });

    document.body.appendChild(badge);
    document.body.appendChild(tooltip);

    return { badge, label, tooltip };
  }

  function updateBadge(elements, data) {
    const { badge, label, tooltip } = elements;

    if (!data || !data.governed) {
      // Not yet onboarded — show nothing (don't confuse the user)
      if (!data || !data.onboarded) {
        badge.style.display = "none";
        return;
      }
      badge.style.display = "";
      badge.className = "charter-ungoverned";
      label.textContent = "Ungoverned";
    } else {
      badge.style.display = "";
      badge.className = "charter-governed";
      label.textContent = "Governed";
    }

    if (minimized) badge.classList.add("charter-minimized");
    updateTooltip(tooltip, data);
  }

  function updateTooltip(tooltip, data) {
    if (!data || !data.governed) {
      tooltip.innerHTML = '<div class="tooltip-row"><span class="tooltip-label">Click the Charter icon to set up</span></div>';
      return;
    }

    const domain = data.domain || "general";
    const identity = (data.identity && data.identity.alias) || "Unknown";
    const chainLen = data.chain ? data.chain.length : 0;
    const intact = data.chain && data.chain.integrity === "verified";

    tooltip.innerHTML = [
      '<div class="tooltip-row">',
      '  <span class="tooltip-label">Domain</span>',
      `  <span class="tooltip-value">${domain.charAt(0).toUpperCase() + domain.slice(1)}</span>`,
      "</div>",
      '<div class="tooltip-row">',
      '  <span class="tooltip-label">Identity</span>',
      `  <span class="tooltip-value">${escapeHtml(identity)}</span>`,
      "</div>",
      '<div class="tooltip-row">',
      '  <span class="tooltip-label">Chain</span>',
      `  <span class="tooltip-value">${chainLen} entries</span>`,
      "</div>",
      '<div class="tooltip-row">',
      '  <span class="tooltip-label">Integrity</span>',
      `  <span class="tooltip-value ${intact ? "good" : "warn"}">${intact ? "Verified" : "Unknown"}</span>`,
      "</div>",
    ].join("");
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  let elements = null;

  // Listen for state updates from background
  chrome.runtime.onMessage.addListener((message) => {
    if (message.type === "governance_state") {
      governanceState = message.data;
      if (elements) updateBadge(elements, governanceState);
    }
  });

  function init() {
    if (!document.body) {
      document.addEventListener("DOMContentLoaded", init);
      return;
    }

    chrome.storage.local.get(["badgeMinimized", "contentScriptEnabled"], (result) => {
      if (result.contentScriptEnabled === false) return;

      minimized = result.badgeMinimized || false;
      elements = createBadge();
      if (minimized) elements.badge.classList.add("charter-minimized");

      // Request current status from background
      chrome.runtime.sendMessage({ type: "get_status" }, (response) => {
        if (chrome.runtime.lastError) return;
        if (response) {
          governanceState = response;
          updateBadge(elements, governanceState);
        }
      });
    });
  }

  init();
})();
