# Enterprise Integration Specification

**Charter v3.1.0 — Codename: Federation**
**Revision:** 1.0
**Date:** 2026-03-01
**Status:** Definitive
**License:** Apache 2.0

---

## 1. Overview

Charter is an AI governance layer for autonomous agent teams. It enforces ethical constraints, gradient decisions, and self-audit trails across any AI system — Claude, GPT, Copilot, Gemini, or custom agents.

**Design principles:**

- **Local-first.** All governance data lives on your machine. No cloud dependency, no SaaS requirement, no data leaving your perimeter.
- **Zero infrastructure cost.** A single `pip install charter-governance` and `charter bootstrap` governs an entire project in under three seconds.
- **Single dependency.** The core CLI depends only on PyYAML. Nothing else.
- **Apache 2.0.** Use it, modify it, embed it. No vendor lock-in.

**Three governance layers:**

| Layer | Name | Purpose |
|-------|------|---------|
| A | Hard Constraints | Absolute prohibitions. Additive only. Cannot be weakened or deleted. |
| B | Gradient Decisions | Threshold-based escalations requiring human judgment above defined limits. |
| C | Self-Audit | Periodic self-review generating honest, transparent accountability reports. |

**Structural safeguards:**

- **Kill triggers** halt all agent work immediately when defined conditions are detected (e.g., ethical gradient acceleration, audit friction, conscience conflict).
- **Hash chain** provides a tamper-evident, append-only audit trail with cryptographic linkage.
- **Merkle trees** enable O(log n) proof verification at production scale.

---

## 2. API Surface

### 2.1 MCP Tools (33 tools as of v3.0.0)

Charter exposes its full governance surface through the Model Context Protocol (MCP), enabling any MCP-compatible AI system to interact with governance state.

#### Core

| Tool | Purpose |
|------|---------|
| `charter_status` | Returns current governance state: layers, kill trigger status, chain length, identity |
| `charter_get_config` | Reads the active `charter.yaml` configuration |
| `charter_identity` | Returns the current node's pseudonymous identity and trust level |
| `charter_audit` | Triggers a Layer C self-audit and returns the report |

#### Chain

| Tool | Purpose |
|------|---------|
| `charter_append_chain` | Appends a new entry to the hash chain with event type, data, and HMAC signature |
| `charter_read_chain` | Reads chain entries with optional filtering by event type, date range, or signer |
| `charter_check_integrity` | Verifies the full chain from genesis to tip — returns pass/fail with first broken link |

#### Attribution

| Tool | Purpose |
|------|---------|
| `charter_stamp` | Generates an attribution stamp: `Charter-Stamp: v1.0:<node_id>:<agent>:governed:<hash>` |
| `charter_verify_stamp` | Verifies a stamp against the local chain — confirms authenticity and governance state |

#### Dispute Resolution

| Tool | Purpose |
|------|---------|
| `charter_dispute_export` | Exports a dispute package: chain slice, Merkle proofs, timestamps, identity attestations |
| `charter_dispute_verify` | Verifies an incoming dispute package against its cryptographic proofs |

#### Timestamps

| Tool | Purpose |
|------|---------|
| `charter_timestamp_anchor` | Anchors a chain entry to an external RFC 3161 Time Stamping Authority |
| `charter_timestamp_status` | Returns the status of pending and completed timestamp anchors |

#### Merkle

| Tool | Purpose |
|------|---------|
| `charter_merkle_batch` | Batches multiple chain entries into a Merkle tree for efficient verification |
| `charter_merkle_prove` | Generates an inclusion proof for a specific entry within a Merkle tree |
| `charter_merkle_verify` | Verifies a Merkle inclusion proof |
| `charter_merkle_exchange_proof` | Generates a portable proof package for cross-organization exchange |
| `charter_merkle_verify_exchange` | Verifies an exchanged proof package from another organization |
| `charter_merkle_status` | Returns current Merkle tree state: root hash, leaf count, tree height |

#### Decision Intelligence

