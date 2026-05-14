"""Bias Detection by Absence — what the role did NOT do.

The third of the four product changes from charter_role_intelligence.md.
What is missing from a chain is sometimes more revealing than what is
present. This module surfaces gaps between expected role activity and
observed activity, so a successor (or the worker themselves) can see
opportunities the predecessor missed.

Three functions:

    compare_role_to_expected_scope(actor, scope=None)
        Find expected events / decision types that the actor did not
        produce, or produced at a much lower rate than expected. The
        scope can be passed in explicitly, or derived from the active
        Charter governance config (Layer A rules + Layer B actions).

    detect_relationship_silences(actor)
        From the graph memory layer, find entities the actor *should*
        have interacted with but did not. Currently a placeholder that
        gracefully no-ops when graph memory is unavailable — full
        implementation deferred to a follow-up session.

    surface_unused_tools(actor)
        From the chain, identify Charter capabilities (event types)
        that other actors used but this one did not. Currently a
        placeholder for the same reason — needs cohort definitions.

Output is deterministic, template-based (NOT LLM-generated), and
follows the same annotation contract as patterns.declare_patterns:
each declaration carries `confidence` and (where appropriate) a
`caveat`. The bias declarations slot into the manifest's
`pattern_declarations` section as type=`absence`.
"""

from charter.analytics.indexer import Indexer, _now_ms

# Mirrors core.graph_memory.engine.DEFAULT_INTERACTION_WEIGHTS so this
# module can score relationship strength without importing the graph
# engine when it isn't installed.
_INTERACTION_WEIGHTS = {
    "meeting": 4.0,
    "call": 3.0,
    "transaction": 2.0,
    "email": 1.0,
    "message": 0.5,
    "mention": 0.25,
}

DEFAULT_UNDERUSED_THRESHOLD = 0.001  # 0.1% of activity


# ---------------------------------------------------------------------------
# Default expected-scope mapping
# ---------------------------------------------------------------------------
#
# Maps Layer B action keys (and Layer A rule keywords) to chain event
# types that we'd expect to see if the role were exercising that scope.
# This is intentionally conservative — only events Charter actually
# emits today. Add more as the chain vocabulary grows.

LAYER_B_TO_EVENTS = {
    "financial_transaction": [
        "human_approval", "human_review",
    ],
    "external_communication": [
        "email_sent", "whatsapp_send", "human_approval",
    ],
    "data_access": [
        "data_source_added", "data_access_logged",
    ],
    "code_deployment": [
        "code_committed", "service_deployed",
    ],
}

LAYER_A_KEYWORD_TO_EVENTS = {
    "audit": ["audit_generated"],
    "approval": ["human_approval"],
    "review": ["human_review"],
    "fabricate": ["work_product_stamped", "work_product_attested"],
    "patient": ["alert_dispatched"],
    "clinical": ["alert_dispatched"],
}


def _derive_expected_scope_from_config(config_path=None):
    """Build an expected-scope dict from the active charter.yaml.

    Returns:
        dict with `expected_events` (set), `source` (list of strings
        describing where each event came from).
    """
    expected = set()
    source = []
    try:
        from charter.config import load_config
        cfg = load_config(path=config_path) or {}
    except Exception:
        cfg = {}

    gov = cfg.get("governance", {}) if isinstance(cfg, dict) else {}

    # Layer B actions → expected events
    layer_b = gov.get("layer_b", {})
    rules = layer_b.get("rules", []) if isinstance(layer_b, dict) else []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        action = rule.get("action", "")
        events = LAYER_B_TO_EVENTS.get(action, [])
        for ev in events:
            if ev not in expected:
                expected.add(ev)
                source.append("{} → layer_b:{}".format(ev, action))

    # Layer A rule text → expected events (keyword scan)
    layer_a = gov.get("layer_a", {})
    a_rules = []
    if isinstance(layer_a, dict):
        a_rules = list(layer_a.get("universal", []) or [])
        a_rules += list(layer_a.get("rules", []) or [])
    for rule_text in a_rules:
        if not isinstance(rule_text, str):
            continue
        low = rule_text.lower()
        for keyword, events in LAYER_A_KEYWORD_TO_EVENTS.items():
            if keyword in low:
                for ev in events:
                    if ev not in expected:
                        expected.add(ev)
                        source.append(
                            "{} → layer_a:{}".format(ev, keyword)
                        )

    return {
        "expected_events": sorted(expected),
        "source": source,
    }


# ---------------------------------------------------------------------------
# Public: compare_role_to_expected_scope
# ---------------------------------------------------------------------------

