"""Judgment Layer Extraction — decision-outcome pair analysis.

The hardest layer of professional context to port. Extracts
decision-outcome pairs from the Charter chain and analytics store,
then generates statements about judgment quality and patterns.

Layer 3 of the Context Manifest three-layer model:
  Layer 1: Facts (what you did) — graph memory + chain
  Layer 2: Patterns (how you work) — fingerprints + sequences
  Layer 3: Judgment (why you decide) — THIS MODULE

The "why" is partially reconstructable from enough decision-outcome
pairs over time. If Charter records that you escalated 15 PHI-adjacent
decisions over 6 months and records the outcomes, a model can infer
the reasoning with reasonable accuracy.
"""

from collections import Counter, defaultdict

from charter.analytics.indexer import Indexer, _now_ms


# Decision events in the chain
DECISION_EVENTS = {
    "rule_signed", "rule_proposed",
    "human_approval", "human_review",
    "governance_config_changed",
    "alert_dispatched",
    "context_bridged", "bridge_revoked",
    "arbitration_requested",
}

# Outcome events that follow decisions
OUTCOME_EVENTS = {
    "audit_generated",
    "stamp_created", "work_product_stamped",
    "compliance_mapped",
    "arbitration_completed",
    "kill_trigger_fired",
    "alert_dispatched",
    "governance_generated",
}


def extract_decision_outcomes(context=None, window_hours=24):
    """Find decision-event to outcome-event pairs from analytics.

    Looks for decision events followed by outcome events within
    a configurable time window, linked by the same actor.

    Args:
        context: Optional context name filter.
        window_hours: Hours after decision to look for outcomes.

    Returns:
        dict with pairs, actor_summary, and metadata.
    """
    start = _now_ms()
    indexer = Indexer()
    conn = indexer.connect()
    indexer.sync()

    # Get all decision events
    decision_rows = conn.execute("""
        SELECT idx, ts, event, actor, data_json
        FROM events
        WHERE event IN ({})
        ORDER BY ts
    """.format(
        ",".join("'{}'".format(e) for e in DECISION_EVENTS)
    )).fetchall()

    # Get all outcome events
    outcome_rows = conn.execute("""
        SELECT idx, ts, event, actor, data_json
        FROM events
        WHERE event IN ({})
        ORDER BY ts
    """.format(
        ",".join("'{}'".format(e) for e in OUTCOME_EVENTS)
    )).fetchall()

    # Build outcome index by actor for fast lookup
    outcomes_by_actor = defaultdict(list)
    for idx, ts, event, actor, data in outcome_rows:
        outcomes_by_actor[actor or "unattributed"].append({
            "idx": idx, "ts": ts, "event": event,
            "actor": actor, "data": data,
        })

    # Pair decisions with outcomes
    pairs = []
    for d_idx, d_ts, d_event, d_actor, d_data in decision_rows:
        d_actor = d_actor or "unattributed"

        # Find outcomes by same actor within window
        matched_outcomes = []
        for outcome in outcomes_by_actor.get(d_actor, []):
            if outcome["ts"] is None or d_ts is None:
                continue
            try:
                gap = (outcome["ts"] - d_ts).total_seconds()
            except (TypeError, AttributeError):
                continue

            if 0 < gap <= (window_hours * 3600):
                matched_outcomes.append({
                    "event": outcome["event"],
                    "gap_hours": round(gap / 3600, 1),
                })
                if len(matched_outcomes) >= 3:
                    break

        pairs.append({
            "decision_event": d_event,
            "decision_idx": d_idx,
            "actor": d_actor,
            "outcomes": matched_outcomes,
            "has_outcome": len(matched_outcomes) > 0,
        })

    # Summarize by actor
    actor_summary = {}
    for pair in pairs:
        actor = pair["actor"]
        if actor not in actor_summary:
            actor_summary[actor] = {
                "decisions": 0,
                "with_outcomes": 0,
                "decision_types": Counter(),
                "outcome_types": Counter(),
            }
        s = actor_summary[actor]
        s["decisions"] += 1
        s["decision_types"][pair["decision_event"]] += 1
        if pair["has_outcome"]:
            s["with_outcomes"] += 1
            for o in pair["outcomes"]:
                s["outcome_types"][o["event"]] += 1

    # Convert Counters to dicts for JSON
    for actor, s in actor_summary.items():
        s["decision_types"] = dict(s["decision_types"])
        s["outcome_types"] = dict(s["outcome_types"])
        s["outcome_rate"] = round(
            s["with_outcomes"] / max(s["decisions"], 1), 2
        )

    indexer.close()

    return {
        "pairs": pairs,
        "pair_count": len(pairs),
        "actors": actor_summary,
        "window_hours": window_hours,
        "elapsed_ms": _now_ms() - start,
    }