| Tool | Purpose |
|------|---------|
| `charter_tag_confidence` | Tags a chain entry with a confidence score and reasoning metadata |
| `charter_revision_history` | Returns the revision chain for an entry — all corrections, annotations, and updates |

#### Red Team

| Tool | Purpose |
|------|---------|
| `charter_redteam_run` | Executes a red team probe against the current governance configuration |
| `charter_redteam_status` | Returns results of the most recent red team run |

#### Arbitration

| Tool | Purpose |
|------|---------|
| `charter_arbitrate` | Routes a decision to multiple models and returns consensus or divergence analysis |

#### RBAC

| Tool | Purpose |
|------|---------|
| `charter_propose_rule` | Proposes a new Layer A or Layer B rule, requiring dual signoff to activate |
| `charter_sign_rule` | Signs a proposed rule — rule activates when required signatures are met |
| `charter_role_status` | Returns current RBAC configuration: roles, permissions, pending proposals |

#### Alerting

| Tool | Purpose |
|------|---------|
| `charter_alert_status` | Returns current alert configuration and recent alert history |

#### SIEM

| Tool | Purpose |
|------|---------|
| `charter_siem_export` | Exports chain data in SIEM-compatible formats (CEF, JSON, syslog) |

#### Compliance

| Tool | Purpose |
|------|---------|
| `charter_compliance_map` | Maps current governance state to a compliance framework (SOC 2, GDPR, EU AI Act, NIST AI RMF, ISO 27001, SOX, HIPAA, FERPA) |

#### Federation

| Tool | Purpose |
|------|---------|
| `charter_federation_status` | Returns federation topology: connected nodes, health, last sync times |
| `charter_federation_events` | Aggregates recent events across federated nodes (read-only, no data centralization) |

#### Local Inference

| Tool | Purpose |
|------|---------|
| `charter_local_inference` | Routes inference requests to a local model (e.g., Qwen3 on a local compute node) |

### 2.2 Daemon REST API (Port 8374)

The Charter daemon runs as a background Flask service, providing a web dashboard and REST endpoints for continuous monitoring.

#### Endpoints

**GET /api/status**

Returns the current governance status.

```json
{
    "governed": true,
    "domain": "finance",
    "layer_a_rules": 10,
    "layer_b_decisions": 4,
    "layer_c_frequency": "daily",
    "kill_triggers": 4,
    "chain_length": 247,
    "chain_integrity": "valid",
    "identity": "node-93921f61",
    "version": "3.0.0"
}
```

**GET /api/detect**

Scans for AI tools and agents in the current environment.

```json
{
    "agents_detected": ["claude_code", "copilot"],
    "governed": ["claude_code"],
    "ungoverned": ["copilot"],
    "recommendation": "Run 'charter bootstrap' in the copilot workspace"
}
```

**GET /api/chain**

Returns chain entries with pagination.

Query parameters:
- `page` (int, default 1) — page number
- `per_page` (int, default 50) — entries per page
- `event` (string, optional) — filter by event type
- `since` (ISO 8601, optional) — filter entries after this timestamp
- `signer` (string, optional) — filter by signer identity

```json
{
    "entries": [...],
    "page": 1,
    "per_page": 50,
    "total": 247,
    "chain_integrity": "valid"
}
```

### 2.3 Chain JSONL Format

Each entry in the hash chain follows this structure:

```json
{
    "index": 0,
    "timestamp": "2026-03-01T00:00:00Z",
    "event": "event_type",
    "data": {},
    "previous_hash": "0000000000000000000000000000000000000000000000000000000000000000",
    "hash": "sha256...",
    "signer": "public_id",
    "signature": "hmac_sha256..."
}
```

**Field definitions:**