def compare_role_to_expected_scope(
    actor=None, scope=None, config_path=None, indexer=None,
    underused_threshold=DEFAULT_UNDERUSED_THRESHOLD,
):
    """Find gaps between expected and observed activity for a role.

    Args:
        actor: Actor name/id to evaluate. If None, evaluates the
            entire chain (organization-level absence).
        scope: Optional dict of the form
            {"expected_events": [list of event types], ...}.
            If not provided, the scope is derived from the active
            charter.yaml governance config.
        config_path: Optional path to charter.yaml for scope derivation.
        indexer: Optional Indexer to reuse (avoids re-syncing).

    Returns:
        dict with:
            - declarations: list of absence declaration dicts (each
              with type='absence', confidence, statement, caveat,
              expected, observed_count)
            - expected: the resolved scope used
            - actor: the actor that was evaluated
            - elapsed_ms
    """
    start = _now_ms()

    # Resolve scope
    if scope is None:
        scope = _derive_expected_scope_from_config(config_path=config_path)
    expected_events = list(scope.get("expected_events", []))
    scope_source = scope.get("source", [])

    # Connect to analytics
    own_indexer = indexer is None
    idx = indexer or Indexer()
    conn = idx.connect()
    if own_indexer:
        idx.sync()

    # Pull observed event counts (filtered by actor if given).
    # When an actor filter is supplied, match against (in order):
    #   1. actor_id      — operator-level identity from chain (v3.1.2)
    #   2. actor         — chain's 3-value enum (human/ai/collaborative)
    #   3. actor_inferred — derived label (e.g. 'ai:gmail_ingestor:MMLD')
    # The inferred label may also match by prefix so callers can pass
    # 'ai:gmail_ingestor' and get all per-account rows.
    if actor:
        rows = conn.execute(
            "SELECT event, COUNT(*) FROM events "
            "WHERE actor_id = ? "
            "   OR actor = ? "
            "   OR actor_inferred = ? "
            "   OR actor_inferred LIKE ? "
            "GROUP BY event",
            [actor, actor, actor, actor + ":%"],
        ).fetchall()
        total_row = conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE actor_id = ? "
            "   OR actor = ? "
            "   OR actor_inferred = ? "
            "   OR actor_inferred LIKE ?",
            [actor, actor, actor, actor + ":%"],
        ).fetchone()
    else:
        rows = conn.execute(
            "SELECT event, COUNT(*) FROM events GROUP BY event"
        ).fetchall()
        total_row = conn.execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()

    observed = {ev: cnt for ev, cnt in rows}
    total_events = total_row[0] if total_row else 0

    # Time window for context
    if actor:
        window = conn.execute(
            "SELECT MIN(ts), MAX(ts) FROM events "
            "WHERE actor_id = ? OR actor = ? "
            "   OR actor_inferred = ? OR actor_inferred LIKE ?",
            [actor, actor, actor, actor + ":%"],
        ).fetchone()
    else:
        window = conn.execute(
            "SELECT MIN(ts), MAX(ts) FROM events"
        ).fetchone()
    temporal_context = {
        "from": str(window[0]) if window and window[0] else None,
        "to": str(window[1]) if window and window[1] else None,
        "total_events": total_events,
    }

    # Build declarations
    declarations = []
    for ev in expected_events:
        count = observed.get(ev, 0)
        if count == 0:
            decl = _absence_declaration_missing(
                actor, ev, total_events, temporal_context, scope_source,
            )
        elif (total_events
              and count / max(total_events, 1) < underused_threshold):
            # Below threshold — present but vanishingly rare
            decl = _absence_declaration_underused(
                actor, ev, count, total_events,
                temporal_context, scope_source,
                threshold=underused_threshold,
            )
        else:
            continue  # Present and not under-represented — no gap
        declarations.append(decl)

    # Confidence on the whole audit: low if total_events small
    audit_confidence = (
        "high" if total_events >= 1000
        else "medium" if total_events >= 100
        else "low"
    )

    if own_indexer:
        idx.close()

    return {
        "declarations": declarations,
        "declaration_count": len(declarations),
        "actor": actor or "organization",
        "expected": {
            "events": expected_events,
            "source": scope_source,
        },
        "observed_event_types": len(observed),
        "audit_confidence": audit_confidence,
        "temporal_context": temporal_context,
        "elapsed_ms": _now_ms() - start,
    }


def _absence_declaration_missing(actor, event, total_events,
                                 temporal_context, scope_source):
    """Build a declaration for an entirely-missing expected event."""
    why = next(
        (s for s in scope_source if s.startswith(event + " ")), ""
    )
    statement = (
        "No '{}' events observed{} across {} chain entries. "
        "Expected because: {}. "
        "This may indicate the work happened off-chain, the role "
        "delegated this category, or it is a genuine coverage gap."
    ).format(
        event,
        " for actor '{}'".format(actor) if actor else "",
        total_events,
        why or "scope rule",
    )

    # Confidence reflects the strength of the inference, not the
    # absence itself. Small samples → low confidence (we can't tell
    # absence from missing-data).
    if total_events >= 1000:
        confidence = "high"
    elif total_events >= 100:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "type": "absence",
        "subtype": "missing",
        "actor": actor or "organization",
        "expected_event": event,
        "observed_count": 0,
        "statement": statement,
        "confidence": confidence,
        "caveat": (
            "Absence is hard to interpret. Charter only sees what "
            "the chain captures — work performed without emitting "
            "events is invisible to this audit. Confirm with the "
            "worker before treating as a gap."
        ),
        "temporal_context": temporal_context,
        "scope_source": why,
    }


