"""Charter Analytics — query and pattern discovery on governance chains.

Transforms the append-only hash chain into an indexed analytical store
for fast queries, cohort comparison, and causal discovery.

Modules:
    indexer  — Incremental ETL from chain.jsonl to DuckDB
    query    — Pre-built lenses and custom SQL (Module 2, future)
    patterns — Sequence mining, anomaly detection (Module 3, future)
"""

__all__ = ["indexer", "query", "patterns", "wolfram", "interface"]