| Field | Type | Description |
|-------|------|-------------|
| `index` | integer | Sequential entry number, starting at 0 (genesis) |
| `timestamp` | string (ISO 8601) | UTC timestamp of entry creation |
| `event` | string | Event type (e.g., `bootstrap`, `decision`, `audit`, `kill_trigger`) |
| `data` | object | Event-specific payload — schema varies by event type |
| `previous_hash` | string (hex) | SHA-256 hash of the preceding entry (all zeros for genesis) |
| `hash` | string (hex) | SHA-256 hash of the current entry (excludes `hash` and `signature` fields) |
| `signer` | string | Pseudonymous identity of the signing node |
| `signature` | string (hex) | HMAC-SHA256 signature using the node's private seed |

**Integrity verification:** To verify the chain, recompute each entry's hash from its fields (excluding `hash` and `signature`), confirm it matches the stored `hash`, and confirm `previous_hash` matches the preceding entry's `hash`. A single mismatch indicates tampering.

---

## 3. Integration Patterns

### 3.1 SIEM Integration

Charter exports governance events in formats compatible with enterprise SIEM platforms.

**Supported formats:**

| Format | Target Platform | Standard |
|--------|----------------|----------|
| CEF | Splunk, ArcSight | Common Event Format |
| Structured JSON | Datadog, Elastic, custom | Native JSON |
| Syslog | Any syslog collector | RFC 5424 |

**Batch export:**

```bash
# Export full chain in CEF format for Splunk ingestion
charter siem export --format cef --output /var/log/charter/events.cef

# Export as structured JSON for Datadog
charter siem export --format json --output /var/log/charter/events.json

# Export as RFC 5424 syslog
charter siem export --format syslog --output /var/log/charter/events.log
```

**Real-time streaming:**

```bash
# Stream events as JSON to stdout (pipe to your collector)
charter siem stream --format json

# Stream CEF events to a file (tail with your SIEM agent)
charter siem stream --format cef --output /var/log/charter/stream.cef
```

**CEF example:**

```
CEF:0|Charter|Governance|3.0.0|DECISION|Layer B Escalation|5|src=node-93921f61 act=financial_transaction threshold=always outcome=escalated_to_human
```

### 3.2 Alerting

Charter sends alerts via webhooks, Slack, or email when governance events require attention.

**Webhook configuration (charter.yaml):**

```yaml
alerting:
  webhook:
    url: "https://your-endpoint.example.com/charter-alerts"
    secret: "${CHARTER_WEBHOOK_SECRET}"
    events:
      - kill_trigger
      - layer_a_violation_attempt
      - chain_integrity_failure
      - redteam_finding
  slack:
    webhook_url: "${CHARTER_SLACK_WEBHOOK}"
    channel: "#ai-governance"
    events:
      - kill_trigger
      - audit_complete
  email:
    smtp_host: "smtp.example.com"
    smtp_port: 587
    from: "charter@example.com"
    to:
      - "security@example.com"
    events:
      - kill_trigger
      - chain_integrity_failure
```

**Webhook payload signing:**

All webhook payloads are signed with HMAC-SHA256. The signature is included in the request header:

```
X-Charter-Signature: sha256=<hex_digest>
```

**Verification (Python example):**

```python
import hmac
import hashlib

def verify_charter_webhook(payload_body: bytes, signature_header: str, secret: str) -> bool:
    expected = hmac.new(
        secret.encode("utf-8"),
        payload_body,
        hashlib.sha256
    ).hexdigest()
    received = signature_header.replace("sha256=", "")
    return hmac.compare_digest(expected, received)
```

### 3.3 SSO and Identity Verification

Charter's identity system is pseudonymous by default and upgradable to verified through external providers.

**Trust levels (ascending):**

| Level | Provider | Verification |
|-------|----------|-------------|
| `self_declared` | None | Node generates its own SHA-256 identity — no external attestation |
| `basic` | Email | Email ownership verified via challenge token |
| `organizational` | ID.me, corporate SSO | Organizational membership attested by an identity provider |
| `government` | Persona | Government-issued ID verified through Persona's document verification |

**Identity upgrade flow:**