def _absence_declaration_underused(actor, event, count, total_events,
                                   temporal_context, scope_source,
                                   threshold=DEFAULT_UNDERUSED_THRESHOLD):
    """Build a declaration for an under-represented expected event."""
    why = next(
        (s for s in scope_source if s.startswith(event + " ")), ""
    )
    pct = round(count / max(total_events, 1) * 100, 3)
    statement = (
        "'{}' events observed only {} times ({:.3f}% of activity)"
        "{}. Expected because: {}. The category exists in the "
        "chain but is barely exercised — worth checking whether "
        "it reflects a deliberate trade-off or a blind spot."
    ).format(
        event, count, pct,
        " for actor '{}'".format(actor) if actor else "",
        why or "scope rule",
    )

    confidence = "medium" if total_events >= 500 else "low"

    return {
        "type": "absence",
        "subtype": "underused",
        "actor": actor or "organization",
        "expected_event": event,
        "observed_count": count,
        "statement": statement,
        "confidence": confidence,
        "caveat": (
            "Under-use is a softer signal than absence. The "
            "threshold ({:.3f}% of activity) is arbitrary and "
            "should be tuned per role."
        ).format(threshold * 100),
        "temporal_context": temporal_context,
        "scope_source": why,
    }


# ---------------------------------------------------------------------------
# Stubs: detect_relationship_silences and surface_unused_tools
# ---------------------------------------------------------------------------
#
# These are scaffolded but not yet implemented. They return an empty
# declaration list with a `status` field so callers can integrate
# the API surface today and the logic can land in a follow-up session
# without breaking anything that already imports them.

def _resolve_actor_entity(gm, actor):
    """Map an actor name (e.g., 'matt') to a graph entity id.

    Tries direct id, slugified person id, then case-insensitive
    name search across person entities. Returns (entity_id, name)
    or (None, None).
    """
    from core.graph_memory.engine import make_id

    # Direct id
    e = gm.get_entity(actor)
    if e:
        return e.get("e.id") or e.get("id"), e.get("e.name") or e.get("name")

    # Common transforms: 'matt' -> 'person:matt', 'person:matt-maughan'
    for candidate in (
        make_id("person", actor),
        "person:{}".format(actor.lower()),
    ):
        e = gm.get_entity(candidate)
        if e:
            return (
                e.get("e.id") or e.get("id"),
                e.get("e.name") or e.get("name"),
            )

    # Name substring search across persons
    matches = gm.find_entities(actor, entity_type="person")
    if matches:
        m = matches[0]
        return (
            m.get("e.id") or m.get("id"),
            m.get("e.name") or m.get("name"),
        )

    return None, None


def _interaction_weight(itype):
    return _INTERACTION_WEIGHTS.get(itype, 0.5)


def _median(values):
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2.0


