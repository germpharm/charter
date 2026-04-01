"""Pre-built analytical lenses on Charter chain data.

Each lens is a common question humans ask about governance activity.
All queries target the DuckDB analytical store built by the indexer,
so they return in milliseconds — not minutes.

Lenses:
    actor_profile  — Deep view of a single actor's behavior
    compare        — Rank actors by behavioral metrics
    timeline       — Activity density and patterns over time
    flow           — Event sequences: what precedes/follows a given event
    summary        — Org-wide health dashboard in one call
    search         — Full-text search across event data

Usage:
    from charter.analytics.query import QueryEngine
    qe = QueryEngine()
    profile = qe.actor_profile("93921f61")
    comparison = qe.compare(metric="event_diversity")
    timeline = qe.timeline(period="7d")
"""

from charter.analytics.indexer import Indexer, _now_ms


# ---------------------------------------------------------------------------
# QueryEngine
# ---------------------------------------------------------------------------

class QueryEngine:
    """Pre-built analytical lenses over the Charter analytics store.

    Auto-syncs the index on construction to ensure fresh data.

    Args:
        auto_sync: If True (default), run incremental sync on init.
        indexer:   Optional Indexer instance to reuse.
    """

    def __init__(self, auto_sync=True, indexer=None):
        self._indexer = indexer or Indexer()
        self._conn = self._indexer.connect()
        if auto_sync:
            self._indexer.sync()

    def close(self):
        self._indexer.close()

    @property
    def conn(self):
        return self._conn

    # -- Raw query -----------------------------------------------------------

    def query(self, sql, params=None):
        """Execute arbitrary SQL and return (columns, rows, elapsed_ms)."""
        start = _now_ms()
        result = self._conn.execute(sql, params or [])
        columns = [d[0] for d in result.description]
        rows = result.fetchall()
        return columns, rows, _now_ms() - start

    # -- Lens: Actor Profile -------------------------------------------------

    def actor_profile(self, actor_prefix=None, signer_prefix=None):
        """Deep behavioral profile of a single actor or signer.

        Args:
            actor_prefix: Prefix match on actor field (e.g., "collaborative").
            signer_prefix: Prefix match on signer hash (e.g., "93921f").

        Returns:
            dict with identity, activity summary, event breakdown,
            session patterns, top transitions, and temporal profile.
        """
        start = _now_ms()
        where, params = self._build_actor_filter(actor_prefix, signer_prefix)

        # Basic counts
        row = self._conn.execute(f"""
            SELECT
                COUNT(*) as total_events,
                COUNT(DISTINCT event) as unique_events,
                MIN(ts) as first_seen,
                MAX(ts) as last_seen,
                ANY_VALUE(COALESCE(actor, 'unattributed')) as actor_value,
                ANY_VALUE(signer) as signer
            FROM events
            {where}
        """, params).fetchone()

        total_events, unique_events, first_seen, last_seen, actor_val, signer = row

        if total_events == 0:
            return {"error": "No events found for this actor", "elapsed_ms": _now_ms() - start}

        # Active days
        active_days = self._conn.execute(f"""
            SELECT COUNT(DISTINCT DATE_TRUNC('day', ts))
            FROM events {where}
        """, params).fetchone()[0]

        # Event type breakdown
        event_breakdown = self._conn.execute(f"""
            SELECT event, COUNT(*) as cnt,
                   ROUND(COUNT(*) * 100.0 / {total_events}, 1) as pct
            FROM events {where}
            GROUP BY event ORDER BY cnt DESC
        """, params).fetchall()

        # Session stats (match on actor value)
        actor_for_session = actor_val if actor_val != "unattributed" else "__unattributed__"
        session_stats = self._conn.execute("""
            SELECT
                COUNT(*) as session_count,
                ROUND(AVG(event_count), 1) as avg_events_per_session,
                ROUND(AVG(duration_seconds), 1) as avg_session_duration_s,
                MIN(event_count) as min_events,
                MAX(event_count) as max_events,
                ROUND(MIN(duration_seconds), 1) as min_duration_s,
                ROUND(MAX(duration_seconds), 1) as max_duration_s
            FROM sessions
            WHERE actor = ?
        """, [actor_for_session]).fetchone()

        # Top transitions for this actor
        transitions = self._conn.execute("""
            SELECT from_event, to_event, count,
                   ROUND(avg_gap_seconds, 1) as avg_gap_s
            FROM transitions
            WHERE actor = ?
            ORDER BY count DESC LIMIT 10
        """, [actor_for_session]).fetchall()

        # Activity by hour of day
        hourly = self._conn.execute(f"""
            SELECT EXTRACT(HOUR FROM ts) as hour, COUNT(*) as cnt
            FROM events {where}
            GROUP BY EXTRACT(HOUR FROM ts)
            ORDER BY hour
        """, params).fetchall()

        # Activity by day of week (0=Mon, 6=Sun)
        daily = self._conn.execute(f"""
            SELECT EXTRACT(DOW FROM ts) as dow, COUNT(*) as cnt
            FROM events {where}
            GROUP BY EXTRACT(DOW FROM ts)
            ORDER BY dow
        """, params).fetchall()

        # Recent activity (last 20 events)
        recent = self._conn.execute(f"""
            SELECT idx, ts, event,
                   SUBSTRING(data_json, 1, 80) as data_preview
            FROM events {where}
            ORDER BY idx DESC LIMIT 20
        """, params).fetchall()

        return {
            "actor": actor_val,
            "signer": signer,
            "total_events": total_events,
            "unique_event_types": unique_events,
            "first_seen": str(first_seen),
            "last_seen": str(last_seen),
            "active_days": active_days,
            "events_per_day": round(total_events / max(active_days, 1), 1),
            "event_breakdown": [
                {"event": e, "count": c, "pct": p}
                for e, c, p in event_breakdown
            ],
            "sessions": {
                "count": session_stats[0],
                "avg_events": session_stats[1],
                "avg_duration_s": session_stats[2],
                "min_events": session_stats[3],
                "max_events": session_stats[4],
                "min_duration_s": session_stats[5],
                "max_duration_s": session_stats[6],
            },
            "top_transitions": [
                {"from": f, "to": t, "count": c, "avg_gap_s": g}
                for f, t, c, g in transitions
            ],
            "hourly_distribution": [
                {"hour": int(h), "count": c} for h, c in hourly
            ],
            "daily_distribution": [
                {"dow": int(d), "count": c} for d, c in daily
            ],
            "recent_events": [
                {"index": i, "ts": str(t), "event": e, "data_preview": d}
                for i, t, e, d in recent
            ],
            "elapsed_ms": _now_ms() - start,
        }

    # -- Lens: Compare -------------------------------------------------------

    def compare(self, metric="event_diversity", top_n=20):
        """Rank actors by a behavioral metric.

        Metrics:
            event_diversity   — Count of distinct event types (breadth)
            volume            — Total event count (activity level)
            session_density   — Events per session (focus)
            session_duration  — Average session length in seconds
            escalation_rate   — Ratio of governance/audit events to total
            cadence           — Events per active day (consistency)

        Returns:
            dict with ranked list, metric stats, and outlier flags.
        """
        start = _now_ms()

        metric_sql = {
            "event_diversity": """
                SELECT COALESCE(actor, 'unattributed') as actor,
                       COUNT(DISTINCT event) as value
                FROM events GROUP BY actor
            """,
            "volume": """
                SELECT COALESCE(actor, 'unattributed') as actor,
                       COUNT(*) as value
                FROM events GROUP BY actor
            """,
            "session_density": """
                SELECT actor, ROUND(AVG(event_count), 1) as value
                FROM sessions GROUP BY actor
            """,
            "session_duration": """
                SELECT actor, ROUND(AVG(duration_seconds), 1) as value
                FROM sessions GROUP BY actor
            """,
            "escalation_rate": """
                SELECT COALESCE(e.actor, 'unattributed') as actor,
                       ROUND(
                           SUM(CASE WHEN e.event IN (
                               'audit_generated', 'governance_generated',
                               'governance_config_changed', 'alert_dispatched'
                           ) THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2
                       ) as value
                FROM events e GROUP BY e.actor
            """,
            "cadence": """
                SELECT COALESCE(actor, 'unattributed') as actor,
                       ROUND(
                           COUNT(*) * 1.0 /
                           GREATEST(COUNT(DISTINCT DATE_TRUNC('day', ts)), 1),
                       1) as value
                FROM events GROUP BY actor
            """,
        }

        if metric not in metric_sql:
            return {
                "error": f"Unknown metric: {metric}",
                "available": list(metric_sql.keys()),
            }

        rows = self._conn.execute(f"""
            WITH ranked AS ({metric_sql[metric]})
            SELECT actor, value FROM ranked
            ORDER BY value DESC
            LIMIT {top_n}
        """).fetchall()

        if not rows:
            return {"error": "No data", "elapsed_ms": _now_ms() - start}

        values = [r[1] for r in rows if r[1] is not None]
        avg_val = sum(values) / len(values) if values else 0
        min_val = min(values) if values else 0
        max_val = max(values) if values else 0

        # Flag outliers (>2x median)
        sorted_vals = sorted(values)
        median = sorted_vals[len(sorted_vals) // 2] if sorted_vals else 0

        results = []
        for actor, value in rows:
            is_outlier = value > (median * 2) if median > 0 else False
            results.append({
                "actor": actor,
                "value": value,
                "outlier": is_outlier,
            })

        return {
            "metric": metric,
            "rankings": results,
            "stats": {
                "mean": round(avg_val, 2),
                "median": median,
                "min": min_val,
                "max": max_val,
                "count": len(values),
            },
            "elapsed_ms": _now_ms() - start,
        }

    # -- Lens: Timeline ------------------------------------------------------

    def timeline(self, period="30d", actor_prefix=None, signer_prefix=None,
                 granularity="day"):
        """Activity density over time.

        Args:
            period: Lookback period — "7d", "30d", "90d", "all".
            actor_prefix: Optional actor filter.
            signer_prefix: Optional signer filter.
            granularity: "hour", "day", "week", "month".

        Returns:
            dict with time buckets, event type breakdown, and trend.
        """
        start = _now_ms()
        where_parts = []
        params = []

        if period != "all":
            days = int(period.rstrip("d"))
            where_parts.append(f"ts >= CURRENT_TIMESTAMP - INTERVAL '{days} days'")

        actor_where, actor_params = self._build_actor_filter(
            actor_prefix, signer_prefix
        )
        if actor_where:
            # Strip the leading "WHERE "
            where_parts.append(actor_where.replace("WHERE ", ""))
            params.extend(actor_params)

        where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        trunc_map = {
            "hour": "hour",
            "day": "day",
            "week": "week",
            "month": "month",
        }
        trunc = trunc_map.get(granularity, "day")

        # Overall volume by time bucket
        buckets = self._conn.execute(f"""
            SELECT DATE_TRUNC('{trunc}', ts) as bucket, COUNT(*) as cnt
            FROM events {where_clause}
            GROUP BY DATE_TRUNC('{trunc}', ts)
            ORDER BY bucket
        """, params).fetchall()

        # Event type breakdown per bucket (top 5 event types)
        top_events = self._conn.execute(f"""
            SELECT event FROM events {where_clause}
            GROUP BY event ORDER BY COUNT(*) DESC LIMIT 5
        """, params).fetchall()
        top_event_names = [r[0] for r in top_events]

        type_breakdown = {}
        for evt in top_event_names:
            evt_params = params + [evt]
            evt_where = where_clause
            if evt_where:
                evt_where += " AND event = ?"
            else:
                evt_where = "WHERE event = ?"

            rows = self._conn.execute(f"""
                SELECT DATE_TRUNC('{trunc}', ts) as bucket, COUNT(*) as cnt
                FROM events {evt_where}
                GROUP BY DATE_TRUNC('{trunc}', ts)
                ORDER BY bucket
            """, evt_params).fetchall()
            type_breakdown[evt] = [
                {"bucket": str(b), "count": c} for b, c in rows
            ]

        # Trend: compare first half vs second half of period
        total_count = sum(c for _, c in buckets)
        if len(buckets) >= 2:
            mid = len(buckets) // 2
            first_half = sum(c for _, c in buckets[:mid])
            second_half = sum(c for _, c in buckets[mid:])
            if first_half > 0:
                trend_pct = round((second_half - first_half) / first_half * 100, 1)
            else:
                trend_pct = 100.0 if second_half > 0 else 0.0

            if trend_pct > 10:
                trend = "increasing"
            elif trend_pct < -10:
                trend = "decreasing"
            else:
                trend = "stable"
        else:
            trend_pct = 0.0
            trend = "insufficient_data"

        return {
            "period": period,
            "granularity": granularity,
            "buckets": [
                {"time": str(b), "count": c} for b, c in buckets
            ],
            "type_breakdown": type_breakdown,
            "total_events": total_count,
            "trend": trend,
            "trend_pct": trend_pct,
            "elapsed_ms": _now_ms() - start,
        }

    # -- Lens: Flow ----------------------------------------------------------

    def flow(self, event, depth=2, min_count=1):
        """What happens before and after a given event type?

        Args:
            event: The event type to analyze.
            depth: How many steps before/after to trace (1-5).
            min_count: Minimum transition count to include.

        Returns:
            dict with predecessors, successors, common sequences,
            and average timing.
        """
        start = _now_ms()
        depth = max(1, min(depth, 5))

        # Direct predecessors (events that immediately precede this event)
        predecessors = self._conn.execute("""
            SELECT e1.event as predecessor, COUNT(*) as cnt,
                   ROUND(AVG(EPOCH(e2.ts) - EPOCH(e1.ts)), 1) as avg_gap_s
            FROM events e1
            JOIN events e2 ON e2.idx = e1.idx + 1
            WHERE e2.event = ?
            GROUP BY e1.event
            HAVING COUNT(*) >= ?
            ORDER BY cnt DESC LIMIT 15
        """, [event, min_count]).fetchall()

        # Direct successors (events that immediately follow this event)
        successors = self._conn.execute("""
            SELECT e2.event as successor, COUNT(*) as cnt,
                   ROUND(AVG(EPOCH(e2.ts) - EPOCH(e1.ts)), 1) as avg_gap_s
            FROM events e1
            JOIN events e2 ON e2.idx = e1.idx + 1
            WHERE e1.event = ?
            GROUP BY e2.event
            HAVING COUNT(*) >= ?
            ORDER BY cnt DESC LIMIT 15
        """, [event, min_count]).fetchall()

        # Multi-step sequences (up to depth)
        sequences = self._find_sequences(event, depth, min_count)

        # Event frequency and timing stats
        stats = self._conn.execute("""
            SELECT
                COUNT(*) as occurrences,
                MIN(ts) as first_occurrence,
                MAX(ts) as last_occurrence,
                COUNT(DISTINCT DATE_TRUNC('day', ts)) as active_days,
                COUNT(DISTINCT COALESCE(actor, 'unattributed')) as actors
            FROM events WHERE event = ?
        """, [event]).fetchone()

        # Average time between consecutive occurrences
        avg_interval = self._conn.execute("""
            SELECT ROUND(AVG(gap_s), 1) as avg_gap
            FROM (
                SELECT EPOCH(LEAD(ts) OVER (ORDER BY idx)) - EPOCH(ts) as gap_s
                FROM events WHERE event = ?
            ) WHERE gap_s IS NOT NULL
        """, [event]).fetchone()

        return {
            "event": event,
            "occurrences": stats[0],
            "first_seen": str(stats[1]) if stats[1] else None,
            "last_seen": str(stats[2]) if stats[2] else None,
            "active_days": stats[3],
            "actor_count": stats[4],
            "avg_interval_s": avg_interval[0] if avg_interval else None,
            "predecessors": [
                {"event": e, "count": c, "avg_gap_s": g}
                for e, c, g in predecessors
            ],
            "successors": [
                {"event": e, "count": c, "avg_gap_s": g}
                for e, c, g in successors
            ],
            "sequences": sequences,
            "elapsed_ms": _now_ms() - start,
        }

    def _find_sequences(self, event, depth, min_count):
        """Find common multi-step sequences around an event."""
        # Build sequences by looking at windows around each occurrence
        occurrences = self._conn.execute("""
            SELECT idx FROM events WHERE event = ? ORDER BY idx
        """, [event]).fetchall()

        if not occurrences:
            return []

        # Sample up to 500 occurrences for sequence mining
        sample_indices = [r[0] for r in occurrences[:500]]

        # For each occurrence, get the surrounding window
        sequence_counts = {}
        for center_idx in sample_indices:
            window = self._conn.execute("""
                SELECT event FROM events
                WHERE idx BETWEEN ? AND ?
                ORDER BY idx
            """, [center_idx - depth, center_idx + depth]).fetchall()

            seq = " → ".join(r[0] for r in window)
            sequence_counts[seq] = sequence_counts.get(seq, 0) + 1

        # Filter and sort
        sequences = [
            {"sequence": seq, "count": cnt}
            for seq, cnt in sorted(
                sequence_counts.items(), key=lambda x: -x[1]
            )
            if cnt >= min_count
        ]

        return sequences[:15]

    # -- Lens: Summary -------------------------------------------------------

    def summary(self):
        """Org-wide health dashboard in one call.

        Returns governance activity, chain health, actor stats,
        and recent highlights.
        """
        start = _now_ms()

        # Overall stats
        overview = self._conn.execute("""
            SELECT
                COUNT(*) as total_events,
                COUNT(DISTINCT event) as event_types,
                COUNT(DISTINCT COALESCE(actor, 'unattributed')) as actors,
                COUNT(DISTINCT signer) as signers,
                MIN(ts) as first_event,
                MAX(ts) as last_event,
                COUNT(DISTINCT DATE_TRUNC('day', ts)) as active_days
            FROM events
        """).fetchone()

        # Last 7 days vs prior 7 days
        recent_7d = self._conn.execute("""
            SELECT COUNT(*) FROM events
            WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '7 days'
        """).fetchone()[0]

        prior_7d = self._conn.execute("""
            SELECT COUNT(*) FROM events
            WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '14 days'
              AND ts < CURRENT_TIMESTAMP - INTERVAL '7 days'
        """).fetchone()[0]

        if prior_7d > 0:
            week_trend = round((recent_7d - prior_7d) / prior_7d * 100, 1)
        else:
            week_trend = 100.0 if recent_7d > 0 else 0.0

        # Governance health: audit frequency
        audit_count = self._conn.execute("""
            SELECT COUNT(*) FROM events WHERE event = 'audit_generated'
        """).fetchone()[0]

        governance_events = self._conn.execute("""
            SELECT COUNT(*) FROM events
            WHERE event IN (
                'governance_generated', 'governance_config_changed',
                'audit_generated', 'alert_dispatched'
            )
        """).fetchone()[0]

        # Chain integrity indicators
        gap_check = self._conn.execute("""
            SELECT COUNT(*) FROM (
                SELECT idx, LEAD(idx) OVER (ORDER BY idx) as next_idx
                FROM events
            ) WHERE next_idx IS NOT NULL AND next_idx != idx + 1
        """).fetchone()[0]

        # Session overview
        session_stats = self._conn.execute("""
            SELECT
                COUNT(*) as total_sessions,
                ROUND(AVG(event_count), 1) as avg_events,
                ROUND(AVG(duration_seconds), 1) as avg_duration_s,
                SUM(event_count) as total_session_events
            FROM sessions
        """).fetchone()

        # Event velocity (events per day, last 30 days)
        velocity = self._conn.execute("""
            SELECT ROUND(COUNT(*) * 1.0 /
                   GREATEST(COUNT(DISTINCT DATE_TRUNC('day', ts)), 1), 1)
            FROM events
            WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '30 days'
        """).fetchone()[0]

        # Top 5 most common events last 7 days
        recent_top = self._conn.execute("""
            SELECT event, COUNT(*) as cnt
            FROM events
            WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '7 days'
            GROUP BY event ORDER BY cnt DESC LIMIT 5
        """).fetchall()

        # Most recent events
        latest = self._conn.execute("""
            SELECT idx, ts, event, COALESCE(actor, 'unattributed') as actor
            FROM events ORDER BY idx DESC LIMIT 5
        """).fetchall()

        return {
            "overview": {
                "total_events": overview[0],
                "event_types": overview[1],
                "actors": overview[2],
                "signers": overview[3],
                "first_event": str(overview[4]),
                "last_event": str(overview[5]),
                "active_days": overview[6],
            },
            "velocity": {
                "events_per_day_30d": velocity,
                "last_7d": recent_7d,
                "prior_7d": prior_7d,
                "week_trend_pct": week_trend,
            },
            "governance": {
                "audit_count": audit_count,
                "governance_events": governance_events,
                "governance_pct": round(
                    governance_events * 100.0 / max(overview[0], 1), 2
                ),
            },
            "chain_health": {
                "index_gaps": gap_check,
                "status": "intact" if gap_check == 0 else "GAPS DETECTED",
            },
            "sessions": {
                "total": session_stats[0],
                "avg_events": session_stats[1],
                "avg_duration_s": session_stats[2],
            },
            "recent_top_events": [
                {"event": e, "count": c} for e, c in recent_top
            ],
            "latest_events": [
                {"index": i, "ts": str(t), "event": e, "actor": a}
                for i, t, e, a in latest
            ],
            "elapsed_ms": _now_ms() - start,
        }

    # -- Lens: Search --------------------------------------------------------

    def search(self, term, limit=25):
        """Full-text search across event types and data payloads.

        Args:
            term: Search string (case-insensitive substring match).
            limit: Max results to return.

        Returns:
            dict with matching events.
        """
        start = _now_ms()
        pattern = f"%{term}%"

        rows = self._conn.execute("""
            SELECT idx, ts, event, COALESCE(actor, 'unattributed') as actor,
                   SUBSTRING(data_json, 1, 120) as data_preview
            FROM events
            WHERE event ILIKE ? OR data_json ILIKE ?
            ORDER BY idx DESC
            LIMIT ?
        """, [pattern, pattern, limit]).fetchall()

        return {
            "term": term,
            "results": [
                {"index": i, "ts": str(t), "event": e, "actor": a, "data": d}
                for i, t, e, a, d in rows
            ],
            "count": len(rows),
            "elapsed_ms": _now_ms() - start,
        }

    # -- Helpers -------------------------------------------------------------

    def _build_actor_filter(self, actor_prefix=None, signer_prefix=None):
        """Build a WHERE clause for actor/signer prefix matching."""
        parts = []
        params = []
        if actor_prefix:
            parts.append("COALESCE(actor, 'unattributed') ILIKE ?")
            params.append(f"{actor_prefix}%")
        if signer_prefix:
            parts.append("signer LIKE ?")
            params.append(f"{signer_prefix}%")

        if not parts:
            return "", []
        return "WHERE " + " AND ".join(parts), params


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_query_cli(args):
    """CLI dispatcher for query-based analytics actions."""
    action = getattr(args, "action", None)

    if action == "profile":
        actor = getattr(args, "actor", None)
        signer = getattr(args, "signer", None)
        if not actor and not signer:
            print("Usage: charter analytics profile [--actor X | --signer X]")
            return
        qe = QueryEngine()
        try:
            result = qe.actor_profile(
                actor_prefix=actor, signer_prefix=signer
            )
            _print_profile(result)
        finally:
            qe.close()

    elif action == "compare":
        metric = getattr(args, "metric", "event_diversity")
        qe = QueryEngine()
        try:
            result = qe.compare(metric=metric)
            _print_compare(result)
        finally:
            qe.close()

    elif action == "timeline":
        period = getattr(args, "period", "30d")
        granularity = getattr(args, "granularity", "day")
        qe = QueryEngine()
        try:
            result = qe.timeline(period=period, granularity=granularity)
            _print_timeline(result)
        finally:
            qe.close()

    elif action == "flow":
        event = getattr(args, "event", None)
        if not event:
            print("Usage: charter analytics flow --event <event_type>")
            return
        depth = getattr(args, "depth", 2)
        qe = QueryEngine()
        try:
            result = qe.flow(event=event, depth=depth)
            _print_flow(result)
        finally:
            qe.close()

    elif action == "summary":
        qe = QueryEngine()
        try:
            result = qe.summary()
            _print_summary(result)
        finally:
            qe.close()

    elif action == "search":
        term = getattr(args, "term", None)
        if not term:
            print("Usage: charter analytics search <term>")
            return
        qe = QueryEngine()
        try:
            result = qe.search(term=term)
            _print_search(result)
        finally:
            qe.close()

    else:
        print(f"Unknown query action: {action}")


# ---------------------------------------------------------------------------
# Pretty printers
# ---------------------------------------------------------------------------

def _print_profile(r):
    if "error" in r:
        print(r["error"])
        return

    print(f"Charter Analytics — Actor Profile")
    print(f"{'=' * 50}")
    print(f"  Actor:            {r['actor']}")
    print(f"  Signer:           {r['signer'] or 'none'}")
    print(f"  Total events:     {r['total_events']:,}")
    print(f"  Event types:      {r['unique_event_types']}")
    print(f"  First seen:       {r['first_seen']}")
    print(f"  Last seen:        {r['last_seen']}")
    print(f"  Active days:      {r['active_days']}")
    print(f"  Events/day:       {r['events_per_day']}")
    print()

    s = r["sessions"]
    print(f"  Sessions:         {s['count']}")
    print(f"  Avg events/sess:  {s['avg_events']}")
    print(f"  Avg duration:     {s['avg_duration_s']}s")
    print()

    print(f"  Event breakdown:")
    for e in r["event_breakdown"][:10]:
        bar = "#" * max(1, int(e["pct"] / 3))
        print(f"    {e['count']:>6,}  ({e['pct']:>5.1f}%)  {e['event']}  {bar}")
    print()

    if r["top_transitions"]:
        print(f"  Top transitions:")
        for t in r["top_transitions"]:
            print(f"    {t['from']:>35s} → {t['to']:<30s}  x{t['count']}  ({t['avg_gap_s']}s)")
    print()

    if r["hourly_distribution"]:
        print(f"  Hourly activity:")
        max_h = max(h["count"] for h in r["hourly_distribution"])
        for h in r["hourly_distribution"]:
            bar = "#" * max(1, int(h["count"] / max(max_h, 1) * 30))
            print(f"    {h['hour']:>2d}:00  {h['count']:>5,}  {bar}")
    print()
    print(f"  ({r['elapsed_ms']}ms)")


def _print_compare(r):
    if "error" in r:
        print(r["error"])
        return

    print(f"Charter Analytics — Compare: {r['metric']}")
    print(f"{'=' * 50}")
    s = r["stats"]
    print(f"  Mean: {s['mean']}  Median: {s['median']}  "
          f"Min: {s['min']}  Max: {s['max']}")
    print()
    for i, entry in enumerate(r["rankings"], 1):
        flag = " ** OUTLIER" if entry["outlier"] else ""
        label = entry["actor"]
        if len(label) > 20:
            label = label[:16] + "..."
        print(f"  {i:>3}. {label:<22s}  {entry['value']}{flag}")
    print()
    print(f"  ({r['elapsed_ms']}ms)")


def _print_timeline(r):
    print(f"Charter Analytics — Timeline ({r['period']}, {r['granularity']})")
    print(f"{'=' * 50}")
    print(f"  Total events:  {r['total_events']:,}")
    print(f"  Trend:         {r['trend']} ({r['trend_pct']:+.1f}%)")
    print()

    if r["buckets"]:
        max_c = max(b["count"] for b in r["buckets"])
        for b in r["buckets"]:
            bar = "#" * max(1, int(b["count"] / max(max_c, 1) * 40))
            print(f"  {b['time'][:16]}  {b['count']:>6,}  {bar}")
    print()
    print(f"  ({r['elapsed_ms']}ms)")


def _print_flow(r):
    print(f"Charter Analytics — Flow: {r['event']}")
    print(f"{'=' * 50}")
    print(f"  Occurrences:     {r['occurrences']:,}")
    print(f"  First seen:      {r['first_seen']}")
    print(f"  Last seen:       {r['last_seen']}")
    print(f"  Active days:     {r['active_days']}")
    print(f"  Actors:          {r['actor_count']}")
    if r["avg_interval_s"] is not None:
        print(f"  Avg interval:    {r['avg_interval_s']}s")
    print()

    if r["predecessors"]:
        print(f"  What happens BEFORE {r['event']}:")
        for p in r["predecessors"]:
            print(f"    {p['event']:<40s}  x{p['count']:<4}  gap: {p['avg_gap_s']}s")
    print()

    if r["successors"]:
        print(f"  What happens AFTER {r['event']}:")
        for s in r["successors"]:
            print(f"    {s['event']:<40s}  x{s['count']:<4}  gap: {s['avg_gap_s']}s")
    print()

    if r["sequences"]:
        print(f"  Common sequences:")
        for seq in r["sequences"][:10]:
            print(f"    x{seq['count']:<4}  {seq['sequence']}")
    print()
    print(f"  ({r['elapsed_ms']}ms)")


def _print_summary(r):
    o = r["overview"]
    v = r["velocity"]
    g = r["governance"]
    ch = r["chain_health"]
    s = r["sessions"]

    print(f"Charter Analytics — Organization Summary")
    print(f"{'=' * 50}")
    print()
    print(f"  Chain:        {o['total_events']:,} events | "
          f"{o['event_types']} types | {o['actors']} actors | "
          f"{o['active_days']} active days")
    print(f"  Time span:    {o['first_event'][:10]} → {o['last_event'][:10]}")
    print(f"  Chain health: {ch['status'].upper()}"
          f"{'  (' + str(ch['index_gaps']) + ' gaps)' if ch['index_gaps'] else ''}")
    print()
    print(f"  Velocity:     {v['events_per_day_30d']} events/day (30d avg)")
    print(f"  Last 7d:      {v['last_7d']:,} events "
          f"({v['week_trend_pct']:+.1f}% vs prior week)")
    print()
    print(f"  Governance:   {g['governance_events']:,} events "
          f"({g['governance_pct']:.1f}% of total)")
    print(f"  Audits:       {g['audit_count']}")
    print()
    print(f"  Sessions:     {s['total']:,} | "
          f"avg {s['avg_events']} events | "
          f"avg {s['avg_duration_s']}s duration")
    print()

    if r["recent_top_events"]:
        print(f"  Top events (7d):")
        for e in r["recent_top_events"]:
            print(f"    {e['count']:>6,}  {e['event']}")
    print()

    if r["latest_events"]:
        print(f"  Latest:")
        for e in r["latest_events"]:
            print(f"    [{e['index']}] {e['ts'][:19]}  {e['event']}  ({e['actor']})")
    print()
    print(f"  ({r['elapsed_ms']}ms)")


def _print_search(r):
    print(f"Charter Analytics — Search: \"{r['term']}\"")
    print(f"{'=' * 50}")
    print(f"  Found: {r['count']} results")
    print()
    for e in r["results"]:
        print(f"  [{e['index']}] {e['ts'][:19]}  {e['event']}  ({e['actor']})")
        if e["data"]:
            print(f"         {e['data']}")
    print()