1. Node starts with `self_declared` identity (SHA-256 of private seed)
2. Operator initiates verification: `charter identity verify --provider persona`
3. Provider performs verification and returns attestation
4. Attestation is appended to the hash chain as an `identity_upgrade` event
5. All subsequent chain entries carry the upgraded trust level

**Integration with enterprise SSO:**

Charter does not replace your SSO. It maps your SSO-authenticated identities to Charter pseudonymous IDs, allowing you to maintain your existing authentication infrastructure while gaining Charter's governance trail.

### 3.4 CI/CD Integration

Charter integrates into existing CI/CD pipelines as a governance gate.

**Basic pipeline integration:**

```yaml
# GitHub Actions example
- name: Bootstrap Charter governance
  run: |
    pip install charter-governance
    charter bootstrap --domain finance

- name: Red team governance check
  run: charter redteam run --exit-code

- name: Compliance verification
  run: charter compliance map --standard hipaa --exit-code

- name: Run agent tasks (governed)
  run: python run_agents.py
```

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0 | All checks passed |
| 1 | Governance violation detected |
| 2 | Kill trigger fired |
| 3 | Chain integrity failure |
| 4 | Red team finding above threshold |

---

## 4. Deployment Models

### 4.1 Local-First (Default)

The standard deployment. A single machine, a single `pip install`, a single command.

```bash
pip install charter-governance
charter bootstrap --domain finance
```

**What this creates:**

```
.charter/
  charter.yaml          # Governance configuration
  chain.jsonl           # Hash chain (append-only audit trail)
  identity/
    private_seed.key    # HMAC signing key (never leaves this machine)
    public_id.txt       # SHA-256 pseudonymous identity
CLAUDE.md               # Governance rules injected into AI agent context
```

**Suitable for:** Individual developers, small teams, proof-of-concept deployments.

### 4.2 Daemon Mode

A background Flask service providing continuous monitoring and a web dashboard.

```bash
charter daemon start --port 8374
```

**Capabilities:**

- Web dashboard at `http://localhost:8374`
- REST API (see Section 2.2)
- Continuous chain integrity monitoring
- Real-time AI tool detection
- Alert dispatch (webhook, Slack, email)

**Process management:**

```bash
charter daemon start          # Start in background
charter daemon stop           # Graceful shutdown
charter daemon status         # Health check
charter daemon restart        # Stop + start
```

**Suitable for:** Teams requiring persistent monitoring, organizations with compliance dashboards.

### 4.3 Federated

Multiple Charter nodes connected via MCP SSE, providing aggregated visibility without data centralization.

```
                   +-------------------+
                   | Federated Dashboard |
                   | (Read-Only Aggregation) |
                   +--------+----------+
                            |
             +--------------+--------------+
             |              |              |
        +----+----+    +----+----+    +----+----+
        | Node A  |    | Node B  |    | Node C  |
        | (NYC)   |    | (London)|    | (Tokyo) |
        | :8375   |    | :8375   |    | :8375   |
        +---------+    +---------+    +---------+
```

**Each node is autonomous.** The federation provides visibility, not control. Data never leaves the source node.

**Suitable for:** Multi-site enterprises, distributed teams, organizations with data residency requirements.

---

## 5. Federation Protocol

### 5.1 Transport

Nodes expose MCP SSE at a configurable port (default 8375):

```
http://<node_address>:8375/sse
```

**Health check:**

```
GET /health
```

Returns:

```json
{
    "status": "healthy",
    "node_id": "node-93921f61",
    "version": "3.0.0",
    "chain_length": 247,
    "uptime_seconds": 86400
}
```

### 5.2 Configuration

Federation is configured in `~/.charter/federation.yaml`:

```yaml
federation:
  enabled: true
  node_name: "headquarters"
  listen_port: 8375
  peers:
    - name: "london-office"
      address: "100.95.120.54"
      port: 8375
    - name: "tokyo-office"
      address: "100.91.176.66"
      port: 8375
  sync_interval_seconds: 300
  tls:
    enabled: true
    cert_path: "/etc/charter/tls/cert.pem"
    key_path: "/etc/charter/tls/key.pem"
```