def detect_relationship_silences(actor=None, indexer=None,
                                 contact_window_days=90,
                                 silence_window_days=30):
    """Find graph entities the actor used to engage but hasn't lately.

    Pulls INTERACTED edges from core.graph_memory for the actor.
    Builds a "regular contact set" of entities engaged with at
    above-median weighted activity in the last `contact_window_days`,
    then flags any of those that have had no interaction in the
    last `silence_window_days`.

    Args:
        actor: Actor name to resolve to a graph entity.
        indexer: Unused; accepted for API symmetry.
        contact_window_days: Window for the regular contact set.
        silence_window_days: Window that must be empty to flag.

    Returns:
        dict with declarations list and a status.
    """
    start = _now_ms()
    actor_label = actor or "organization"

    if not actor:
        return {
            "declarations": [],
            "declaration_count": 0,
            "actor": actor_label,
            "status": "insufficient_actor",
            "note": "Relationship silence detection requires an actor.",
            "elapsed_ms": _now_ms() - start,
        }

    try:
        from core.graph_memory.engine import GraphMemory
    except Exception as e:
        return {
            "declarations": [],
            "declaration_count": 0,
            "actor": actor_label,
            "status": "graph_unavailable",
            "note": "core.graph_memory not importable: {}".format(e),
            "elapsed_ms": _now_ms() - start,
        }

    try:
        gm = GraphMemory()
    except Exception as e:
        return {
            "declarations": [],
            "declaration_count": 0,
            "actor": actor_label,
            "status": "graph_unavailable",
            "note": "GraphMemory init failed: {}".format(e),
            "elapsed_ms": _now_ms() - start,
        }

    entity_id, entity_name = _resolve_actor_entity(gm, actor)
    if not entity_id:
        return {
            "declarations": [],
            "declaration_count": 0,
            "actor": actor_label,
            "status": "actor_not_in_graph",
            "note": (
                "Actor '{}' could not be resolved to a graph "
                "entity. Relationship silences require the actor "
                "to exist in core.graph_memory."
            ).format(actor),
            "elapsed_ms": _now_ms() - start,
        }

    # Pull a generous interaction history (engine returns newest-first)
    interactions = gm.get_interactions(entity_id, limit=2000) or []

    if not interactions:
        return {
            "declarations": [],
            "declaration_count": 0,
            "actor": actor_label,
            "status": "no_interactions",
            "note": (
                "Actor '{}' (entity {}) has no interactions in "
                "graph memory."
            ).format(actor, entity_id),
            "entity_id": entity_id,
            "elapsed_ms": _now_ms() - start,
        }

    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    contact_cutoff = now - timedelta(days=contact_window_days)
    silence_cutoff = now - timedelta(days=silence_window_days)

    def _parse(ts):
        if not ts:
            return None
        try:
            # Engine writes ISO timestamps; some are naive, some
            # carry timezone. Normalize everything to UTC-aware so
            # comparison against `now` is valid.
            dt = datetime.fromisoformat(
                str(ts).replace("Z", "+00:00")
            )
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    # Group by "other" entity. Sum weighted activity in the
    # contact window. Track most-recent interaction date for each.
    by_other = {}
    for row in interactions:
        a_id = row.get("a.id")
        a_name = row.get("a.name")
        b_id = row.get("b.id")
        b_name = row.get("b.name")
        itype = row.get("i.interaction_type") or "message"
        ts = _parse(row.get("i.occurred_at"))
        if a_id == entity_id:
            other_id, other_name = b_id, b_name
        else:
            other_id, other_name = a_id, a_name
        if not other_id or other_id == entity_id:
            # Skip self-loops — interactions where Matt appears on
            # both sides should not register as a "relationship".
            continue
        rec = by_other.setdefault(other_id, {
            "name": other_name,
            "weighted": 0.0,
            "count": 0,
            "last_ts": None,
        })
        if ts and ts >= contact_cutoff:
            rec["weighted"] += _interaction_weight(itype)
            rec["count"] += 1
        if ts and (rec["last_ts"] is None or ts > rec["last_ts"]):
            rec["last_ts"] = ts

    # Build regular contact set: weight > median of nonzero weights
    nonzero_weights = [
        r["weighted"] for r in by_other.values() if r["weighted"] > 0
    ]
    if not nonzero_weights:
        return {
            "declarations": [],
            "declaration_count": 0,
            "actor": actor_label,
            "status": "no_recent_contacts",
            "note": (
                "No interactions in the last {} days for actor '{}'."
            ).format(contact_window_days, actor),
            "entity_id": entity_id,
            "elapsed_ms": _now_ms() - start,
        }

    median_weight = _median(nonzero_weights)

    declarations = []
    for other_id, rec in by_other.items():
        if rec["weighted"] <= 0:
            continue  # not in regular contact set
        if rec["last_ts"] and rec["last_ts"] >= silence_cutoff:
            continue  # interacted recently — not silent
        is_above_median = rec["weighted"] > median_weight
        confidence = "high" if is_above_median else "medium"
        last_seen = (
            rec["last_ts"].date().isoformat()
            if rec["last_ts"] else "unknown"
        )
        days_silent = (
            (now - rec["last_ts"]).days if rec["last_ts"] else None
        )
        statement = (
            "Actor '{}' has had no interaction with {} in the last "
            "{} days (last contact: {}), despite {} interactions in "
            "the prior {}-day window (weighted activity {:.1f}, "
            "{} median)."
        ).format(
            actor_label,
            rec["name"] or other_id,
            silence_window_days,
            last_seen,
            rec["count"],
            contact_window_days,
            rec["weighted"],
            "above" if is_above_median else "at-or-below",
        )
        declarations.append({
            "type": "absence",
            "subtype": "relationship_silence",
            "actor": actor_label,
            "entity_id": other_id,
            "entity_name": rec["name"] or other_id,
            "weighted_activity": round(rec["weighted"], 2),
            "interaction_count": rec["count"],
            "last_seen": last_seen,
            "days_silent": days_silent,
            "statement": statement,
            "confidence": confidence,
            "caveat": (
                "Relationship may have ended naturally — closed deal, "
                "completed project, intentional pullback. Verify "
                "before treating as a follow-up gap."
            ),
        })

    declarations.sort(
        key=lambda d: d.get("weighted_activity", 0), reverse=True
    )

    return {
        "declarations": declarations,
        "declaration_count": len(declarations),
        "actor": actor_label,
        "status": "ok",
        "entity_id": entity_id,
        "entity_name": entity_name,
        "regular_contacts": len(nonzero_weights),
        "median_weight": round(median_weight, 2),
        "contact_window_days": contact_window_days,
        "silence_window_days": silence_window_days,
        "elapsed_ms": _now_ms() - start,
    }


