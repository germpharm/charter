# Charter Governance — Security Assessment

**Assessed Version:** 3.2.0
**Date:** April 2026
**Type:** Automated Static Analysis + Dependency Audit (Interim)
**Status:** No HIGH severity issues. See findings below.

> **Note (May 2026):** Current shipping version is v3.4.0. Updated SBOM and Bandit scan artifacts for v3.4.0 are available at [`docs/sbom.json`](sbom.json) and [`docs/bandit_report.json`](bandit_report.json). The narrative analysis below reflects the v3.2.0 baseline; v3.4.0 added connectors, AI adapters, and analytics expansion (see `vscode-extension/CHANGELOG.md`). A full re-assessment for v3.4.0 is recommended before enterprise deployment.

---

## Executive Summary

Charter Governance v3.2.0 was assessed using Bandit (static analysis), pip-audit (dependency vulnerabilities), and CycloneDX SBOM generation. The core product has **zero HIGH severity issues** and **one direct dependency** (PyYAML) with **zero known vulnerabilities**.

| Metric | Value |
|--------|-------|
| Files scanned | 51 Python modules |
| Lines of code | 18,833 |
| Direct dependencies | 1 (PyYAML 6.0.3) |
| Dependency vulnerabilities (direct) | 0 |
| HIGH severity findings | 0 |
| MEDIUM severity findings | 42 (31 are SQL construction in DuckDB analytics — see analysis) |
| LOW severity findings | 61 (subprocess calls + try/except/pass — expected in CLI tool) |

---

## Static Analysis (Bandit)

### MEDIUM Findings — SQL Construction (31 of 42)

**Files:** `analytics/query.py`, `analytics/patterns.py`, `analytics/wolfram.py`, `analytics/interface.py`

**Finding:** Bandit flags string-based SQL query construction as potential SQL injection (CWE-89).

**Risk Assessment: LOW.** These queries target a local DuckDB database that Charter creates and owns. The database contains only governance chain data from `chain.jsonl`. There is no user-facing SQL input — all queries are constructed internally from typed parameters. DuckDB runs in-process (no network exposure). An attacker would need local filesystem access to the machine, at which point they already have access to the raw chain data.

**Mitigation:** Parameterized queries should be adopted in a future release for defense-in-depth, but the current attack surface is minimal (local-only, no external input).

### MEDIUM Findings — URL Scheme Audit (11 of 42)

**Files:** `alerting.py`, `arbitration.py`, `federation.py`, `verify.py`, `update.py`, `timestamp.py`, `mcp_server/local_model.py`

**Finding:** `urllib.request.urlopen()` usage flagged for potential file:// scheme abuse (CWE-22).

**Risk Assessment: LOW.** All URL targets are hardcoded (PyPI API, identity verification providers, RFC 3161 TSA servers) or configured by the local operator in `charter.yaml`. No user-supplied URLs are opened without operator configuration.

### LOW Findings — Subprocess Calls (30 of 61)

**Files:** `daemon/detector.py`, `hooks/git_hooks.py`, `analytics/wolfram.py`, `timestamp.py`, `update.py`

**Finding:** Subprocess module usage flagged (CWE-78).

**Risk Assessment: EXPECTED.** Charter is a CLI tool that interacts with git (hooks), pip (updates), openssl (timestamps), and optionally Wolfram Engine (analytics). All subprocess calls use hardcoded commands or operator-configured paths. No user-supplied input is passed to shell commands.

### LOW Findings — Try/Except/Pass (31 of 61)

**Files:** `daemon/service.py` (12), various others

**Finding:** Bare except/pass patterns flagged (CWE-703).

**Risk Assessment: EXPECTED.** The daemon service uses resilient error handling to maintain uptime. A background service that crashes on non-critical errors is worse than one that logs and continues. All critical paths (chain integrity, audit logging) use specific exception handling.

---

## Dependency Audit (pip-audit)

### Direct Dependencies

| Package | Version | Vulnerabilities |
|---------|---------|----------------|
| PyYAML | 6.0.3 | **0** |

### Optional Dependencies

| Extra | Packages | Vulnerabilities |
|-------|----------|----------------|
| `[mcp]` | mcp, uvicorn, starlette | 0 |
| `[daemon]` | flask, psutil | flask 3.1.2 has 1 (upgrade to 3.1.3) |
| `[analytics]` | duckdb | 0 |
| `[test]` | pytest | 0 |

**Note:** The 30 vulnerabilities flagged by pip-audit are in the broader development environment, not in Charter's dependency chain. Charter's core has 1 dependency (PyYAML, clean). Optional dependencies have 1 actionable finding (flask 3.1.2 → 3.1.3).

---

## Software Bill of Materials (SBOM)

**Format:** CycloneDX 1.6 (JSON)
**Location:** `docs/sbom.json`
**Charter-specific dependency tree:**

```
charter-governance==3.2.0
  └── PyYAML==6.0.3
```

One dependency. One. That's it for the core CLI.

---

## Architecture Security Properties

| Property | Implementation |
|----------|---------------|
| **Local-first** | All governance data stays on the operator's machine. No cloud dependency, no data exfiltration path. |
| **Cryptographic audit trail** | HMAC-SHA256 hash chain. Each entry includes previous hash. Tampering breaks the chain. |
| **Merkle tree verification** | O(log n) integrity proofs for production-scale chains. |
| **No custom cryptography** | SHA-256 (FIPS 180-4), HMAC-SHA256 (FIPS 198-1). Standard algorithms only. |
| **Minimal attack surface** | 1 direct dependency. No network services in core CLI. MCP/daemon are opt-in. |
| **RFC 3161 timestamps** | Independent Time Stamping Authority attestation closes self-attestation gap. |

---

## Recommendations

| Priority | Action | Status |
|----------|--------|--------|
| Low | Parameterize DuckDB queries in analytics module | Future release |
| Low | Upgrade flask to 3.1.3 in optional daemon dependencies | Next patch |
| Medium | Engage third-party penetration test firm | Budget-dependent ($5K-$20K) |
| Complete | Automated SBOM generation (CycloneDX) | Done — `docs/sbom.json` |
| Complete | Static analysis baseline (Bandit) | Done — `docs/bandit_report.json` |

---

## Limitations

This is an automated assessment, not a formal penetration test. It covers:
- Static code analysis (Bandit — OWASP patterns)
- Known dependency vulnerabilities (pip-audit — CVE/GHSA database)
- Software composition (CycloneDX SBOM)

It does NOT cover:
- Dynamic application security testing (DAST)
- Manual code review by security professionals
- Network penetration testing
- Social engineering assessment

A formal third-party penetration test is recommended before enterprise production deployment.

---

*Charter Governance | Apache 2.0 | charteragent.ai*