### 5.3 Aggregation

The federated dashboard queries each peer's `/api/status` and `/api/chain` endpoints:

- Status aggregation provides a topology view: which nodes are healthy, their governance state, chain lengths, and last activity timestamps.
- Chain aggregation merges events from all nodes into a unified timeline for review. Events are tagged with their source node and are read-only.

### 5.4 Data Sovereignty

**Data never leaves the source node.** The federation protocol is strictly read-only:

- The dashboard queries live state from each peer on demand.
- No chain data is copied, cached, or stored on the dashboard node.
- If a peer is unreachable, its data is simply absent from the aggregated view.
- Each node can revoke federation access at any time by removing the peer entry or shutting down its SSE endpoint.

This follows the Italian cooperative model: each node is autonomous and sovereign. Federation provides visibility across the cooperative without centralizing power or data.

---

## 6. Compliance Framework Mappings

Charter maps its governance state to established compliance frameworks, generating reports that demonstrate how Charter controls satisfy framework requirements.

### 6.1 SOX (Sarbanes-Oxley) — 10 Controls

| Section | Requirement | Charter Control |
|---------|-------------|----------------|
| 302 | CEO/CFO certification of financial reports | Layer B `financial_transaction` escalation + chain evidence |
| 404 | Internal control assessment | Layer C self-audit + chain integrity verification |
| 802 | Document retention | Append-only hash chain with tamper detection |
| 906 | Criminal penalties for false certification | Kill trigger: `conscience_conflict` |
| ITGC-1 | Access controls | RBAC with dual-signoff rule governance |
| ITGC-2 | Change management | `charter_revision_history` + chain-linked changes |
| ITGC-3 | Computer operations | Daemon continuous monitoring + alerting |
| ITGC-4 | Program development | `charter_redteam_run` as CI gate |
| ITGC-5 | Segregation of duties | Dual-signoff (`charter_propose_rule` + `charter_sign_rule`) |
| ITGC-6 | Audit trail | Hash chain + Merkle trees + RFC 3161 timestamps |

### 6.2 HIPAA — 15 Controls

**Administrative Safeguards:**

| Control | Requirement | Charter Control |
|---------|-------------|----------------|
| 164.308(a)(1) | Security management process | Three-layer governance + kill triggers |
| 164.308(a)(3) | Workforce security | RBAC + identity verification |
| 164.308(a)(4) | Information access management | Layer B `data_access` threshold escalation |
| 164.308(a)(5) | Security awareness training | Red team probes surface governance gaps |
| 164.308(a)(6) | Security incident procedures | Kill triggers + alerting + chain logging |
| 164.308(a)(8) | Evaluation | Layer C self-audit (minimum weekly) |

**Technical Safeguards:**

| Control | Requirement | Charter Control |
|---------|-------------|----------------|
| 164.312(a)(1) | Access control | RBAC + dual-signoff identity management |
| 164.312(b) | Audit controls | Hash chain + SIEM export |
| 164.312(c)(1) | Integrity | Chain integrity verification + Merkle proofs |
| 164.312(d) | Person/entity authentication | Pseudonymous identity with upgrade path |
| 164.312(e)(1) | Transmission security | TLS for federation, HMAC signing for webhooks |

**Additional HIPAA Controls:**

| Control | Requirement | Charter Control |
|---------|-------------|----------------|
| PHI-1 | Minimum necessary standard | Layer A domain rules restrict data scope |
| PHI-2 | Business associate agreements | Federation data sovereignty (data never centralized) |
| PHI-3 | Breach notification | Kill trigger `audit_friction` + alerting |
| PHI-4 | Documentation retention (6 years) | Append-only chain with RFC 3161 timestamping |

### 6.3 FERPA — 12 Controls