def _surface_unused_tools_operator_role(
    conn, actor, min_peer_usage, start,
):
    """Operator-role detector: target = human/collaborative events,
    cohort = ai:* agents that the operator orchestrates.

    Surfaces capabilities the AI agents collectively use that the
    human/collaborative side has never produced. This is the
    "what tools is my fleet using that I haven't touched" view.
    """
    # Operator vocabulary: events the human/collaborative side did
    operator_rows = conn.execute(
        "SELECT DISTINCT event FROM events "
        "WHERE actor IN ('human', 'collaborative') "
        "   OR actor_inferred LIKE 'human:%' "
        "   OR actor_inferred LIKE 'collaborative:%'"
    ).fetchall()
    operator_vocab = {r[0] for r in operator_rows}

    # Cohort vocabulary: events any ai:* agent used
    cohort_rows = conn.execute(
        "SELECT actor_inferred, event, COUNT(*) "
        "FROM events "
        "WHERE actor_inferred LIKE 'ai:%' "
        "GROUP BY actor_inferred, event"
    ).fetchall()

    if not cohort_rows:
        return {
            "declarations": [],
            "declaration_count": 0,
            "actor": actor,
            "status": "insufficient_cohort",
            "note": "No ai:* agents in chain to form a cohort.",
            "elapsed_ms": _now_ms() - start,
        }

    # Per-event peer support and usage
    by_event = {}
    cohort_actors = set()
    for ia, ev, cnt in cohort_rows:
        cohort_actors.add(ia)
        rec = by_event.setdefault(ev, {"support": set(), "usage": 0})
        rec["support"].add(ia)
        rec["usage"] += cnt

    cohort_size = len(cohort_actors)
    declarations = []
    for ev, rec in by_event.items():
        if ev in operator_vocab:
            continue
        peer_support = len(rec["support"])
        peer_usage = rec["usage"]
        if peer_support < 2 and peer_usage < min_peer_usage:
            continue
        support_ratio = peer_support / max(cohort_size, 1)
        if support_ratio >= 0.5:
            confidence = "high"
        elif support_ratio >= 0.25:
            confidence = "medium"
        else:
            confidence = "low"
        declarations.append({
            "type": "absence",
            "subtype": "unused_tool",
            "actor": actor,
            "resolved_actor": "operator_role:human+collaborative",
            "expected_event": ev,
            "peer_support": peer_support,
            "peer_usage_count": peer_usage,
            "cohort_size": cohort_size,
            "support_ratio": round(support_ratio, 2),
            "observed_count": 0,
            "statement": (
                "The operator role (human + collaborative actors) "
                "has never directly produced '{}', but {} of {} "
                "ai:* agents in the operator's fleet use it ({} "
                "total uses). Worth checking whether '{}' is a "
                "tool the operator should engage with directly "
                "instead of fully delegating."
            ).format(
                ev, peer_support, cohort_size, peer_usage, ev,
            ),
            "confidence": confidence,
            "caveat": (
                "Operator-role detection compares the human side "
                "against the AI fleet. An event the operator never "
                "produces directly may simply be appropriate to "
                "delegate — verify before treating as a gap."
            ),
        })

    declarations.sort(
        key=lambda d: (
            d.get("support_ratio", 0),
            d.get("peer_usage_count", 0),
        ),
        reverse=True,
    )

    return {
        "declarations": declarations,
        "declaration_count": len(declarations),
        "actor": actor,
        "resolved_actor": "operator_role:human+collaborative",
        "status": "ok",
        "cohort_size": cohort_size,
        "fallback": "operator_role",
        "elapsed_ms": _now_ms() - start,
    }


