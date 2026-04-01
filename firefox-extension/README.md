# Charter Governance — Chrome Extension

AI governance for everyone. No terminal required.

## What It Does

- **Toolbar badge** — Shows your governance status (GOV/PRO/ENT) right on the Chrome toolbar
- **Popup dashboard** — Click the icon to see governance state, identity, chain integrity, and recent events
- **Page badge** — Subtle indicator on AI chat pages (ChatGPT, Claude, Gemini, Copilot, Mistral, Poe)
- **License management** — Activate Pro/Enterprise keys from the settings page
- **One-click dashboard** — Jump to the full Charter dashboard in one click

## Install (Developer Mode)

1. Open Chrome and navigate to `chrome://extensions`
2. Enable **Developer mode** (toggle in top-right)
3. Click **Load unpacked**
4. Select this `chrome-extension/` folder
5. The Charter diamond icon appears in your toolbar

## Install (Chrome Web Store)

Coming soon.

## Prerequisites

The extension communicates with the Charter daemon running on your machine:

```bash
pip install charter-governance
charter bootstrap
charter daemon
```

The daemon runs at `http://localhost:8374` by default. You can change this in the extension settings.

## Supported AI Chat Pages

The extension injects a governance badge on:
- [ChatGPT](https://chatgpt.com)
- [Claude](https://claude.ai)
- [Gemini](https://gemini.google.com)
- [Microsoft Copilot](https://copilot.microsoft.com)
- [Mistral](https://chat.mistral.ai)
- [Poe](https://poe.com)

## Settings

Click the gear icon in the popup, or right-click the extension icon > Options:
- **Daemon URL** — Point to a different daemon (e.g., remote server)
- **Toolbar Badge** — Show/hide the GOV badge on the extension icon
- **Page Badge** — Show/hide the governance indicator on AI chat pages
- **License Key** — Activate Pro or Enterprise features

## Architecture

```
chrome-extension/
├── manifest.json          # Manifest V3 configuration
├── src/
│   └── background.js      # Service worker — polls daemon, updates badge
├── popup/
│   ├── popup.html         # Popup UI
│   ├── popup.css          # Dark theme styles
│   └── popup.js           # Fetch and render governance status
├── content/
│   ├── badge.css          # Injected badge styles
│   └── badge.js           # Injected badge script
├── options/
│   ├── options.html       # Settings page
│   ├── options.css        # Settings styles
│   └── options.js         # Settings logic
└── icons/
    ├── icon-16.png        # Toolbar icon
    ├── icon-32.png
    ├── icon-48.png
    └── icon-128.png       # Chrome Web Store icon
```

Zero npm dependencies. Zero build step. Pure browser APIs.

## Version

3.0.0 — Matches Charter CLI and VS Code Extension.
