"""Pattern engine — sequence mining, anomaly detection, causal discovery.

Extracts behavioral patterns from the Charter analytics store.
Designed for organizational learning: which approaches lead to
better outcomes, and who is doing things differently?

Engines:
    SequenceMiner   — Find frequent event subsequences across actors
    CohortAnalyzer  — Statistical comparison between actor groups
    AnomalyDetector — Flag behavioral deviations from baselines
    CausalEngine    — Link event patterns to outcome differences

Usage:
    from charter.analytics.patterns import PatternEngine
    pe = PatternEngine()
    frequent = pe.mine_sequences(min_support=3)
    anomalies = pe.detect_anomalies()
    cohorts = pe.compare_cohorts(group_by="actor")
"""

import math
from collections import Counter, defaultdict

from charter.analytics.indexer import Indexer, _now_ms

# Optional heavy dependencies — degrade gracefully
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    np = None
    HAS_NUMPY = False

try:
    from scipy import stats as sp_stats
    HAS_SCIPY = True
except ImportError:
    sp_stats = None
    HAS_SCIPY = False


# ---------------------------------------------------------------------------
# Pattern Engine (main interface)
# ---------------------------------------------------------------------------

class PatternEngine:
    """Unified interface to all pattern discovery engines.

    Auto-syncs the DuckDB index on construction.

    Args:
        indexer: Optional Indexer to reuse.
        auto_sync: Sync index on init (default True).
    """

    def __init__(self, indexer=None, auto_sync=True):
        self._indexer = indexer or Indexer()
        self._conn = self._indexer.connect()
        if auto_sync:
            self._indexer.sync()

    def close(self):
        self._indexer.close()

    # -- Sequence Mining -----------------------------------------------------

    def mine_sequences(self, min_support=2, max_length=5,
                       actor=None, event_filter=None):
        """Find frequent event subsequences across sessions.

        Uses a PrefixSpan-inspired algorithm on session event sequences.

        Args:
            min_support: Minimum number of sessions containing the pattern.
            max_length: Maximum subsequence length to mine.
            actor: Optional actor filter.
            event_filter: Optional list of event types to include.

        Returns:
            dict with frequent_patterns, pattern_stats, and mining metadata.
        """
        start = _now_ms()
        sessions = self._get_session_sequences(actor, event_filter)

        if not sessions:
            return {"error": "No sessions found", "elapsed_ms": _now_ms() - start}

        # Mine frequent subsequences
        patterns = _mine_prefixspan(sessions, min_support, max_length)

        # Enrich patterns with timing data
        enriched = []
        for seq, support, session_ids in patterns:
            enriched.append({
                "sequence": list(seq),
                "display": " → ".join(seq),
                "length": len(seq),
                "support": support,
                "support_pct": round(support / len(sessions) * 100, 1),
                "session_ids": session_ids[:10],
            })

        # Summary stats
        by_length = defaultdict(int)
        for p in enriched:
            by_length[p["length"]] += 1

        return {
            "total_sessions": len(sessions),
            "total_patterns": len(enriched),
            "patterns_by_length": dict(by_length),
            "patterns": enriched,
            "min_support": min_support,
            "max_length": max_length,
            "elapsed_ms": _now_ms() - start,
        }

    # -- Cohort Comparison ---------------------------------------------------

    def compare_cohorts(self, group_by="actor", metrics=None):
        """Compare behavioral metrics across actor groups.

        Computes per-actor metrics and runs statistical tests
        to identify significant differences between groups.

        Args:
            group_by: How to group actors ("actor" or "signer").
            metrics: List of metrics to compare. Default: all.
                     Options: volume, diversity, session_length,
                     session_count, escalation_rate, cadence,
                     avg_gap, peak_hour

        Returns:
            dict with per-actor metrics, group stats, and
            statistical test results.
        """
        start = _now_ms()
        if metrics is None:
            metrics = [
                "volume", "diversity", "session_length",
                "session_count", "escalation_rate", "cadence",
                "avg_gap", "peak_hour",
            ]

        # Compute per-actor metrics
        actor_metrics = self._compute_actor_metrics(group_by)

        if len(actor_metrics) < 2:
            return {
                "actors": actor_metrics,
                "note": "Need at least 2 actors for comparison",
                "elapsed_ms": _now_ms() - start,
            }

        # Statistical summary per metric
        metric_stats = {}
        for metric in metrics:
            values = [
                a["metrics"].get(metric, 0)
                for a in actor_metrics
                if a["metrics"].get(metric) is not None
            ]
            if not values:
                continue

            stat = _describe(values)

            # Flag outliers (beyond 2 std deviations)
            outliers = []
            if stat["std"] > 0:
                for a in actor_metrics:
                    v = a["metrics"].get(metric, 0)
                    z = (v - stat["mean"]) / stat["std"]
                    if abs(z) > 2:
                        outliers.append({
                            "actor": a["actor"],
                            "value": v,
                            "z_score": round(z, 2),
                            "direction": "high" if z > 0 else "low",
                        })

            metric_stats[metric] = {
                **stat,
                "outliers": outliers,
            }

        # Pairwise comparison if exactly 2 groups
        pairwise = None
        if len(actor_metrics) == 2:
            pairwise = self._pairwise_compare(
                actor_metrics[0], actor_metrics[1], metrics
            )

        return {
            "group_by": group_by,
            "actor_count": len(actor_metrics),
            "actors": actor_metrics,
            "metric_stats": metric_stats,
            "pairwise": pairwise,
            "elapsed_ms": _now_ms() - start,
        }

    # -- Anomaly Detection ---------------------------------------------------

    def detect_anomalies(self, lookback_days=7, baseline_days=30,
                         sensitivity=2.0):
        """Detect behavioral anomalies by comparing recent activity
        to historical baselines.

        For each actor, computes metrics over the baseline period,
        then checks if the lookback period deviates significantly.

        Args:
            lookback_days: Recent window to check for anomalies.
            baseline_days: Historical window for establishing baselines.
            sensitivity: Z-score threshold for flagging (default 2.0).

        Returns:
            dict with anomalies per actor and global anomalies.
        """
        start = _now_ms()

        # Get per-actor metrics for baseline and lookback periods
        baseline_metrics = self._compute_period_metrics(
            baseline_days, offset_days=lookback_days
        )
        recent_metrics = self._compute_period_metrics(lookback_days)

        anomalies = []
        for actor, recent in recent_metrics.items():
            baseline = baseline_metrics.get(actor)
            if not baseline:
                # New actor — flag as new, not anomalous
                anomalies.append({
                    "actor": actor,
                    "type": "new_actor",
                    "detail": "Actor appeared in lookback but not baseline",
                    "severity": "info",
                })
                continue

            # Compare each metric
            for metric in recent:
                if metric not in baseline:
                    continue

                b_val = baseline[metric]
                r_val = recent[metric]

                if b_val == 0 and r_val == 0:
                    continue

                # Use ratio-based detection for small baselines
                if b_val > 0:
                    ratio = r_val / b_val
                    # Normalize for period length difference
                    period_ratio = lookback_days / max(baseline_days, 1)
                    normalized_ratio = ratio / period_ratio if period_ratio > 0 else ratio

                    if normalized_ratio > (1 + sensitivity) or normalized_ratio < max(1 - sensitivity * 0.5, 0):
                        direction = "spike" if normalized_ratio > 1 else "drop"
                        severity = "warning" if abs(normalized_ratio - 1) > sensitivity else "info"

                        anomalies.append({
                            "actor": actor,
                            "type": f"metric_{direction}",
                            "metric": metric,
                            "baseline_value": round(b_val, 2),
                            "recent_value": round(r_val, 2),
                            "change_ratio": round(normalized_ratio, 2),
                            "direction": direction,
                            "severity": severity,
                        })

        # Global anomalies: event types that appeared/disappeared
        global_anomalies = self._detect_event_anomalies(
            lookback_days, baseline_days
        )

        return {
            "lookback_days": lookback_days,
            "baseline_days": baseline_days,
            "sensitivity": sensitivity,
            "actor_anomalies": anomalies,
            "global_anomalies": global_anomalies,
            "total_anomalies": len(anomalies) + len(global_anomalies),
            "elapsed_ms": _now_ms() - start,
        }

    # -- Causal Discovery (foundation) --------------------------------------

    def discover_causes(self, target_event, min_occurrences=3,
                        window_size=5):
        """Find events that statistically precede a target event
        more often than chance.

        This is the foundation for causal discovery. It computes:
        - Conditional probability: P(target | predecessor)
        - Lift: how much more likely target is after predecessor
          vs. base rate
        - Temporal consistency: is the timing stable?

        Args:
            target_event: The outcome event to explain.
            min_occurrences: Minimum co-occurrences to report.
            window_size: How many events before target to examine.

        Returns:
            dict with candidate causes ranked by lift,
            timing analysis, and sequence context.
        """
        start = _now_ms()

        # Base rate: how often does target appear per event?
        total_events = self._conn.execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]

        target_count = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE event = ?",
            [target_event],
        ).fetchone()[0]

        if target_count == 0:
            return {
                "error": f"Event '{target_event}' not found",
                "elapsed_ms": _now_ms() - start,
            }

        base_rate = target_count / max(total_events, 1)

        # Find all target event indices
        target_indices = self._conn.execute(
            "SELECT idx FROM events WHERE event = ? ORDER BY idx",
            [target_event],
        ).fetchall()
        target_idxs = [r[0] for r in target_indices]

        # For each target, look at the window before it
        predecessor_counts = Counter()  # event → count of times it precedes target
        predecessor_gaps = defaultdict(list)  # event → list of gap_seconds
        predecessor_positions = defaultdict(list)  # event → positions relative to target

        for t_idx in target_idxs:
            window_start = max(0, t_idx - window_size)
            window = self._conn.execute("""
                SELECT idx, ts, event FROM events
                WHERE idx >= ? AND idx < ?
                ORDER BY idx
            """, [window_start, t_idx]).fetchall()

            for w_idx, w_ts, w_event in window:
                if w_event == target_event:
                    continue
                predecessor_counts[w_event] += 1
                predecessor_positions[w_event].append(t_idx - w_idx)

                # Get target timestamp for gap calculation
                t_ts = self._conn.execute(
                    "SELECT ts FROM events WHERE idx = ?", [t_idx]
                ).fetchone()
                if t_ts and w_ts:
                    gap = (t_ts[0] - w_ts).total_seconds()
                    predecessor_gaps[w_event].append(gap)

        # Compute lift for each predecessor
        candidates = []
        for event, count in predecessor_counts.items():
            if count < min_occurrences:
                continue

            # How often does this event appear overall?
            event_total = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE event = ?",
                [event],
            ).fetchone()[0]

            # P(target in window | predecessor) ≈ count / event_total
            conditional_prob = count / max(event_total, 1)

            # Lift = conditional_prob / base_rate
            lift = conditional_prob / base_rate if base_rate > 0 else 0

            # Timing stats
            gaps = predecessor_gaps.get(event, [])
            positions = predecessor_positions.get(event, [])

            timing = {}
            if gaps:
                timing = {
                    "avg_gap_s": round(sum(gaps) / len(gaps), 1),
                    "min_gap_s": round(min(gaps), 1),
                    "max_gap_s": round(max(gaps), 1),
                    "std_gap_s": round(_std(gaps), 1),
                }

            position_stats = {}
            if positions:
                position_stats = {
                    "avg_position": round(sum(positions) / len(positions), 1),
                    "most_common_position": Counter(positions).most_common(1)[0][0],
                }

            candidates.append({
                "event": event,
                "co_occurrences": count,
                "event_total": event_total,
                "conditional_prob": round(conditional_prob, 4),
                "base_rate": round(base_rate, 6),
                "lift": round(lift, 2),
                "timing": timing,
                "position": position_stats,
                "strength": _causal_strength(lift, count, timing.get("std_gap_s", 999)),
            })

        # Sort by causal strength score
        candidates.sort(key=lambda c: c["strength"], reverse=True)

        # Find common full sequences leading to target
        sequences = self._find_target_sequences(target_event, window_size)

        return {
            "target_event": target_event,
            "target_count": target_count,
            "base_rate": round(base_rate, 6),
            "window_size": window_size,
            "candidates": candidates[:20],
            "common_lead_sequences": sequences[:10],
            "elapsed_ms": _now_ms() - start,
        }

    # -- Behavioral Fingerprint ----------------------------------------------

    def fingerprint(self, actor=None):
        """Generate a behavioral fingerprint for an actor or the org.

        A fingerprint is a normalized vector of behavioral metrics
        that characterizes *how* someone works, not just *what* they do.

        Returns:
            dict with fingerprint vector, dominant traits, and
            similarity to other actors.
        """
        start = _now_ms()
        metrics = self._compute_actor_metrics("actor")

        if actor:
            target = None
            for m in metrics:
                if m["actor"] == actor or m["actor"].startswith(str(actor)):
                    target = m
                    break
            if not target:
                return {"error": f"Actor '{actor}' not found",
                        "elapsed_ms": _now_ms() - start}
        else:
            # Org-wide fingerprint: aggregate all actors
            target = self._aggregate_metrics(metrics)

        # Build fingerprint vector
        fp = self._build_fingerprint(target)

        # Compute similarity to other actors
        similarities = []
        if actor and len(metrics) > 1:
            target_vec = list(fp["vector"].values())
            for m in metrics:
                if m["actor"] == target["actor"]:
                    continue
                other_fp = self._build_fingerprint(m)
                other_vec = list(other_fp["vector"].values())
                sim = _cosine_similarity(target_vec, other_vec)
                similarities.append({
                    "actor": m["actor"],
                    "similarity": round(sim, 3),
                })
            similarities.sort(key=lambda s: s["similarity"], reverse=True)

        return {
            "actor": target.get("actor", "organization"),
            "fingerprint": fp,
            "similar_actors": similarities,
            "elapsed_ms": _now_ms() - start,
        }

    # -----------------------------------------------------------------------
    # Internal: data extraction
    # -----------------------------------------------------------------------

    def _get_session_sequences(self, actor=None, event_filter=None):
        """Extract event sequences from sessions table."""
        where_parts = []
        params = []
        if actor:
            where_parts.append("actor LIKE ?")
            params.append(f"{actor}%")

        where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        rows = self._conn.execute(f"""
            SELECT session_id, events FROM sessions
            {where} ORDER BY session_id
        """, params).fetchall()

        import json
        sessions = []
        for sid, events_json in rows:
            try:
                events = json.loads(events_json)
            except (json.JSONDecodeError, TypeError):
                continue

            if event_filter:
                events = [e for e in events if e in event_filter]

            if len(events) >= 2:
                sessions.append((sid, events))

        return sessions

    def _compute_actor_metrics(self, group_by="actor"):
        """Compute behavioral metrics for each actor."""
        group_col = "COALESCE(actor, 'unattributed')" if group_by == "actor" else "signer"

        rows = self._conn.execute(f"""
            SELECT
                {group_col} as grp,
                COUNT(*) as volume,
                COUNT(DISTINCT event) as diversity,
                COUNT(DISTINCT DATE_TRUNC('day', ts)) as active_days,
                SUM(CASE WHEN event IN (
                    'audit_generated', 'governance_generated',
                    'governance_config_changed', 'alert_dispatched'
                ) THEN 1 ELSE 0 END) as governance_events,
                MIN(ts) as first_ts,
                MAX(ts) as last_ts
            FROM events
            GROUP BY {group_col}
        """).fetchall()

        actors = []
        for grp, volume, diversity, active_days, gov_events, first_ts, last_ts in rows:
            # Session metrics
            actor_key = grp if grp != "unattributed" else "__unattributed__"
            sess = self._conn.execute("""
                SELECT COUNT(*), AVG(event_count), AVG(duration_seconds)
                FROM sessions WHERE actor = ?
            """, [actor_key]).fetchone()

            # Average gap between consecutive events
            avg_gap = self._conn.execute(f"""
                SELECT AVG(gap) FROM (
                    SELECT EPOCH(LEAD(ts) OVER (ORDER BY idx)) - EPOCH(ts) as gap
                    FROM events WHERE {group_col} = ?
                ) WHERE gap IS NOT NULL AND gap > 0 AND gap < 86400
            """, [grp]).fetchone()[0]

            # Peak hour
            peak = self._conn.execute(f"""
                SELECT EXTRACT(HOUR FROM ts) as h, COUNT(*) as c
                FROM events WHERE {group_col} = ?
                GROUP BY h ORDER BY c DESC LIMIT 1
            """, [grp]).fetchone()

            actors.append({
                "actor": grp,
                "metrics": {
                    "volume": volume,
                    "diversity": diversity,
                    "active_days": active_days,
                    "session_count": sess[0] if sess else 0,
                    "session_length": round(sess[1], 1) if sess and sess[1] else 0,
                    "session_duration": round(sess[2], 1) if sess and sess[2] else 0,
                    "escalation_rate": round(
                        gov_events / max(volume, 1) * 100, 2
                    ),
                    "cadence": round(volume / max(active_days, 1), 1),
                    "avg_gap": round(avg_gap, 1) if avg_gap else 0,
                    "peak_hour": int(peak[0]) if peak else 0,
                },
                "first_seen": str(first_ts),
                "last_seen": str(last_ts),
            })

        return actors

    def _compute_period_metrics(self, days, offset_days=0):
        """Compute per-actor metrics for a specific time window."""
        if offset_days > 0:
            where = (
                f"ts >= CURRENT_TIMESTAMP - INTERVAL '{days + offset_days} days' "
                f"AND ts < CURRENT_TIMESTAMP - INTERVAL '{offset_days} days'"
            )
        else:
            where = f"ts >= CURRENT_TIMESTAMP - INTERVAL '{days} days'"

        rows = self._conn.execute(f"""
            SELECT
                COALESCE(actor, 'unattributed') as actor,
                COUNT(*) as volume,
                COUNT(DISTINCT event) as diversity,
                COUNT(DISTINCT DATE_TRUNC('day', ts)) as active_days,
                SUM(CASE WHEN event IN (
                    'audit_generated', 'governance_generated',
                    'governance_config_changed', 'alert_dispatched'
                ) THEN 1 ELSE 0 END) as governance_events
            FROM events
            WHERE {where}
            GROUP BY actor
        """).fetchall()

        result = {}
        for actor, volume, diversity, active_days, gov in rows:
            result[actor] = {
                "volume": volume,
                "diversity": diversity,
                "active_days": active_days,
                "escalation_rate": round(gov / max(volume, 1) * 100, 2),
                "cadence": round(volume / max(active_days, 1), 1),
            }
        return result

    def _detect_event_anomalies(self, lookback_days, baseline_days):
        """Detect event types that appeared or disappeared."""
        baseline_events = set(r[0] for r in self._conn.execute(f"""
            SELECT DISTINCT event FROM events
            WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '{baseline_days + lookback_days} days'
              AND ts < CURRENT_TIMESTAMP - INTERVAL '{lookback_days} days'
        """).fetchall())

        recent_events = set(r[0] for r in self._conn.execute(f"""
            SELECT DISTINCT event FROM events
            WHERE ts >= CURRENT_TIMESTAMP - INTERVAL '{lookback_days} days'
        """).fetchall())

        anomalies = []
        new_events = recent_events - baseline_events
        for e in new_events:
            anomalies.append({
                "type": "new_event_type",
                "event": e,
                "severity": "info",
                "detail": f"Event '{e}' appeared in last {lookback_days}d "
                          f"but not in prior {baseline_days}d",
            })

        disappeared = baseline_events - recent_events
        for e in disappeared:
            anomalies.append({
                "type": "disappeared_event_type",
                "event": e,
                "severity": "warning",
                "detail": f"Event '{e}' was active in baseline but absent "
                          f"in last {lookback_days}d",
            })

        return anomalies

    def _find_target_sequences(self, target_event, window_size):
        """Find common event sequences leading to a target event."""
        target_indices = self._conn.execute(
            "SELECT idx FROM events WHERE event = ? ORDER BY idx",
            [target_event],
        ).fetchall()

        seq_counts = Counter()
        for (t_idx,) in target_indices[:200]:
            window = self._conn.execute("""
                SELECT event FROM events
                WHERE idx >= ? AND idx <= ?
                ORDER BY idx
            """, [max(0, t_idx - window_size), t_idx]).fetchall()

            seq = tuple(r[0] for r in window)
            if len(seq) >= 2:
                seq_counts[seq] += 1

        return [
            {"sequence": " → ".join(seq), "count": cnt}
            for seq, cnt in seq_counts.most_common(10)
            if cnt >= 2
        ]

    def _pairwise_compare(self, actor_a, actor_b, metrics):
        """Statistical comparison between exactly two actors."""
        results = {}
        for metric in metrics:
            a_val = actor_a["metrics"].get(metric, 0)
            b_val = actor_b["metrics"].get(metric, 0)
            if a_val == 0 and b_val == 0:
                continue

            diff = b_val - a_val
            pct_diff = round(diff / max(abs(a_val), 1) * 100, 1)

            results[metric] = {
                "actor_a": {"name": actor_a["actor"], "value": a_val},
                "actor_b": {"name": actor_b["actor"], "value": b_val},
                "difference": round(diff, 2),
                "pct_difference": pct_diff,
                "higher": actor_b["actor"] if diff > 0 else actor_a["actor"],
            }

        return results

    def _aggregate_metrics(self, actor_list):
        """Aggregate metrics across all actors for org fingerprint."""
        totals = defaultdict(float)
        count = len(actor_list)
        for a in actor_list:
            for k, v in a["metrics"].items():
                totals[k] += v

        return {
            "actor": "organization",
            "metrics": {
                k: round(v / max(count, 1), 2)
                for k, v in totals.items()
            },
        }

    def _build_fingerprint(self, actor_data):
        """Build a normalized behavioral fingerprint vector."""
        m = actor_data["metrics"]

        # Select fingerprint dimensions
        dims = {
            "breadth": min(m.get("diversity", 0) / 50, 1.0),
            "intensity": min(m.get("cadence", 0) / 500, 1.0),
            "focus": min(m.get("session_length", 0) / 200, 1.0),
            "endurance": min(m.get("session_duration", 0) / 3600, 1.0),
            "governance": min(m.get("escalation_rate", 0) / 100, 1.0),
            "consistency": 1.0 - min(m.get("avg_gap", 0) / 86400, 1.0),
        }

        # Dominant trait
        dominant = max(dims, key=dims.get) if dims else None

        return {
            "vector": {k: round(v, 3) for k, v in dims.items()},
            "dominant_trait": dominant,
            "dominant_value": round(dims.get(dominant, 0), 3) if dominant else 0,
        }