def _surface_unused_tools_inferred_fallback(
    pe, actor, min_similarity, min_cohort_size,
    min_peer_usage, start,
):
    """Cohort detection over `actor_inferred` for chains where the
    immutable `actor` field is unattributed.

    Builds peer cohort by Jaccard similarity of event vocabularies.
    Returns the same shape as the main surface_unused_tools path.
    """
    conn = pe._conn

    # All inferred actors with at least one event
    rows = conn.execute(
        "SELECT actor_inferred, COUNT(*) "
        "FROM events "
        "WHERE actor_inferred IS NOT NULL AND actor_inferred != '' "
        "GROUP BY actor_inferred"
    ).fetchall()

    inferred_actors = [r[0] for r in rows]
    if not inferred_actors:
        return {
            "declarations": [],
            "declaration_count": 0,
            "actor": actor,
            "status": "actor_not_found",
            "note": (
                "No inferred actors in chain. Cannot build cohort."
            ),
            "elapsed_ms": _now_ms() - start,
        }

    # Resolve target inferred-actor: exact match, then prefix match
    target_inferred = None
    for ia in inferred_actors:
        if ia == actor:
            target_inferred = ia
            break
    if target_inferred is None:
        prefix = "{}:".format(actor)
        for ia in inferred_actors:
            if ia.startswith(prefix) or ia.startswith(actor):
                target_inferred = ia
                break
    if target_inferred is None:
        # As a last resort, treat the requested actor as a role
        # PREFIX (e.g. 'matt' → match anything starting with 'matt')
        # — useful when the chain stores granular agent labels.
        candidates = [
            ia for ia in inferred_actors
            if actor.lower() in ia.lower()
        ]
        if candidates:
            target_inferred = candidates[0]

    if target_inferred is None:
        # Operator-role fallback: when the requested actor is the
        # human operator (e.g. 'matt') and no labelled inferred
        # actor matches, treat the target as the union of all
        # human/collaborative events and the cohort as the
        # ai:* agents that surround the operator. Resolve dynamically
        # against the active identity (v3.1.2) so 'matthew',
        # 'node-93921f61', and any future verified-name lookup all
        # route to the operator-role path without hardcoding.
        operator_aliases = {"matt", "operator", "human", "user"}
        try:
            from charter.identity import get_active_actor
            active = get_active_actor()
            if active:
                operator_aliases.add(active.lower())
        except Exception:
            pass
        if actor.lower() in operator_aliases:
            return _surface_unused_tools_operator_role(
                conn, actor, min_peer_usage, start,
            )
        return {
            "declarations": [],
            "declaration_count": 0,
            "actor": actor,
            "status": "actor_not_found",
            "note": (
                "Actor '{}' could not be matched to any inferred "
                "actor label in the chain."
            ).format(actor),
            "elapsed_ms": _now_ms() - start,
        }

    # Build event-vocabulary set per inferred actor
    vocab = {}
    vocab_rows = conn.execute(
        "SELECT actor_inferred, event "
        "FROM events "
        "WHERE actor_inferred IS NOT NULL AND actor_inferred != '' "
        "GROUP BY actor_inferred, event"
    ).fetchall()
    for ia, ev in vocab_rows:
        vocab.setdefault(ia, set()).add(ev)

    target_vocab = vocab.get(target_inferred, set())
    if not target_vocab:
        return {
            "declarations": [],
            "declaration_count": 0,
            "actor": actor,
            "status": "actor_has_no_events",
            "note": (
                "Inferred actor '{}' has no events to compare."
            ).format(target_inferred),
            "elapsed_ms": _now_ms() - start,
        }

    def _jaccard(a, b):
        if not a or not b:
            return 0.0
        inter = len(a & b)
        union = len(a | b)
        return inter / union if union else 0.0

    peers = []
    for ia, vocab_set in vocab.items():
        if ia == target_inferred:
            continue
        sim = _jaccard(target_vocab, vocab_set)
        if sim >= min_similarity:
            peers.append({"actor": ia, "similarity": sim})

    if len(peers) < min_cohort_size:
        # Relax similarity floor progressively until we hit cohort
        # size, but never go below 0.2 — beyond that, the "peers"
        # are noise.
        relaxed_floor = max(0.2, min_similarity - 0.4)
        peers = [
            {"actor": ia, "similarity": _jaccard(target_vocab, v)}
            for ia, v in vocab.items()
            if ia != target_inferred
            and _jaccard(target_vocab, v) >= relaxed_floor
        ]
        if len(peers) < min_cohort_size:
            return {
                "declarations": [],
                "declaration_count": 0,
                "actor": actor,
                "status": "insufficient_cohort",
                "note": (
                    "Only {} peers above Jaccard {:.2f} for "
                    "inferred actor '{}'."
                ).format(
                    len(peers), relaxed_floor, target_inferred,
                ),
                "elapsed_ms": _now_ms() - start,
            }

    peers.sort(key=lambda p: p["similarity"], reverse=True)
    peer_names = [p["actor"] for p in peers]
    cohort_size = len(peers)
    avg_similarity = (
        sum(p["similarity"] for p in peers) / cohort_size
    )

    placeholders = ", ".join(["?"] * len(peer_names))
    cohort_rows = conn.execute(
        "SELECT event, COUNT(DISTINCT actor_inferred) as peer_support, "
        "       COUNT(*) as peer_usage "
        "FROM events "
        "WHERE actor_inferred IN ({}) "
        "GROUP BY event".format(placeholders),
        peer_names,
    ).fetchall()

    declarations = []
    for ev, peer_support, peer_usage in cohort_rows:
        if ev in target_vocab:
            continue
        if peer_support < 2 and peer_usage < min_peer_usage:
            continue
        support_ratio = peer_support / cohort_size
        if support_ratio >= 0.5 and avg_similarity >= 0.5:
            confidence = "high"
        elif support_ratio >= 0.33:
            confidence = "medium"
        else:
            confidence = "low"
        declarations.append({
            "type": "absence",
            "subtype": "unused_tool",
            "actor": actor,
            "resolved_actor": target_inferred,
            "expected_event": ev,
            "peer_support": peer_support,
            "peer_usage_count": peer_usage,
            "cohort_size": cohort_size,
            "support_ratio": round(support_ratio, 2),
            "observed_count": 0,
            "statement": (
                "Actor '{}' (resolved to '{}') has never used "
                "'{}', but {} of {} peers in its inferred-actor "
                "cohort (avg Jaccard similarity {:.2f}) use it "
                "({} total uses). Worth exploring whether this "
                "is a tool blind spot."
            ).format(
                actor, target_inferred, ev,
                peer_support, cohort_size,
                avg_similarity, peer_usage,
            ),
            "confidence": confidence,
            "caveat": (
                "Cohort built by event-vocabulary Jaccard "
                "similarity over inferred-actor labels, since the "
                "chain's immutable actor field is unattributed. "
                "Peers may be functionally adjacent agents rather "
                "than role-similar workers."
            ),
        })

    declarations.sort(
        key=lambda d: (
            d.get("support_ratio", 0),
            d.get("peer_usage_count", 0),
        ),
        reverse=True,
    )

    return {
        "declarations": declarations,
        "declaration_count": len(declarations),
        "actor": actor,
        "resolved_actor": target_inferred,
        "status": "ok",
        "cohort_size": cohort_size,
        "cohort": [
            {
                "actor": p["actor"],
                "similarity": round(p["similarity"], 3),
            }
            for p in peers[:10]
        ],
        "avg_similarity": round(avg_similarity, 3),
        "fallback": "inferred_jaccard",
        "elapsed_ms": _now_ms() - start,
    }