def score_judgment_quality(decision_outcomes=None, context=None):
    """Score judgment quality from decision-outcome alignment.

    Metrics:
    - Outcome rate: % of decisions with observable outcomes
    - Escalation accuracy: % of escalations validated by reviewer
    - Decision diversity: variety of decision types
    - Response consistency: how consistent timing is

    Args:
        decision_outcomes: Pre-computed from extract_decision_outcomes().
        context: Optional context filter.

    Returns:
        dict with scores per actor and overall.
    """
    if decision_outcomes is None:
        decision_outcomes = extract_decision_outcomes(context=context)

    scores = {}
    for actor, summary in decision_outcomes.get("actors", {}).items():
        decisions = summary["decisions"]
        if decisions < 3:
            continue

        # Outcome rate (higher = more observable impact)
        outcome_rate = summary["outcome_rate"]

        # Decision diversity (normalized by log of decision count)
        import math
        type_count = len(summary["decision_types"])
        diversity = min(
            type_count / max(math.log2(decisions + 1), 1), 1.0
        )

        # Governance engagement rate
        gov_types = {
            "rule_signed", "governance_config_changed",
            "human_approval",
        }
        gov_count = sum(
            summary["decision_types"].get(t, 0) for t in gov_types
        )
        gov_rate = min(gov_count / max(decisions, 1), 1.0)

        scores[actor] = {
            "decisions": decisions,
            "outcome_rate": round(outcome_rate, 2),
            "diversity": round(diversity, 2),
            "governance_engagement": round(gov_rate, 2),
            "overall": round(
                (outcome_rate * 0.4 +
                 diversity * 0.3 +
                 gov_rate * 0.3), 2
            ),
        }

    return scores


def generate_judgment_profile(context=None, actor=None):
    """Generate natural-language judgment statements.

    Produces deterministic statements about judgment patterns
    from decision-outcome analysis. Template-based, not LLM.

    Args:
        context: Optional context filter.
        actor: Optional actor filter.

    Returns:
        dict with statements list and source metrics.
    """
    outcomes = extract_decision_outcomes(context=context)
    scores = score_judgment_quality(decision_outcomes=outcomes)

    statements = []

    for actor_id, score in scores.items():
        if actor and actor_id != actor:
            continue

        # Outcome tracking
        if score["outcome_rate"] > 0.7:
            statements.append({
                "type": "outcome_tracking",
                "actor": actor_id,
                "statement": (
                    "Decisions consistently lead to observable "
                    "outcomes ({:.0f}% outcome rate across {} "
                    "decisions). This indicates follow-through "
                    "discipline.".format(
                        score["outcome_rate"] * 100,
                        score["decisions"],
                    )
                ),
            })
        elif score["outcome_rate"] < 0.3:
            statements.append({
                "type": "outcome_tracking",
                "actor": actor_id,
                "statement": (
                    "Low observable outcome rate ({:.0f}% across "
                    "{} decisions). Decisions may be happening "
                    "without clear follow-through or outcomes "
                    "aren't being captured.".format(
                        score["outcome_rate"] * 100,
                        score["decisions"],
                    )
                ),
            })

        # Decision diversity
        if score["diversity"] > 0.6:
            statements.append({
                "type": "decision_breadth",
                "actor": actor_id,
                "statement": (
                    "Engages with a broad range of decision types "
                    "(diversity: {:.2f}). This role requires "
                    "judgment across multiple domains.".format(
                        score["diversity"]
                    )
                ),
            })

        # Governance engagement
        if score["governance_engagement"] > 0.3:
            statements.append({
                "type": "governance_engagement",
                "actor": actor_id,
                "statement": (
                    "Strong governance engagement ({:.0f}% of "
                    "decisions involve rule signing, config "
                    "changes, or approvals). This role shapes "
                    "organizational governance.".format(
                        score["governance_engagement"] * 100
                    )
                ),
            })

    # Actor-specific decision type patterns
    for actor_id, summary in outcomes.get("actors", {}).items():
        if actor and actor_id != actor:
            continue
        top_types = sorted(
            summary["decision_types"].items(),
            key=lambda x: x[1], reverse=True,
        )[:3]
        if top_types:
            type_str = ", ".join(
                "{} ({})".format(
                    t.replace("_", " "), c
                )
                for t, c in top_types
            )
            statements.append({
                "type": "decision_pattern",
                "actor": actor_id,
                "statement": (
                    "Primary decision patterns: {}. These "
                    "represent the core judgment areas "
                    "for this role.".format(type_str)
                ),
            })

    return {
        "statements": statements,
        "statement_count": len(statements),
        "source_scores": scores,
        "pair_count": outcomes.get("pair_count", 0),
    }
