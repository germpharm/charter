# Charter KB — Governed Institutional Memory Layer

**Charter v3.3 Module**
(Compatible with all v3.2.0 installations)

Charter KB adds a clean, queryable wiki layer on top of the existing immutable hash chain and temporal graph. It turns raw audit events and project documents into structured, linked knowledge articles while preserving full provenance and governance.

### Key Features
- Dedicated wikis for every major project/domain
- Obsidian-native frontend (Graph View, backlinks, Dataview queries)
- Automatic immutable logging of every index, compile, and lint to the Charter hash chain
- Full-fidelity raw file preservation (never modified by LLM)
- Automatic cross-project connections and entity linking

### Relationship to Charter v3.2.0
- The immutable hash chain and temporal graph remain unchanged.
- Charter KB is an **optional layer** that sits on top.
- Existing users continue with v3.2.0 exactly as before.
- New users or upgrades gain readable, queryable institutional memory with zero data migration.

### Benefits for Users
- Hospital systems and partners receive clean, linked answers instead of raw logs.
- Auditors get structured articles with direct links back to the exact chain events.
- New team members and interns onboard faster (query instead of asking).
- Deal teams and operations share intelligence across projects without duplication.
- Knowledge compounds instead of evaporating with each session.

### Quick Activation (one command)
```bash
cd charter-kb
./setup.sh
```

This creates the `knowledge/` vault in your environment, copies the logger, and activates automatic chain logging.

### Architecture
- **Raw layer** — Exact copies of source documents (never edited by LLM)
- **Wiki layer** — LLM-generated indexes and concept articles
- **Governance layer** — Every operation is hashed and appended to `~/.charter/chain.jsonl`
- **Frontend** — Obsidian (recommended) or any markdown viewer

### Status
Production-ready - April 2026
Maintained by Matthew Corp AI Systems

**For support or feature requests:** Open an issue in this repo.