# ---------------------------------------------------------------------------
# Sequence Mining: PrefixSpan-inspired
# ---------------------------------------------------------------------------

def _mine_prefixspan(sessions, min_support, max_length):
    """Mine frequent subsequences using a simplified PrefixSpan.

    Args:
        sessions: List of (session_id, event_list) tuples.
        min_support: Minimum number of sessions containing pattern.
        max_length: Maximum pattern length.

    Returns:
        List of (pattern_tuple, support_count, session_ids).
    """
    # Build initial frequency of single items
    item_support = Counter()
    item_sessions = defaultdict(set)
    for sid, events in sessions:
        for e in set(events):
            item_support[e] += 1
            item_sessions[e].add(sid)

    # Filter by min_support
    frequent_items = {
        e for e, count in item_support.items()
        if count >= min_support
    }

    if not frequent_items:
        return []

    results = []

    # Add length-1 patterns
    for item in sorted(frequent_items):
        sids = list(item_sessions[item])
        results.append(((item,), len(sids), sids))

    # Build projected databases and extend
    if max_length >= 2:
        for item in sorted(frequent_items):
            prefix = (item,)
            projected = _project_database(sessions, prefix, frequent_items)
            _extend_prefix(
                prefix, projected, min_support, max_length,
                results, frequent_items, sessions,
            )

    # Sort by support descending, then length descending
    results.sort(key=lambda x: (-x[1], -len(x[0])))
    return results


