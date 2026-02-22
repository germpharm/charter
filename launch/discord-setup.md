# Charter Discord Server — Setup Guide

## Step 1: Create the Server

1. Open Discord (app or discord.com)
2. Click "+" on the left sidebar → "Create My Own" → "For a community"
3. Server name: **Charter — AI Governance**
4. Upload the same green shield icon used for the VS Code extension

## Step 2: Channel Structure

### Category: START HERE
| Channel | Type | Purpose |
|---------|------|---------|
| #welcome | Text (read-only) | Auto-welcome message, rules, quick links |
| #rules | Text (read-only) | Community guidelines |
| #introductions | Text | New members introduce themselves |
| #announcements | Text (read-only, admin only) | Release notes, milestones, inflection points |

### Category: CHARTER
| Channel | Type | Purpose |
|---------|------|---------|
| #getting-started | Text | Installation help, first-time setup questions |
| #general | Text | Main discussion about Charter, governance, AI ethics |
| #bug-reports | Text | Issues that aren't GitHub-worthy yet |
| #feature-requests | Text | What people want Charter to do next |
| #show-your-governance | Text | Screenshots of GOVERNED status bars, creative charter.yaml configs |

### Category: DOMAINS
| Channel | Type | Purpose |
|---------|------|---------|
| #healthcare-hipaa | Text | Healthcare governance, HIPAA compliance |
| #finance-sox | Text | Financial governance, SOX compliance |
| #education-ferpa | Text | Education governance, FERPA compliance |
| #enterprise | Text | Large org governance challenges |

### Category: BUILD
| Channel | Type | Purpose |
|---------|------|---------|
| #contributing | Text | For people who want to contribute to Charter |
| #extension-dev | Text | VS Code extension development |
| #cli-dev | Text | Charter CLI development |

### Category: THE NETWORK
| Channel | Type | Purpose |
|---------|------|---------|
| #network-nodes | Text | People sharing their node IDs, connecting |
| #governed-projects | Text | Public projects using Charter |
| #philosophy | Text | Deeper discussion on AI governance, ethics, the thesis |

## Step 3: Welcome Message (pin in #welcome)

```
Welcome to Charter — the open-source governance layer for AI.

You're here because you believe AI should be governed by the humans who use it. So do we.

**Get started in 10 seconds:**
1. Install: Search "Charter" in VS Code Extensions
2. Open any folder
3. See GOVERNED in your status bar

**Quick links:**
- GitHub: https://github.com/germpharm/charter
- VS Code Extension: Search "Charter" in Extensions
- CLI: `pip install charter-governance`
- Website: https://germpharm.org

**Rules:**
- Be constructive. We're building something.
- No spam. No self-promotion that isn't about governance.
- Help each other. The network is the product.

Every person here strengthens the standard. Welcome.
```

## Step 4: Roles

| Role | Color | Purpose |
|------|-------|---------|
| @Founder | Gold | Matthew |
| @Core Team | Green | Anubhav, Vidhi, key contributors |
| @Contributor | Blue | Anyone who's submitted a PR |
| @Governed | White | Anyone who's installed Charter (default role) |

## Step 5: Server Settings

- Verification level: Medium (must have a verified email)
- Explicit media content filter: Scan all members
- Default notifications: Only @mentions (don't blast people)
- Community features: Enable (allows Server Discovery)
- Enable Community Server features so it can be discovered in Discord's server directory

## Step 6: Integrations

- **GitHub webhook** → #announcements: New releases, PRs merged
- **Twitter/X feed** → #announcements: Charter-related posts (use a bot like TweetShift)

## Step 7: Invite Link

Create a permanent invite link (never expires, unlimited uses):
- Server Settings → Invites → Create Invite → Set to "Never expire"
- Use this link everywhere: GitHub README, VS Code extension README, website, X bio, LinkedIn

Format: `https://discord.gg/charter` (request a vanity URL after reaching 7 boosts or use whatever Discord generates)