def surface_unused_tools(actor=None, indexer=None,
                         min_peer_usage=3,
                         min_similarity=0.6,
                         min_cohort_size=3):
    """Find capabilities peers used but this actor did not.

    Best-effort implementation: with no formal "similar role"
    definition yet, this compares the target actor's event
    vocabulary against the union of all other actors' event
    vocabularies. An event type used by at least `min_peer_usage`
    times across other actors but never by the target is reported
    as an unused tool.

    When `actor` is None or only one actor exists in the chain,
    returns an empty result with status='insufficient_cohort'.

    Args:
        actor: Actor to evaluate.
        indexer: Optional Indexer to reuse.
        min_peer_usage: Minimum count across peer actors before an
            event qualifies as "in use" by peers.

    Returns:
        dict with declarations list and status.
    """
    start = _now_ms()

    if not actor:
        return {
            "declarations": [],
            "declaration_count": 0,
            "actor": "organization",
            "status": "insufficient_cohort",
            "note": "Cohort comparison requires a target actor.",
            "elapsed_ms": _now_ms() - start,
        }

    # Use the PatternEngine fingerprint to define a cohort of
    # behaviorally-similar peer actors, then surface event types
    # that the cohort uses but the target actor does not.
    try:
        from charter.analytics.patterns import (
            PatternEngine, _cosine_similarity,
        )
    except Exception as e:
        return {
            "declarations": [],
            "declaration_count": 0,
            "actor": actor,
            "status": "patterns_unavailable",
            "note": "PatternEngine not importable: {}".format(e),
            "elapsed_ms": _now_ms() - start,
        }

    pe = PatternEngine(auto_sync=True)
    try:
        all_metrics = pe._compute_actor_metrics("actor")
        target = None
        for m in all_metrics:
            if m["actor"] == actor or m["actor"].startswith(str(actor)):
                target = m
                break
        if not target:
            # Fallback path for chains where the immutable `actor`
            # field is empty/None and the rich identity lives in
            # `actor_inferred`. We score peer similarity by Jaccard
            # overlap of event vocabulary instead of the behavioral
            # fingerprint vector. This sidesteps the dependency on
            # the chain actor-attribution fix (Prompt 12).
            result = _surface_unused_tools_inferred_fallback(
                pe, actor, min_similarity, min_cohort_size,
                min_peer_usage, start,
            )
            return result

        target_fp = pe._build_fingerprint(target)
        target_vec = list(target_fp["vector"].values())

        # Score each peer
        peers = []
        for m in all_metrics:
            if m["actor"] == target["actor"]:
                continue
            other_fp = pe._build_fingerprint(m)
            other_vec = list(other_fp["vector"].values())
            sim = _cosine_similarity(target_vec, other_vec)
            if sim >= min_similarity:
                peers.append({"actor": m["actor"], "similarity": sim})

        if len(peers) < min_cohort_size:
            return {
                "declarations": [],
                "declaration_count": 0,
                "actor": actor,
                "status": "insufficient_cohort",
                "note": (
                    "Only {} peers above similarity {:.2f} "
                    "(need {}). Cannot define a meaningful cohort."
                ).format(
                    len(peers), min_similarity, min_cohort_size,
                ),
                "cohort_size": len(peers),
                "min_similarity": min_similarity,
                "elapsed_ms": _now_ms() - start,
            }

        peers.sort(key=lambda p: p["similarity"], reverse=True)
        peer_names = [p["actor"] for p in peers]

        conn = pe._conn

        # Vocabulary used by the target actor
        target_events = {
            row[0] for row in conn.execute(
                "SELECT DISTINCT event FROM events WHERE actor = ?",
                [actor],
            ).fetchall()
        }

        # Cohort vocabulary: union of event types used by any peer,
        # plus a count of how many peers used each (peer-support).
        placeholders = ", ".join(["?"] * len(peer_names))
        cohort_rows = conn.execute(
            "SELECT event, COUNT(DISTINCT actor) as peer_support, "
            "       COUNT(*) as peer_usage "
            "FROM events "
            "WHERE actor IN ({}) "
            "GROUP BY event".format(placeholders),
            peer_names,
        ).fetchall()
    finally:
        pe.close()

    declarations = []
    cohort_size = len(peers)
    avg_similarity = (
        sum(p["similarity"] for p in peers) / cohort_size
        if cohort_size else 0.0
    )

    for ev, peer_support, peer_usage in cohort_rows:
        if ev in target_events:
            continue
        if peer_support < 2 and peer_usage < min_peer_usage:
            # Single peer, low volume — too weak a signal
            continue
        # Confidence: high if a majority of cohort uses it AND
        # similarity is strong; medium if a clear minority; low otherwise.
        support_ratio = peer_support / cohort_size
        if support_ratio >= 0.5 and avg_similarity >= 0.75:
            confidence = "high"
        elif support_ratio >= 0.33:
            confidence = "medium"
        else:
            confidence = "low"
        declarations.append({
            "type": "absence",
            "subtype": "unused_tool",
            "actor": actor,
            "expected_event": ev,
            "peer_support": peer_support,
            "peer_usage_count": peer_usage,
            "cohort_size": cohort_size,
            "support_ratio": round(support_ratio, 2),
            "observed_count": 0,
            "statement": (
                "Actor '{}' has never used '{}', but {} of {} "
                "behaviorally-similar peers (avg cosine "
                "similarity {:.2f}) use it ({} total uses). "
                "Worth exploring whether this is a tool blind spot."
            ).format(
                actor, ev, peer_support, cohort_size,
                avg_similarity, peer_usage,
            ),
            "confidence": confidence,
            "caveat": (
                "Cohort is built from behavioral fingerprint "
                "similarity, not explicit role definitions. A peer "
                "with a similar work cadence may still hold a "
                "different role; verify before treating as a gap."
            ),
        })

    declarations.sort(
        key=lambda d: (
            d.get("support_ratio", 0),
            d.get("peer_usage_count", 0),
        ),
        reverse=True,
    )

    return {
        "declarations": declarations,
        "declaration_count": len(declarations),
        "actor": actor,
        "status": "ok",
        "cohort_size": cohort_size,
        "cohort": [
            {"actor": p["actor"], "similarity": round(p["similarity"], 3)}
            for p in peers[:10]
        ],
        "avg_similarity": round(avg_similarity, 3),
        "min_similarity": min_similarity,
        "elapsed_ms": _now_ms() - start,
    }


