"""Module 4: Interface layer — MCP tools, web endpoints, data export.

Exposes the analytics stack (Modules 1-3 + Wolfram bridge) through
every surface a user or AI agent might interact with:

    - MCP tools: AI agents query the analytics store directly
    - Web API: JSON endpoints for dashboards and integrations
    - Data export: Parquet/CSV/JSON for notebooks and external tools
    - Unified API: Single entry point for programmatic access

This module does not contain analytical logic — it delegates to
indexer, query, patterns, and wolfram modules.
"""

import json
import os

from charter.analytics.indexer import Indexer, _now_ms, _get_analytics_dir


# ---------------------------------------------------------------------------
# MCP Tool Definitions (for mcp_server/__init__.py)
# ---------------------------------------------------------------------------

def get_analytics_mcp_tools():
    """Return MCP Tool definitions for the analytics layer.

    These are imported and appended to TOOLS in the MCP server.
    Uses deferred import of Tool to avoid circular dependency.
    """
    from mcp.types import Tool

    return [
        Tool(
            name="charter_analytics_summary",
            description=(
                "Get an organization-wide analytics summary: event volume, "
                "chain health, velocity trends, governance metrics, session "
                "stats, and recent activity. Sub-second response."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        Tool(
            name="charter_analytics_profile",
            description=(
                "Get a deep behavioral profile of a single actor or signer. "
                "Returns event breakdown, session patterns, transitions, "
                "hourly/daily distribution, and recent events."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "actor": {
                        "type": "string",
                        "description": "Actor name or prefix to filter by.",
                    },
                    "signer": {
                        "type": "string",
                        "description": "Signer hash prefix to filter by.",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="charter_analytics_compare",
            description=(
                "Rank actors by a behavioral metric. Metrics: volume, "
                "diversity, session_density, session_duration, "
                "escalation_rate, cadence. Flags outliers."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "description": "Metric to compare by (default: event_diversity).",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="charter_analytics_timeline",
            description=(
                "Activity density over time with trend detection. "
                "Shows event volume per time bucket and whether activity "
                "is increasing, decreasing, or stable."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": "Lookback: 7d, 30d, 90d, all (default: 30d).",
                    },
                    "granularity": {
                        "type": "string",
                        "description": "Bucket size: hour, day, week, month (default: day).",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="charter_analytics_flow",
            description=(
                "Analyze what happens before and after a given event type. "
                "Returns predecessors, successors, common sequences, and "
                "timing statistics."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "event": {
                        "type": "string",
                        "description": "The event type to analyze.",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Steps before/after to trace (1-5, default: 2).",
                    },
                },
                "required": ["event"],
            },
        ),
        Tool(
            name="charter_analytics_search",
            description=(
                "Full-text search across event types and data payloads. "
                "Case-insensitive substring match."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "Search term.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 25).",
                    },
                },
                "required": ["term"],
            },
        ),
        Tool(
            name="charter_analytics_sequences",
            description=(
                "Mine frequent event subsequences across sessions. "
                "Discovers common workflow patterns using PrefixSpan."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "min_support": {
                        "type": "integer",
                        "description": "Min sessions containing pattern (default: 2).",
                    },
                    "max_length": {
                        "type": "integer",
                        "description": "Max pattern length (default: 5).",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="charter_analytics_anomalies",
            description=(
                "Detect behavioral anomalies by comparing recent activity "
                "to historical baselines. Flags spikes, drops, new actors, "
                "and disappeared event types."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "lookback_days": {
                        "type": "integer",
                        "description": "Recent window to check (default: 7).",
                    },
                    "baseline_days": {
                        "type": "integer",
                        "description": "Historical baseline window (default: 30).",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="charter_analytics_causes",
            description=(
                "Causal discovery: find events that statistically precede "
                "a target event more often than chance. Computes lift, "
                "conditional probability, and temporal consistency."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "target_event": {
                        "type": "string",
                        "description": "The outcome event to explain.",
                    },
                    "window_size": {
                        "type": "integer",
                        "description": "Events before target to examine (default: 5).",
                    },
                },
                "required": ["target_event"],
            },
        ),
        Tool(
            name="charter_analytics_fingerprint",
            description=(
                "Generate a behavioral fingerprint — a normalized vector "
                "of breadth, intensity, focus, endurance, governance, and "
                "consistency. Compares similarity between actors."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "actor": {
                        "type": "string",
                        "description": "Actor to fingerprint (omit for org-wide).",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="charter_analytics_query",
            description=(
                "Execute a custom SQL query against the Charter analytics "
                "DuckDB store. Tables: events, sessions, transitions, "
                "plus any ingested datasets."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": "SQL query to execute.",
                    },
                },
                "required": ["sql"],
            },
        ),
        Tool(
            name="charter_analytics_ingest",
            description=(
                "Import a CSV or JSON dataset into the analytics store "
                "as a queryable table. Enables joining external data "
                "(outcomes, clinical records) with chain events."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to CSV or JSON file.",
                    },
                    "table_name": {
                        "type": "string",
                        "description": "Table name in DuckDB (auto-derived if omitted).",
                    },
                },
                "required": ["file_path"],
            },
        ),
        Tool(
            name="charter_analytics_export",
            description=(
                "Export analytics data as Parquet, CSV, or JSON for use "
                "in external tools (notebooks, R, Wolfram). Exports any "
                "table or query result."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Table name or SQL query to export.",
                    },
                    "format": {
                        "type": "string",
                        "description": "Export format: parquet, csv, json (default: parquet).",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Output file path (auto-generated if omitted).",
                    },
                },
                "required": ["source"],
            },
        ),
    ]


# ---------------------------------------------------------------------------
# MCP Tool Handlers
# ---------------------------------------------------------------------------

def handle_analytics_mcp_tool(name, arguments):
    """Handle an analytics MCP tool call.

    Args:
        name: Tool name (e.g., "charter_analytics_summary").
        arguments: Dict of tool arguments.

    Returns:
        List of TextContent, or None if the tool name is not recognized.
    """
    from mcp.types import TextContent

    if not name.startswith("charter_analytics_"):
        return None

    try:
        result = _dispatch_analytics(name, arguments)
        return [TextContent(
            type="text",
            text=json.dumps(result, indent=2, default=str),
        )]
    except ImportError as e:
        return [TextContent(
            type="text",
            text=json.dumps({
                "error": f"Analytics dependency missing: {e}",
                "hint": "Install with: pip install charter-governance[analytics]",
            }),
        )]
    except Exception as e:
        return [TextContent(
            type="text",
            text=json.dumps({"error": str(e)}),
        )]


def _dispatch_analytics(name, arguments):
    """Route an analytics tool call to the appropriate module."""

    if name == "charter_analytics_summary":
        from charter.analytics.query import QueryEngine
        qe = QueryEngine()
        try:
            return qe.summary()
        finally:
            qe.close()

    elif name == "charter_analytics_profile":
        from charter.analytics.query import QueryEngine
        qe = QueryEngine()
        try:
            return qe.actor_profile(
                actor_prefix=arguments.get("actor"),
                signer_prefix=arguments.get("signer"),
            )
        finally:
            qe.close()

    elif name == "charter_analytics_compare":
        from charter.analytics.query import QueryEngine
        qe = QueryEngine()
        try:
            return qe.compare(
                metric=arguments.get("metric", "event_diversity"),
            )
        finally:
            qe.close()

    elif name == "charter_analytics_timeline":
        from charter.analytics.query import QueryEngine
        qe = QueryEngine()
        try:
            return qe.timeline(
                period=arguments.get("period", "30d"),
                granularity=arguments.get("granularity", "day"),
            )
        finally:
            qe.close()

    elif name == "charter_analytics_flow":
        from charter.analytics.query import QueryEngine
        qe = QueryEngine()
        try:
            return qe.flow(
                event=arguments["event"],
                depth=arguments.get("depth", 2),
            )
        finally:
            qe.close()

    elif name == "charter_analytics_search":
        from charter.analytics.query import QueryEngine
        qe = QueryEngine()
        try:
            return qe.search(
                term=arguments["term"],
                limit=arguments.get("limit", 25),
            )
        finally:
            qe.close()

    elif name == "charter_analytics_sequences":
        from charter.analytics.patterns import PatternEngine
        pe = PatternEngine()
        try:
            return pe.mine_sequences(
                min_support=arguments.get("min_support", 2),
                max_length=arguments.get("max_length", 5),
            )
        finally:
            pe.close()

    elif name == "charter_analytics_anomalies":
        from charter.analytics.patterns import PatternEngine
        pe = PatternEngine()
        try:
            return pe.detect_anomalies(
                lookback_days=arguments.get("lookback_days", 7),
                baseline_days=arguments.get("baseline_days", 30),
            )
        finally:
            pe.close()

    elif name == "charter_analytics_causes":
        from charter.analytics.patterns import PatternEngine
        pe = PatternEngine()
        try:
            return pe.discover_causes(
                target_event=arguments["target_event"],
                window_size=arguments.get("window_size", 5),
            )
        finally:
            pe.close()

    elif name == "charter_analytics_fingerprint":
        from charter.analytics.patterns import PatternEngine
        pe = PatternEngine()
        try:
            return pe.fingerprint(actor=arguments.get("actor"))
        finally:
            pe.close()

    elif name == "charter_analytics_query":
        from charter.analytics.query import QueryEngine
        qe = QueryEngine()
        try:
            columns, rows, elapsed = qe.query(arguments["sql"])
            return {
                "columns": columns,
                "rows": [list(r) for r in rows],
                "count": len(rows),
                "elapsed_ms": elapsed,
            }
        finally:
            qe.close()

    elif name == "charter_analytics_ingest":
        from charter.analytics.wolfram import WolframBridge
        wb = WolframBridge()
        try:
            return wb.ingest_dataset(
                file_path=arguments["file_path"],
                name=arguments.get("table_name"),
            )
        finally:
            wb.close()

    elif name == "charter_analytics_export":
        return export_data(
            source=arguments["source"],
            fmt=arguments.get("format", "parquet"),
            output_path=arguments.get("output_path"),
        )

    return {"error": f"Unknown analytics tool: {name}"}


# ---------------------------------------------------------------------------
# Web API Endpoints (for web/app.py)
# ---------------------------------------------------------------------------

def register_analytics_routes(app):
    """Register analytics API routes on a Flask app.

    Call this from create_app() to add /api/analytics/* endpoints.

    Args:
        app: Flask application instance.
    """
    from flask import jsonify, request

    @app.route("/api/analytics/summary")
    def api_analytics_summary():
        from charter.analytics.query import QueryEngine
        qe = QueryEngine()
        try:
            return jsonify(qe.summary())
        finally:
            qe.close()

    @app.route("/api/analytics/profile")
    def api_analytics_profile():
        from charter.analytics.query import QueryEngine
        actor = request.args.get("actor")
        signer = request.args.get("signer")
        qe = QueryEngine()
        try:
            return jsonify(qe.actor_profile(
                actor_prefix=actor, signer_prefix=signer,
            ))
        finally:
            qe.close()

    @app.route("/api/analytics/compare")
    def api_analytics_compare():
        from charter.analytics.query import QueryEngine
        metric = request.args.get("metric", "event_diversity")
        qe = QueryEngine()
        try:
            return jsonify(qe.compare(metric=metric))
        finally:
            qe.close()

    @app.route("/api/analytics/timeline")
    def api_analytics_timeline():
        from charter.analytics.query import QueryEngine
        period = request.args.get("period", "30d")
        granularity = request.args.get("granularity", "day")
        qe = QueryEngine()
        try:
            return jsonify(qe.timeline(
                period=period, granularity=granularity,
            ))
        finally:
            qe.close()

    @app.route("/api/analytics/flow")
    def api_analytics_flow():
        from charter.analytics.query import QueryEngine
        event = request.args.get("event")
        if not event:
            return jsonify({"error": "event parameter required"}), 400
        depth = request.args.get("depth", 2, type=int)
        qe = QueryEngine()
        try:
            return jsonify(qe.flow(event=event, depth=depth))
        finally:
            qe.close()

    @app.route("/api/analytics/search")
    def api_analytics_search():
        from charter.analytics.query import QueryEngine
        term = request.args.get("term", request.args.get("q", ""))
        if not term:
            return jsonify({"error": "term parameter required"}), 400
        limit = request.args.get("limit", 25, type=int)
        qe = QueryEngine()
        try:
            return jsonify(qe.search(term=term, limit=limit))
        finally:
            qe.close()

    @app.route("/api/analytics/anomalies")
    def api_analytics_anomalies():
        from charter.analytics.patterns import PatternEngine
        lookback = request.args.get("lookback", 7, type=int)
        baseline = request.args.get("baseline", 30, type=int)
        pe = PatternEngine()
        try:
            return jsonify(pe.detect_anomalies(
                lookback_days=lookback, baseline_days=baseline,
            ))
        finally:
            pe.close()

    @app.route("/api/analytics/causes")
    def api_analytics_causes():
        from charter.analytics.patterns import PatternEngine
        event = request.args.get("event")
        if not event:
            return jsonify({"error": "event parameter required"}), 400
        window = request.args.get("window", 5, type=int)
        pe = PatternEngine()
        try:
            return jsonify(pe.discover_causes(
                target_event=event, window_size=window,
            ))
        finally:
            pe.close()

    @app.route("/api/analytics/query", methods=["POST"])
    def api_analytics_query():
        from charter.analytics.query import QueryEngine
        body = request.get_json(silent=True) or {}
        sql = body.get("sql") or request.args.get("sql")
        if not sql:
            return jsonify({"error": "sql parameter required"}), 400
        qe = QueryEngine()
        try:
            columns, rows, elapsed = qe.query(sql)
            return jsonify({
                "columns": columns,
                "rows": [list(r) for r in rows],
                "count": len(rows),
                "elapsed_ms": elapsed,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 400
        finally:
            qe.close()


# ---------------------------------------------------------------------------
# Data Export
# ---------------------------------------------------------------------------

def export_data(source, fmt="parquet", output_path=None):
    """Export analytics data for external tools.

    Args:
        source: Table name (e.g., "events", "sessions") or SQL query.
        fmt: "parquet", "csv", or "json".
        output_path: Output file path (auto-generated if None).

    Returns:
        dict with path, rows, format, and size.
    """
    start = _now_ms()
    indexer = Indexer()
    conn = indexer.connect()
    indexer.sync()

    try:
        # Determine if source is a table name or SQL query
        if " " in source:
            sql = source
            table_name = "query_result"
        else:
            sql = f"SELECT * FROM {source}"
            table_name = source

        # Generate output path
        if output_path is None:
            export_dir = os.path.join(_get_analytics_dir(), "exports")
            os.makedirs(export_dir, exist_ok=True)
            ext = {"parquet": "parquet", "csv": "csv", "json": "json"}.get(
                fmt, "parquet"
            )
            output_path = os.path.join(
                export_dir, f"{table_name}.{ext}"
            )

        # Export using DuckDB's native export
        if fmt == "parquet":
            conn.execute(
                f"COPY ({sql}) TO '{output_path}' (FORMAT PARQUET)"
            )
        elif fmt == "csv":
            conn.execute(
                f"COPY ({sql}) TO '{output_path}' (FORMAT CSV, HEADER)"
            )
        elif fmt == "json":
            result = conn.execute(sql)
            columns = [d[0] for d in result.description]
            rows = result.fetchall()
            data = [dict(zip(columns, row)) for row in rows]
            with open(output_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        else:
            return {"error": f"Unknown format: {fmt}"}

        # Get row count and file size
        row_count = conn.execute(
            f"SELECT COUNT(*) FROM ({sql})"
        ).fetchone()[0]

        file_size = os.path.getsize(output_path)

        return {
            "path": output_path,
            "format": fmt,
            "rows": row_count,
            "size_bytes": file_size,
            "table": table_name,
            "elapsed_ms": _now_ms() - start,
        }

    finally:
        indexer.close()


# ---------------------------------------------------------------------------
# CLI: Export command
# ---------------------------------------------------------------------------

def run_export_cli(args):
    """CLI entry point for data export."""
    source = getattr(args, "sql", None) or getattr(args, "source", None)
    if not source:
        print("Usage: charter analytics export <table_or_sql> "
              "[--format parquet|csv|json] [--output path]")
        return

    fmt = getattr(args, "export_format", "parquet")
    output = getattr(args, "output", None)

    result = export_data(source=source, fmt=fmt, output_path=output)

    if "error" in result:
        print(f"Error: {result['error']}")
        return

    print("Charter Analytics — Export")
    print("=" * 40)
    print(f"  Source:  {result['table']}")
    print(f"  Format:  {result['format']}")
    print(f"  Rows:    {result['rows']:,}")
    print(f"  Size:    {_human_bytes(result['size_bytes'])}")
    print(f"  Path:    {result['path']}")
    print(f"  ({result['elapsed_ms']}ms)")


def _human_bytes(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if n != int(n) else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