def _project_database(sessions, prefix, frequent_items):
    """Build projected database for a prefix.

    Returns list of (session_id, suffix) where suffix is the
    events following the last occurrence of prefix in the session.
    """
    projected = []
    prefix_len = len(prefix)

    for sid, events in sessions:
        # Find all positions where prefix ends
        for i in range(prefix_len - 1, len(events)):
            match = True
            for j in range(prefix_len):
                if events[i - prefix_len + 1 + j] != prefix[j]:
                    match = False
                    break
            if match and i + 1 < len(events):
                suffix = [e for e in events[i + 1:] if e in frequent_items]
                if suffix:
                    projected.append((sid, suffix))
                break  # Only first match per session

    return projected


def _extend_prefix(prefix, projected, min_support, max_length,
                   results, frequent_items, sessions):
    """Recursively extend a prefix with frequent items."""
    if len(prefix) >= max_length:
        return

    # Count support for each possible extension
    extension_support = Counter()
    extension_sessions = defaultdict(set)

    for sid, suffix in projected:
        seen = set()
        for e in suffix:
            if e not in seen:
                extension_support[e] += 1
                extension_sessions[e].add(sid)
                seen.add(e)

    for ext_item in sorted(extension_support):
        if extension_support[ext_item] < min_support:
            continue

        new_prefix = prefix + (ext_item,)
        sids = list(extension_sessions[ext_item])
        results.append((new_prefix, len(sids), sids))

        # Recurse
        new_projected = _project_database(sessions, new_prefix, frequent_items)
        if new_projected:
            _extend_prefix(
                new_prefix, new_projected, min_support, max_length,
                results, frequent_items, sessions,
            )


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def _describe(values):
    """Basic descriptive statistics, no dependencies required."""
    n = len(values)
    if n == 0:
        return {"count": 0, "mean": 0, "median": 0, "std": 0,
                "min": 0, "max": 0, "p25": 0, "p75": 0}

    sorted_v = sorted(values)
    mean = sum(values) / n
    median = sorted_v[n // 2]
    variance = sum((x - mean) ** 2 for x in values) / max(n - 1, 1)
    std = math.sqrt(variance)

    p25 = sorted_v[max(n // 4, 0)]
    p75 = sorted_v[min(3 * n // 4, n - 1)]

    return {
        "count": n,
        "mean": round(mean, 2),
        "median": round(median, 2),
        "std": round(std, 2),
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "p25": round(p25, 2),
        "p75": round(p75, 2),
    }


def _std(values):
    """Standard deviation."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
    return math.sqrt(variance)


def _cosine_similarity(vec_a, vec_b):
    """Cosine similarity between two vectors."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0

    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))

    if mag_a == 0 or mag_b == 0:
        return 0.0

    return dot / (mag_a * mag_b)


def _causal_strength(lift, count, timing_std):
    """Composite causal strength score.

    Higher lift + higher count + lower timing variance = stronger signal.
    """
    # Log-scaled count (diminishing returns above ~10)
    count_score = math.log(max(count, 1) + 1)

    # Timing consistency (lower std = more consistent = stronger)
    timing_score = 1.0 / (1.0 + timing_std / 60.0)

    # Lift already captures conditional probability advantage
    return round(lift * count_score * timing_score, 3)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_patterns_cli(args):
    """CLI dispatcher for pattern discovery actions."""
    action = getattr(args, "action", None)

    if action == "sequences":
        min_support = getattr(args, "min_support", 2)
        max_length = getattr(args, "max_length", 5)
        pe = PatternEngine()
        try:
            result = pe.mine_sequences(
                min_support=min_support, max_length=max_length
            )
            _print_sequences(result)
        finally:
            pe.close()

    elif action == "anomalies":
        lookback = getattr(args, "lookback", 7)
        baseline = getattr(args, "baseline", 30)
        pe = PatternEngine()
        try:
            result = pe.detect_anomalies(
                lookback_days=lookback, baseline_days=baseline
            )
            _print_anomalies(result)
        finally:
            pe.close()

    elif action == "cohorts":
        pe = PatternEngine()
        try:
            result = pe.compare_cohorts()
            _print_cohorts(result)
        finally:
            pe.close()

    elif action == "causes":
        event = getattr(args, "event", None)
        if not event:
            print("Usage: charter analytics causes --event <event_type>")
            return
        window = getattr(args, "window", 5)
        pe = PatternEngine()
        try:
            result = pe.discover_causes(
                target_event=event, window_size=window
            )
            _print_causes(result)
        finally:
            pe.close()

    elif action == "fingerprint":
        actor = getattr(args, "actor", None)
        pe = PatternEngine()
        try:
            result = pe.fingerprint(actor=actor)
            _print_fingerprint(result)
        finally:
            pe.close()

    else:
        print(f"Unknown pattern action: {action}")


# ---------------------------------------------------------------------------
# Pretty printers
# ---------------------------------------------------------------------------

def _print_sequences(r):
    if "error" in r:
        print(r["error"])
        return

    print("Charter Analytics — Sequence Mining")
    print("=" * 50)
    print(f"  Sessions analyzed: {r['total_sessions']}")
    print(f"  Patterns found:    {r['total_patterns']}")
    print(f"  Min support:       {r['min_support']}")
    print()

    if r["patterns_by_length"]:
        print("  Patterns by length:")
        for length, count in sorted(r["patterns_by_length"].items()):
            print(f"    Length {length}: {count} patterns")
        print()

    print("  Frequent patterns:")
    for p in r["patterns"][:25]:
        print(f"    x{p['support']:<4} ({p['support_pct']:>5.1f}%)  "
              f"{p['display']}")
    print()
    print(f"  ({r['elapsed_ms']}ms)")


def _print_anomalies(r):
    print("Charter Analytics — Anomaly Detection")
    print("=" * 50)
    print(f"  Lookback:   {r['lookback_days']}d")
    print(f"  Baseline:   {r['baseline_days']}d")
    print(f"  Sensitivity: {r['sensitivity']}")
    print(f"  Total anomalies: {r['total_anomalies']}")
    print()

    if r["actor_anomalies"]:
        print("  Actor anomalies:")
        for a in r["actor_anomalies"]:
            sev = a["severity"].upper()
            if a["type"] == "new_actor":
                print(f"    [{sev}] {a['actor']}: {a['detail']}")
            else:
                print(f"    [{sev}] {a['actor']}: {a['metric']} "
                      f"{a['direction']} — "
                      f"baseline: {a['baseline_value']}, "
                      f"recent: {a['recent_value']} "
                      f"(ratio: {a['change_ratio']}x)")
        print()

    if r["global_anomalies"]:
        print("  Global anomalies:")
        for a in r["global_anomalies"]:
            sev = a["severity"].upper()
            print(f"    [{sev}] {a['event']}: {a['detail']}")
        print()

    if r["total_anomalies"] == 0:
        print("  No anomalies detected.")
    print()
    print(f"  ({r['elapsed_ms']}ms)")


def _print_cohorts(r):
    if "note" in r:
        print(r["note"])
        if "actors" in r:
            for a in r["actors"]:
                print(f"  {a['actor']}: {a['metrics']}")
        return

    print("Charter Analytics — Cohort Comparison")
    print("=" * 50)
    print(f"  Actors: {r['actor_count']}")
    print()

    for metric, stats in r["metric_stats"].items():
        print(f"  {metric}:")
        print(f"    mean={stats['mean']}  median={stats['median']}  "
              f"std={stats['std']}  range=[{stats['min']}, {stats['max']}]")
        if stats["outliers"]:
            for o in stats["outliers"]:
                print(f"    ** OUTLIER: {o['actor']} = {o['value']} "
                      f"(z={o['z_score']}, {o['direction']})")
        print()

    if r.get("pairwise"):
        print("  Pairwise comparison:")
        for metric, comp in r["pairwise"].items():
            print(f"    {metric}: "
                  f"{comp['actor_a']['name']}={comp['actor_a']['value']} vs "
                  f"{comp['actor_b']['name']}={comp['actor_b']['value']} "
                  f"({comp['pct_difference']:+.1f}%)")
    print()
    print(f"  ({r['elapsed_ms']}ms)")


def _print_causes(r):
    if "error" in r:
        print(r["error"])
        return

    print(f"Charter Analytics — Causal Discovery: {r['target_event']}")
    print("=" * 50)
    print(f"  Target occurrences: {r['target_count']}")
    print(f"  Base rate:          {r['base_rate']}")
    print(f"  Window size:        {r['window_size']} events")
    print()

    if r["candidates"]:
        print("  Candidate causes (ranked by strength):")
        print(f"  {'Event':<35s} {'Lift':>6s} {'Co-occ':>7s} "
              f"{'Strength':>9s} {'Avg gap':>8s}")
        print(f"  {'-'*35} {'-'*6} {'-'*7} {'-'*9} {'-'*8}")
        for c in r["candidates"]:
            gap = c["timing"].get("avg_gap_s", "—")
            gap_str = f"{gap}s" if isinstance(gap, (int, float)) else gap
            print(f"  {c['event']:<35s} {c['lift']:>6.1f} "
                  f"{c['co_occurrences']:>7d} "
                  f"{c['strength']:>9.2f} {gap_str:>8s}")
        print()

    if r["common_lead_sequences"]:
        print("  Common sequences leading to target:")
        for s in r["common_lead_sequences"]:
            print(f"    x{s['count']:<3}  {s['sequence']}")
    print()
    print(f"  ({r['elapsed_ms']}ms)")


def _print_fingerprint(r):
    if "error" in r:
        print(r["error"])
        return

    print(f"Charter Analytics — Behavioral Fingerprint: {r['actor']}")
    print("=" * 50)

    fp = r["fingerprint"]
    print(f"  Dominant trait: {fp['dominant_trait']} "
          f"({fp['dominant_value']})")
    print()

    print("  Fingerprint vector:")
    for dim, val in fp["vector"].items():
        bar = "#" * max(1, int(val * 30))
        print(f"    {dim:<15s} {val:.3f}  {bar}")
    print()

    if r["similar_actors"]:
        print("  Similarity to other actors:")
        for s in r["similar_actors"]:
            print(f"    {s['actor']}: {s['similarity']:.3f}")
    print()
    print(f"  ({r['elapsed_ms']}ms)")