| Control | Requirement | Charter Control |
|---------|-------------|----------------|
| FERPA-1 | Prior written consent for disclosure | Layer B `external_communication` escalation |
| FERPA-2 | Directory information designation | Layer A domain rules define data classification |
| FERPA-3 | Annual notification of rights | Layer C audit includes access review |
| FERPA-4 | Right to inspect and review | `charter_read_chain` provides full audit access |
| FERPA-5 | Right to amend records | `charter_revision_history` with chain linkage |
| FERPA-6 | Limitation on re-disclosure | Layer A hard constraint on unauthorized sharing |
| FERPA-7 | Record of disclosures | Hash chain logs all data access events |
| FERPA-8 | Security of education records | RBAC + identity verification |
| FERPA-9 | Outsourcing safeguards | Federation data sovereignty |
| FERPA-10 | De-identification standards | Pseudonymous identity system |
| FERPA-11 | AI-specific: automated decision logging | `charter_tag_confidence` + chain attribution |
| FERPA-12 | AI-specific: algorithmic transparency | `charter_arbitrate` multi-model consensus |

**Running compliance checks:**

```bash
# Map current governance to HIPAA controls
charter compliance map --standard hipaa

# Generate a formal compliance report
charter compliance report --standard sox --output sox-report.pdf

# CI gate: fail if compliance gaps are found
charter compliance map --standard ferpa --exit-code
```

---

## 7. Security Model

| Layer | Mechanism | Purpose |
|-------|-----------|---------|
| Hash Chain | SHA-256 linked entries | Tamper-evident audit trail — any modification breaks the chain |
| Signatures | HMAC-SHA256 per entry | Non-repudiation and attribution — every entry is signed by a known identity |
| Merkle Trees | SHA-256 binary trees | O(log n) proof verification — prove any single entry's inclusion without revealing the full chain |
| RFC 3161 | External TSA anchoring | Independent timestamp attestation — a third party confirms when an entry existed |
| Identity | SHA-256 pseudonymous IDs | Upgradable to government-verified — privacy by default, accountability when needed |
| Layer 0 | Hardcoded Python invariants | Structural guarantees nobody can lower — not configurable, not overridable |
| Webhook Signing | HMAC-SHA256 | Alert payload integrity — receivers can verify alerts came from Charter |

### 7.1 Layer 0: Structural Invariants

Layer 0 is not configurable. It is hardcoded in the Charter Python source. These invariants exist below the governance configuration and cannot be altered by any `charter.yaml` setting, any MCP tool call, or any API request.

**Layer 0 invariants include:**

- Kill triggers cannot be disabled
- Layer A rules cannot be deleted
- The hash chain cannot be edited (append-only)
- Audit frequency cannot be set below weekly
- Identity signing keys cannot be exported without dual signoff

Layer 0 is the reason Charter can make structural guarantees. Everything above Layer 0 is configurable. Layer 0 itself is not.

### 7.2 Threat Model

| Threat | Mitigation |
|--------|-----------|
| Chain tampering | SHA-256 linkage — any modification invalidates all subsequent hashes |
| Signature forgery | HMAC-SHA256 with per-node private seeds — seeds never leave the node |
| Timestamp manipulation | RFC 3161 external TSA anchoring — independent third-party attestation |
| Identity spoofing | Pseudonymous IDs derived from private seeds — upgradable to government-verified |
| Governance downgrade | Layer 0 invariants — structural floor cannot be lowered |
| Data exfiltration via federation | Read-only federation protocol — data never leaves the source node |
| Alert spoofing | HMAC-SHA256 webhook signing — receivers verify payload integrity |
| Insider rule manipulation | Dual-signoff for rule changes — no single actor can modify governance |

---

## 8. The "No" List

Charter will refuse to do these things, regardless of who asks, what contract says, or what configuration is provided. These are structural guarantees, not policy decisions. They are enforced at Layer 0 — hardcoded invariants in the Python source that exist below the governance configuration layer.

### 1. No disabling kill triggers.

