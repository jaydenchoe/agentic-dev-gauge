# Cheliped Browser & Claude.ai Usage Page Investigation Report
**Date:** 2026-03-29

---

## Part 1: Cheliped Browser Repository Analysis

### 1. What is Cheliped Browser?

Cheliped is a **specialized browser automation tool designed for AI agents**, created by Kyungpil Lim (tykimos). It's optimized for LLM reasoning and token efficiency rather than general-purpose automation.

**GitHub:** https://github.com/tykimos/cheliped-browser

**Core Innovation:** "Agent DOM" — a compressed, semantically-structured representation of web pages where interactive elements receive numeric IDs instead of CSS selectors. This is designed to minimize token usage in LLM contexts.

### 2. Browser Automation Tool: Which Framework?

**Tool Used:** Chrome DevTools Protocol (CDP) - **NOT Playwright, Puppeteer, or Selenium**

- Direct CDP WebSocket connection ("no framework overhead")
- Lightweight compared to Playwright/Puppeteer
- Controls Chrome directly via protocol
- Machine-readable JSON output

### 3. Python Support

**⚠️ NOT SUPPORTED**

- Cheliped is **Node.js/JavaScript only** (requires Node.js ≥ 20)
- Installation uses npm/npm scripts
- CLI invocation via Node.js
- If Python integration is needed, would require spawning Node.js processes or using subprocess wrapper

### 4. Browser Session Reuse (Cookies/Profiles)

**Partially Supported:**

| Feature | Support | Details |
|---------|---------|---------|
| **Cookie Persistence** | ✅ Yes | Dedicated `session/` module for cookie persistence |
| **Session Isolation** | ✅ Yes | `--session` flag allows multiple isolated Chrome instances |
| **Same Browser Instance** | ✅ Yes | Chrome stays alive between CLI calls within same session |
| **User Data Directory** | ✅ Yes | Sessions use isolated user data directories |
| **Pre-existing Credentials** | ⚠️ Partial | Sessions start fresh unless manually loaded via cookies or `run-js` commands |
| **User Profile Support** | ❌ No | No explicit user profile or persistent login management documented |

**How it works:**
- Each agent can have its own Chrome instance via `--session` flag
- Same browser session persists across multiple Claude Code turns (goto → observe → click workflow)
- Cookies can be managed through the session module

### 5. Headless Mode Support

**✅ Fully Supported (Default)**

- Runs in headless mode by default
- Chrome operates without visual display
- Can disable with `headless: false` if needed (e.g., for bot detection bypass on Amazon, Booking.com)
- Suitable for CI/CD and server environments

### 6. Installation Methods

#### Option A: As Claude Code Skill
```bash
git clone https://github.com/tykimos/cheliped-browser.git ~/.claude/skills/cheliped-browser
cd ~/.claude/skills/cheliped-browser/scripts
npm install && npm run build
```

#### Option B: As OpenClaw Skill
```bash
git clone https://github.com/tykimos/cheliped-browser.git ~/.openclaw/skills/cheliped-browser
cd ~/.openclaw/skills/cheliped-browser/scripts
npm install && npm run build
```

#### Option C: Standalone Tool
```bash
git clone https://github.com/tykimos/cheliped-browser.git
cd cheliped-browser/scripts
npm install && npm run build
node cheliped-cli.mjs '[{"cmd":"goto","args":["https://example.com"]},{"cmd":"observe"}]'
```

**Requirements:**
- Node.js ≥ 20
- Chrome/Chromium browser (CDP protocol)
- npm or yarn for dependency management

### 7. Key Features & Commands

**Core Commands:**
- `goto [url]` — Navigate to page
- `observe` — Extract Agent DOM representation
- `click [agentId]` — Click element by numeric ID
- `fill [agentId] [text]` — Fill input fields
- `select [agentId] [value]` — Select dropdown values
- `screenshot` — Capture page image
- `wait [ms]` — Pause execution

**Token Efficiency:**
- Averages **1,932 tokens per page**
- Compares to 5,000-12,000 tokens for Playwright/Puppeteer approaches
- ~130K token HTML → ~2.5K tokens via Agent DOM

### 8. Limitations

- ❌ Cross-origin iframe content not accessible (same-origin iframe/shadow DOM support only)
- ⚠️ Basic Single Page Application (SPA) support compared to Playwright's "excellent" handling
- ⚠️ Early production maturity (v1.x stage)
- ⚠️ Manual wait strategies needed in some cases
- ❌ Python integration requires subprocess wrapper

---

## Part 2: Claude.ai Usage Page Investigation

### URL Structure & Accessibility

**Attempted URLs:**
- `https://claude.ai/settings` — ❌ 403 Forbidden (Requires Authentication)
- `https://claude.ai/settings/usage` — ❌ 403 Forbidden (Requires Authentication)

**Findings:**

1. **Authentication Required**: All settings pages require user authentication
   - Claude.ai uses session-based authentication
   - Cookie/token validation enforced at the server level
   - Public WebFetch access is blocked

2. **Expected Structure** (Based on typical SaaS patterns):
   - `/settings` — General settings dashboard
   - `/settings/usage` — Usage/billing analytics (likely exists but authenticated)
   - `/settings/account` — Account management
   - `/settings/billing` — Billing information

3. **Private Page Detection**:
   - HTTP 403 indicates the page exists but is access-restricted
   - Not a 404 (not found), confirming the URL structure is valid
   - Standard authentication gate for protected resources

### Implementation Implications for Tiny Monitor

If the goal is to integrate Claude.ai usage data:

| Approach | Feasibility | Notes |
|----------|-------------|-------|
| **WebFetch public pages** | ❌ Not possible | All settings pages authenticated |
| **Claude API usage metrics** | ✅ Recommended | Use `anthropic.billing.usage()` API method |
| **Browser automation (Cheliped)** | ⚠️ Possible but fragile | Could automate login + navigate to usage page, but requires credential management |
| **Direct API integration** | ✅ Best approach | Use Anthropic SDK to fetch usage via official API |

---

## Summary Table

| Aspect | Result | Notes |
|--------|--------|-------|
| **Tool Type** | Chrome DevTools Protocol (CDP) | Not Playwright/Puppeteer/Selenium |
| **Language** | Node.js/JavaScript only | ❌ No Python support |
| **Session Reuse** | ✅ Partial (cookies, same instance) | No pre-loaded profiles; manual credential loading |
| **Headless Mode** | ✅ Yes (default) | Can be disabled if needed |
| **Installation** | 3 options (Claude/OpenClaw/Standalone) | Requires Node.js ≥20 & npm |
| **Claude.ai Usage Page** | ❌ Not publicly accessible | Authenticated endpoint (403) |
| **Recommended for Tiny Monitor** | Cheliped for web automation; Claude API for usage data | Combine both for optimal integration |

---

## Recommendations

1. **For Web Scraping**: Use Cheliped Browser as a Node.js subprocess if Python wrapper needed
2. **For Claude API Usage**: Use official `anthropic` SDK, not web scraping
3. **Session Management**: Implement cookie storage and reuse via Cheliped's session module
4. **Headless Deployment**: Leverage default headless mode for server environments
5. **Production Readiness**: Consider Cheliped still early-stage; test thoroughly before production deployment