# ---------------------------------------------------------------------------
# Convenience: combine all three (used by manifest export and CLI)
# ---------------------------------------------------------------------------

def declare_absence(actor=None, scope=None, config_path=None,
                    underused_threshold=DEFAULT_UNDERUSED_THRESHOLD):
    """Run all three absence detectors and return a combined result.

    The output shape mirrors patterns.declare_patterns so it can be
    merged into the manifest's pattern_declarations.declarations
    list directly.

    Args:
        actor: Actor to evaluate.
        scope: Optional explicit scope dict.
        config_path: Optional charter.yaml path.

    Returns:
        dict with combined declarations and a per-detector summary.
    """
    start = _now_ms()
    indexer = Indexer()
    indexer.connect()
    indexer.sync()

    scope_result = compare_role_to_expected_scope(
        actor=actor, scope=scope,
        config_path=config_path, indexer=indexer,
        underused_threshold=underused_threshold,
    )
    silences_result = detect_relationship_silences(
        actor=actor, indexer=indexer,
    )
    tools_result = surface_unused_tools(
        actor=actor, indexer=indexer,
    )

    indexer.close()

    declarations = (
        scope_result.get("declarations", [])
        + silences_result.get("declarations", [])
        + tools_result.get("declarations", [])
    )

    return {
        "declarations": declarations,
        "declaration_count": len(declarations),
        "actor": actor or "organization",
        "detectors": {
            "scope_comparison": {
                "declaration_count": scope_result.get(
                    "declaration_count", 0
                ),
                "expected": scope_result.get("expected", {}),
                "audit_confidence": scope_result.get(
                    "audit_confidence", "low"
                ),
            },
            "relationship_silences": {
                "declaration_count": silences_result.get(
                    "declaration_count", 0
                ),
                "status": silences_result.get("status", "unknown"),
            },
            "unused_tools": {
                "declaration_count": tools_result.get(
                    "declaration_count", 0
                ),
                "status": tools_result.get("status", "unknown"),
            },
        },
        "elapsed_ms": _now_ms() - start,
    }


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

def run_absence_cli(args):
    """CLI entrypoint for `charter analytics absence`.

    Supports:
        --actor <name>           Actor to evaluate
        --json                   Emit raw JSON instead of human format
    """
    import json

    actor = getattr(args, "actor", None)
    as_json = getattr(args, "json", False)
    threshold = getattr(
        args, "underused_threshold", DEFAULT_UNDERUSED_THRESHOLD,
    )
    if threshold is None:
        threshold = DEFAULT_UNDERUSED_THRESHOLD

    result = declare_absence(actor=actor, underused_threshold=threshold)

    if as_json:
        print(json.dumps(result, indent=2, default=str))
        return

    print()
    print("Charter — Bias Detection by Absence")
    print("=" * 60)
    print("Actor: {}".format(result["actor"]))
    print("Declarations: {}".format(result["declaration_count"]))
    print()

    detectors = result.get("detectors", {})
    sc = detectors.get("scope_comparison", {})
    print("Scope comparison: {} gap(s) (audit confidence: {})".format(
        sc.get("declaration_count", 0),
        sc.get("audit_confidence", "?"),
    ))
    rs = detectors.get("relationship_silences", {})
    print("Relationship silences: {} ({})".format(
        rs.get("declaration_count", 0),
        rs.get("status", "?"),
    ))
    ut = detectors.get("unused_tools", {})
    print("Unused tools: {} ({})".format(
        ut.get("declaration_count", 0),
        ut.get("status", "?"),
    ))
    print()

    if not result["declarations"]:
        print("No absence patterns detected.")
        return

    for i, d in enumerate(result["declarations"], 1):
        print("{}. [{}/{}] confidence={}".format(
            i,
            d.get("subtype", d.get("type", "?")),
            d.get("expected_event", "?"),
            d.get("confidence", "?"),
        ))
        print("   {}".format(d.get("statement", "")))
        if d.get("caveat"):
            print("   caveat: {}".format(d["caveat"]))
        print()
