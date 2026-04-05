# Changelog

## [3.3.0] - 2026-04-03

### Added — Charter KB (Governed Institutional Memory)
- **Charter KB module**: Optional wiki layer on top of the immutable hash chain and temporal graph
- **7 project wikis**: Structured knowledge templates for osteo-density-international, germpharm, dartmouth-telepharmacy, the-trades, olo-builders, charter-governance, deal-intelligence
- **Charter logger**: Every KB index, compile, and lint operation is automatically hashed and appended to the chain
- **Obsidian-native frontend**: Graph View, backlinks, and Dataview queries over governed knowledge
- **Raw/wiki/output architecture**: Full-fidelity raw document preservation with LLM-compiled wiki articles
- **One-command activation**: `./setup.sh` creates the knowledge vault and installs the logger
- **Zero migration**: Existing v3.2.0 installations continue unchanged; KB is opt-in

## [3.2.0] - 2026-03-31

### Added — Analytics Release
- **DuckDB analytical store**: Incremental ETL from chain to columnar store with session-based event grouping
- **Behavioral profiling**: Deep actor profiles with activity summaries, session patterns, and temporal distribution
- **Sequence mining**: PrefixSpan algorithm for discovering frequent event subsequences
- **Anomaly detection**: Flag behavioral deviations from historical baselines
- **Causal discovery**: Statistical precedence analysis linking event patterns to outcomes
- **Wolfram Engine bridge**: Causal inference, time series modeling, graph community detection via remote Wolfram Language
- **13 analytics MCP tools**: `charter_analytics_summary`, `charter_analytics_profile`, `charter_analytics_compare`, `charter_analytics_timeline`, `charter_analytics_flow`, `charter_analytics_search`, `charter_analytics_sequences`, `charter_analytics_anomalies`, `charter_analytics_causes`, `charter_analytics_fingerprint`, `charter_analytics_query`, `charter_analytics_ingest`, `charter_analytics_export`
- **Data export**: Parquet, CSV, and JSON output for notebooks and external tools
- **Query engine**: Pre-built analytical lenses — actor profiles, comparisons, timelines, flow analysis, org-wide summary
- **Total MCP tools**: 55 (up from 38)

## [3.1.1] - 2026-03-24

### Added — The Zeroth Law Release
- **Always-on hashing**: Chain never goes silent during work sessions
- **Layer 0 invariants #6-9**: Every interaction hashed, actor attribution required, chain gaps are violations, graph edges immutable
- **Graph edges**: `caused_by`, `revision_of`, `input_to`, `part_of`, `approved_by` — stored in chain entries, included in hash
- **`charter log` command**: Lightweight chain append with actor and edges
- **`charter graph` command**: Query chain as DAG — by actor, file, provenance, with Mermaid/DOT output
- **`charter hooks` command**: Install git post-commit/post-merge hooks for automatic hashing
- **Claude Code hooks**: Auto-log AI edits and tool calls to chain
- **Session watchdog**: Daemon detects work-without-hashing and logs gap events
- **5 new MCP tools**: `charter_log`, `charter_graph_query`, `charter_graph_provenance`, `charter_graph_attribution`, `charter_graph_visualize`

## [1.5.0] - 2026-02-22

### Added
- Expanded Marketplace discoverability — 30 keywords, Machine Learning category
- Improved README with compliance templates and feature details

## [1.4.0] - 2026-02-22

### Fixed
- Status bar hidden when no folder is open (no false UNGOVERNED on blank windows)
- Retry logic when workspace folders load after activation

## [1.3.0] - 2026-02-22

### Fixed
- Workspace folder availability race condition at activation

## [1.2.0] - 2026-02-22

### Fixed
- PATH resolution for Charter CLI in extension host
- Async race condition between governance check and daemon polling

### Added
- Diagnostic logging to Output channel

## [1.1.0] - 2026-02-22

### Added
- Auto-bootstrap: ungoverned workspaces automatically get governance files
- Extended PATH search for Python/pip binary locations

## [1.0.0] - 2026-02-22

### Added
- Initial release
- Status bar governance indicator (GOVERNED / UNGOVERNED)
- Daemon health monitoring
- File system watcher for charter.yaml
- Configuration settings for daemon port, poll interval, auto-bootstrap