Kill triggers are Layer 0 invariants. They cannot be removed, disabled, or weakened through any mechanism — not through `charter.yaml`, not through MCP tools, not through the REST API, not through direct database manipulation. If `ethical_gradient_acceleration`, `audit_friction`, or `conscience_conflict` is detected, Charter stops. There is no override.

**Why:** Kill triggers are the last line of defense. A governance system that can be told to ignore its own alarms is not a governance system.

### 2. No Layer A override.

Layer A (hard constraints) are additive only. Rules can be added through dual-signoff governance. They can never be deleted or weakened. If a rule needs to be relaxed, use Layer B (gradient decisions) where human judgment is required above defined thresholds.

**Why:** Hard constraints exist because some actions should never be taken. A governance system that allows its prohibitions to be removed under pressure has no prohibitions — it has suggestions.

### 3. No centralizing governance data.

The federation protocol reads local chain state. It never copies, stores, or transmits chain data to a central server. Each node owns its data. The federated dashboard shows a live view of peer state — when the dashboard closes, the data is gone. Nothing is cached, replicated, or warehoused.

**Why:** Centralized governance data creates a single point of compromise, a single point of coercion, and a single point of failure. Decentralization is not a feature — it is a security property.

### 4. No editable audit trail.

The hash chain is append-only. Corrections are appended as new entries with revision linkage — the original entry is never modified. The `charter_revision_history` tool shows the full correction chain. Chain integrity is cryptographically verifiable at any time via `charter_check_integrity`.

**Why:** An audit trail that can be edited is not an audit trail. It is a narrative. Append-only ensures that what happened stays in the record, even if later entries correct or contextualize it.

### 5. No audit frequency below weekly.

Layer C self-audit must run at least weekly. This is a Layer 0 invariant. The `audit_frequency` field in `charter.yaml` accepts `daily`, `weekly`, or any cron expression that resolves to at least weekly. Attempts to set a lower frequency (e.g., `monthly`, `quarterly`) are rejected at bootstrap time.

**Why:** Governance without regular review is governance in name only. Weekly is the minimum cadence that ensures accountability is maintained even during quiet periods when the temptation to skip review is highest.

### 6. No exporting identity signing keys without dual signoff.

The private seed that signs chain entries (stored at `.charter/identity/private_seed.key`) cannot be exported in plaintext without two authorized team members approving via the dual-signoff process (`charter_propose_rule` + `charter_sign_rule`). Programmatic access to the seed for signing operations does not require signoff — only export (copying the key material to another location).

**Why:** The private seed is the root of trust for a node's entire chain history. Uncontrolled export enables impersonation, retroactive forgery, and silent takeover. Dual signoff ensures that key export is a deliberate, witnessed organizational decision.

---

## 9. Version History

| Version | Codename | Release | Key Features |
|---------|----------|---------|-------------|
| 1.0 | Genesis | 2026-02 | Three-layer governance (A/B/C), hash chain, kill triggers, CLI bootstrap |
| 2.0 | Identity | 2026-02 | Pseudonymous identity system, MCP server (10 tools), web dashboard, daemon, VS Code extension |
| 2.1 | Evidence | 2026-02 | RFC 3161 timestamps, Merkle trees, dispute resolution, attribution stamps |
| 2.2 | Intelligence | 2026-02 | Confidence tagging, red team probes, multi-model arbitration, revision history |
| 2.3 | Enterprise | 2026-02 | RBAC with dual signoff, alerting (webhook/Slack/email), SIEM export (CEF/JSON/syslog), compliance mapping (SOX/HIPAA/FERPA) |
| 3.0 | Federation | 2026-03 | Federated dashboard, enterprise integration specification, 50+ Python modules, local inference routing |
| 3.1 | Compliance | 2026-03 | 8 compliance frameworks (SOC 2, GDPR, EU AI Act, NIST AI RMF, ISO 27001), scheduled audits, chain retention, runtime alerting |

---

Charter v3.1.0 — 40 Python modules, 33 MCP tools, 46 TS/JS files, Apache 2.0. Zero external dependencies beyond PyYAML.
