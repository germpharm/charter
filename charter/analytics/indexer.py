"""Incremental indexer — ETL from chain.jsonl to DuckDB analytical store.

The chain is the source of truth. This module builds a derived columnar
store that can be queried in milliseconds. The chain is never modified.

Usage:
    charter analytics sync       # Incremental update
    charter analytics rebuild    # Full rebuild from chain
    charter analytics status     # Show index health

Programmatic:
    from charter.analytics.indexer import Indexer
    idx = Indexer()
    idx.sync()
    conn = idx.connect()
    conn.execute("SELECT * FROM events WHERE event = 'audit_generated'")
"""

import json
import os
import time

try:
    import duckdb
except ImportError:
    duckdb = None

from charter.identity import get_chain_path, get_identity_dir


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ANALYTICS_DIR = "analytics"
DB_FILENAME = "charter_analytics.duckdb"

# Session gap: if >30 minutes between events from the same actor,
# treat it as a new session.
SESSION_GAP_SECONDS = 1800

# Schema version — bump when tables change shape.
SCHEMA_VERSION = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_analytics_dir():
    """Return ~/.charter/analytics/, creating if needed."""
    d = os.path.join(get_identity_dir(), ANALYTICS_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _get_db_path():
    """Return path to the DuckDB file."""
    return os.path.join(_get_analytics_dir(), DB_FILENAME)


def _require_duckdb():
    """Raise a clear error if duckdb is not installed."""
    if duckdb is None:
        raise ImportError(
            "DuckDB is required for Charter Analytics.\n"
            "Install it with: pip install charter-governance[analytics]"
        )


def _parse_chain_line(line):
    """Parse a single JSONL line into a dict, or None on failure."""
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------

_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS events (
    idx             INTEGER PRIMARY KEY,
    ts              TIMESTAMP NOT NULL,
    event           VARCHAR NOT NULL,
    actor           VARCHAR,
    signer          VARCHAR,
    hash            VARCHAR(64) NOT NULL,
    previous_hash   VARCHAR(64),
    signature       VARCHAR(64),
    data_json       VARCHAR,
    -- Extracted fields for fast filtering
    data_domain     VARCHAR,
    data_source     VARCHAR,
    data_tool       VARCHAR,
    data_format     VARCHAR,
    -- Derived attribution: richer than the chain's 3-value `actor`
    -- enum. Format: <role>:<subsystem>:<context> with optional
    -- segments. Examples: ai:gmail_ingestor:MMLD, ai:auditor, human.
    -- Always populated by _infer_actor() during sync. Falls back to
    -- the chain `actor` when present, then to event-type heuristics.
    -- Safe to evolve — the indexer is a derived view, not authoritative.
    actor_inferred  VARCHAR,
    -- v3.1.2: Operator-level identity that produced this entry.
    -- Read from chain entry's actor_id field when present (post fix);
    -- backfilled from signer→identity mapping for legacy entries.
    -- This is the column the bias-detection-by-absence module joins
    -- against when filtering by operator (--actor matt). Stable
    -- across the lifetime of an identity even before verification.
    actor_id        VARCHAR
);
"""

_SESSIONS_DDL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id      INTEGER PRIMARY KEY,
    actor           VARCHAR NOT NULL,
    start_ts        TIMESTAMP NOT NULL,
    end_ts          TIMESTAMP NOT NULL,
    event_count     INTEGER NOT NULL,
    events          VARCHAR,          -- JSON array of event types in order
    first_index     INTEGER NOT NULL,
    last_index      INTEGER NOT NULL,
    duration_seconds DOUBLE
);
"""

_TRANSITIONS_DDL = """
CREATE TABLE IF NOT EXISTS transitions (
    actor           VARCHAR NOT NULL,
    from_event      VARCHAR NOT NULL,
    to_event        VARCHAR NOT NULL,
    count           INTEGER NOT NULL,
    avg_gap_seconds DOUBLE,
    PRIMARY KEY (actor, from_event, to_event)
);
"""

_WATERMARK_DDL = """
CREATE TABLE IF NOT EXISTS _watermark (
    key             VARCHAR PRIMARY KEY,
    value           VARCHAR NOT NULL
);
"""

_ALL_DDL = [_EVENTS_DDL, _SESSIONS_DDL, _TRANSITIONS_DDL, _WATERMARK_DDL]


# ---------------------------------------------------------------------------
# Indexer
# ---------------------------------------------------------------------------

class Indexer:
    """Incremental indexer from chain.jsonl to DuckDB.

    Args:
        chain_path: Path to chain.jsonl (default: ~/.charter/chain.jsonl).
        db_path:    Path to DuckDB file (default: ~/.charter/analytics/charter_analytics.duckdb).
    """

    def __init__(self, chain_path=None, db_path=None):
        _require_duckdb()
        self.chain_path = chain_path or get_chain_path()
        self.db_path = db_path or _get_db_path()
        self._conn = None

    def connect(self):
        """Return a DuckDB connection, creating the schema if needed."""
        if self._conn is None:
            self._conn = duckdb.connect(self.db_path)
            self._ensure_schema()
        return self._conn

    def close(self):
        """Close the DuckDB connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _ensure_schema(self):
        """Create tables if they don't exist, run additive migrations."""
        conn = self._conn
        for ddl in _ALL_DDL:
            conn.execute(ddl)

        # Check schema version
        existing = conn.execute(
            "SELECT value FROM _watermark WHERE key = 'schema_version'"
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO _watermark VALUES ('schema_version', ?)",
                [str(SCHEMA_VERSION)],
            )
            return

        current = int(existing[0])
        if current == SCHEMA_VERSION:
            return

        # v1 → v2: add `actor_inferred` column. Backfill happens on
        # the next sync (incremental — older rows stay NULL until a
        # full rebuild). The CLI hint is left in place for users who
        # want to force-populate everything immediately.
        if current == 1 and SCHEMA_VERSION >= 2:
            try:
                conn.execute(
                    "ALTER TABLE events ADD COLUMN actor_inferred VARCHAR"
                )
            except Exception:
                # Column may already exist if a partial migration ran.
                pass
            # Backfill actor_inferred for every existing row by
            # re-running the inference rules against the stored
            # event type, chain actor, and data payload.
            self._backfill_actor_inferred()
            current = 2

        # v2 → v3: add `actor_id` column. Backfill from the signer
        # column by mapping each signer public_id to the identity
        # alias from identity.json (today this is a single-operator
        # mapping; multi-tenant chains can extend the mapping later).
        if current == 2 and SCHEMA_VERSION >= 3:
            try:
                conn.execute(
                    "ALTER TABLE events ADD COLUMN actor_id VARCHAR"
                )
            except Exception:
                pass
            self._backfill_actor_id()
            current = 3

        conn.execute(
            "UPDATE _watermark SET value = ? "
            "WHERE key = 'schema_version'",
            [str(SCHEMA_VERSION)],
        )

        if current != SCHEMA_VERSION:
            raise RuntimeError(
                f"Analytics DB schema version {current} != expected "
                f"{SCHEMA_VERSION}. Run 'charter analytics rebuild'."
            )

    # -- Watermark -----------------------------------------------------------

    def _get_watermark(self):
        """Return the last indexed chain index, or -1 if empty."""
        conn = self.connect()
        row = conn.execute(
            "SELECT value FROM _watermark WHERE key = 'last_index'"
        ).fetchone()
        return int(row[0]) if row else -1

    def _set_watermark(self, index):
        """Update the high-water mark."""
        conn = self.connect()
        conn.execute(
            "INSERT OR REPLACE INTO _watermark VALUES ('last_index', ?)",
            [str(index)],
        )

    def _set_meta(self, key, value):
        """Set an arbitrary metadata key."""
        conn = self.connect()
        conn.execute(
            "INSERT OR REPLACE INTO _watermark VALUES (?, ?)",
            [key, str(value)],
        )

    def _get_meta(self, key):
        """Get a metadata value, or None."""
        conn = self.connect()
        row = conn.execute(
            "SELECT value FROM _watermark WHERE key = ?", [key]
        ).fetchone()
        return row[0] if row else None

    # -- Core sync -----------------------------------------------------------

    def sync(self):
        """Incremental sync: index new chain entries since last watermark.

        Returns:
            dict with keys: new_events, total_events, duration_ms
        """
        start_ms = _now_ms()
        watermark = self._get_watermark()

        new_entries = self._read_chain_from(watermark + 1)
        if not new_entries:
            total = self.connect().execute(
                "SELECT COUNT(*) FROM events"
            ).fetchone()[0]
            return {
                "new_events": 0,
                "total_events": total,
                "duration_ms": _now_ms() - start_ms,
                "status": "up_to_date",
            }

        self._insert_events(new_entries)
        new_watermark = new_entries[-1]["index"]
        self._set_watermark(new_watermark)
        self._set_meta("last_sync_ts", time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        ))

        # Rebuild derived tables
        self._rebuild_sessions()
        self._rebuild_transitions()

        total = self.connect().execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]

        return {
            "new_events": len(new_entries),
            "total_events": total,
            "duration_ms": _now_ms() - start_ms,
            "status": "synced",
        }

    def rebuild(self):
        """Full rebuild: drop all data and re-index from chain.

        Returns:
            dict with keys: total_events, duration_ms
        """
        start_ms = _now_ms()
        conn = self.connect()

        # Drop and recreate
        conn.execute("DROP TABLE IF EXISTS events")
        conn.execute("DROP TABLE IF EXISTS sessions")
        conn.execute("DROP TABLE IF EXISTS transitions")
        conn.execute("DROP TABLE IF EXISTS _watermark")
        for ddl in _ALL_DDL:
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO _watermark VALUES ('schema_version', ?)",
            [str(SCHEMA_VERSION)],
        )

        all_entries = self._read_chain_from(0)
        if all_entries:
            self._insert_events(all_entries)
            self._set_watermark(all_entries[-1]["index"])
            self._rebuild_sessions()
            self._rebuild_transitions()

        self._set_meta("last_sync_ts", time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        ))
        self._set_meta("last_rebuild_ts", time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        ))

        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return {
            "total_events": total,
            "duration_ms": _now_ms() - start_ms,
            "status": "rebuilt",
        }

    # -- Chain reading -------------------------------------------------------

    def _read_chain_from(self, start_index):
        """Read chain entries with index >= start_index.

        Reads the JSONL file line-by-line. For chains under ~1M entries
        this is fast enough. For larger chains, the Merkle batch files
        could be used as an optimization.
        """
        if not os.path.isfile(self.chain_path):
            return []

        entries = []
        with open(self.chain_path) as f:
            for line in f:
                entry = _parse_chain_line(line)
                if entry is None:
                    continue
                idx = entry.get("index")
                if idx is not None and idx >= start_index:
                    entries.append(entry)
        return entries

    def _backfill_actor_id(self):
        """Populate events.actor_id for legacy rows.

        Strategy: every legacy row whose `signer` matches the active
        identity's public_id is attributed to that identity's alias
        (or verified first name). Rows from foreign signers stay NULL
        and surface as "unknown" in analytics, which is the correct
        behavior — we don't claim attribution we don't have.

        For multi-tenant chains, future versions can read a
        signer→actor_id map from a config file. Today, single
        operator → single mapping.
        """
        from charter.identity import load_identity, get_active_actor
        identity = load_identity()
        if not identity:
            return
        active_signer = identity.get("public_id")
        active_label = get_active_actor()
        if not (active_signer and active_label):
            return
        conn = self._conn
        # Update only rows where actor_id is NULL — never overwrite a
        # value that the chain wrote at append time (post-fix entries).
        conn.execute(
            "UPDATE events SET actor_id = ? "
            "WHERE actor_id IS NULL AND signer = ?",
            [active_label, active_signer],
        )

    def _backfill_actor_inferred(self):
        """Recompute actor_inferred for every row in events.

        Used during the v1 → v2 schema migration and as the body of
        a future `charter analytics rebuild --reinfer` if needed.
        Reads (idx, event, actor, data_json), computes the new
        label, and writes it back. Bulk-friendly: reads all rows
        once, prepares one parameterized UPDATE per batch.
        """
        conn = self._conn
        rows = conn.execute(
            "SELECT idx, event, actor, data_json FROM events"
        ).fetchall()
        if not rows:
            return
        updates = []
        for idx, event, actor, data_json in rows:
            try:
                data = json.loads(data_json) if data_json else {}
            except Exception:
                data = {}
            updates.append((_infer_actor(event, actor, data), idx))
        conn.executemany(
            "UPDATE events SET actor_inferred = ? WHERE idx = ?",
            updates,
        )

    # -- Event insertion -----------------------------------------------------

    def _insert_events(self, entries):
        """Insert parsed chain entries into the events table."""
        conn = self.connect()

        # Resolve a signer→actor_id fallback for entries that predate
        # the v3.1.2 chain fix. Loaded once per insert batch.
        from charter.identity import load_identity, get_active_actor
        identity = load_identity()
        active_signer = (identity or {}).get("public_id")
        active_label = get_active_actor() if identity else None

        # Batch insert using executemany for performance
        rows = []
        for entry in entries:
            data = entry.get("data", {})
            data_json = json.dumps(data) if data else None
            event = entry.get("event", "unknown")
            actor = entry.get("actor")
            # actor_id resolution: prefer the chain field (new entries
            # have it), fall back to signer→active mapping for legacy
            # entries that predate the fix.
            actor_id = entry.get("actor_id")
            if not actor_id:
                if (active_signer and active_label
                        and entry.get("signer") == active_signer):
                    actor_id = active_label
            rows.append((
                entry.get("index"),
                entry.get("timestamp"),
                event,
                actor,
                entry.get("signer"),
                entry.get("hash", ""),
                entry.get("previous_hash"),
                entry.get("signature"),
                data_json,
                data.get("domain") if isinstance(data, dict) else None,
                data.get("source") if isinstance(data, dict) else None,
                data.get("tool") if isinstance(data, dict) else None,
                data.get("format") if isinstance(data, dict) else None,
                _infer_actor(event, actor, data),
                actor_id,
            ))

        conn.executemany(
            """INSERT OR REPLACE INTO events VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )""",
            rows,
        )

    # -- Derived tables ------------------------------------------------------

    def _rebuild_sessions(self):
        """Rebuild the sessions table from events.

        A session is a sequence of events by the same actor with no gap
        longer than SESSION_GAP_SECONDS between consecutive events.
        """
        conn = self.connect()
        conn.execute("DELETE FROM sessions")

        # Pull events ordered by actor and timestamp
        events = conn.execute(
            "SELECT idx, ts, event, actor FROM events "
            "ORDER BY actor, ts, idx"
        ).fetchall()

        if not events:
            return

        sessions = []
        session_id = 0
        current_actor = None
        session_events = []
        session_start = None
        session_end = None
        first_idx = None

        for row in events:
            idx, ts, event, actor = row
            actor = actor or "__unattributed__"

            if actor != current_actor or (
                session_end is not None
                and (ts - session_end).total_seconds() > SESSION_GAP_SECONDS
            ):
                # Close previous session
                if session_events:
                    duration = (
                        (session_end - session_start).total_seconds()
                        if session_start and session_end else 0.0
                    )
                    sessions.append((
                        session_id,
                        current_actor,
                        session_start,
                        session_end,
                        len(session_events),
                        json.dumps(session_events),
                        first_idx,
                        prev_idx,
                        duration,
                    ))
                    session_id += 1

                # Start new session
                current_actor = actor
                session_events = [event]
                session_start = ts
                session_end = ts
                first_idx = idx
            else:
                session_events.append(event)
                session_end = ts

            prev_idx = idx

        # Close final session
        if session_events:
            duration = (
                (session_end - session_start).total_seconds()
                if session_start and session_end else 0.0
            )
            sessions.append((
                session_id,
                current_actor,
                session_start,
                session_end,
                len(session_events),
                json.dumps(session_events),
                first_idx,
                prev_idx,
                duration,
            ))

        if sessions:
            conn.executemany(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                sessions,
            )

    def _rebuild_transitions(self):
        """Rebuild the transitions table from events.

        Counts event-to-event transitions per actor, with average
        time gap between the two events.
        """
        conn = self.connect()
        conn.execute("DELETE FROM transitions")

        # Use SQL to compute transitions directly — much faster than Python
        conn.execute("""
            INSERT INTO transitions
            SELECT
                COALESCE(e1.actor, '__unattributed__') as actor,
                e1.event as from_event,
                e2.event as to_event,
                COUNT(*) as count,
                AVG(EPOCH(e2.ts) - EPOCH(e1.ts)) as avg_gap_seconds
            FROM events e1
            JOIN events e2
                ON e2.idx = e1.idx + 1
                AND COALESCE(e1.actor, '__unattributed__') = COALESCE(e2.actor, '__unattributed__')
            GROUP BY
                COALESCE(e1.actor, '__unattributed__'),
                e1.event,
                e2.event
        """)

    # -- Status --------------------------------------------------------------

    def status(self):
        """Return index health information.

        Returns:
            dict with watermark, event counts, table sizes, chain info.
        """
        conn = self.connect()
        watermark = self._get_watermark()
        last_sync = self._get_meta("last_sync_ts")
        last_rebuild = self._get_meta("last_rebuild_ts")

        event_count = conn.execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]
        session_count = conn.execute(
            "SELECT COUNT(*) FROM sessions"
        ).fetchone()[0]
        transition_count = conn.execute(
            "SELECT COUNT(*) FROM transitions"
        ).fetchone()[0]

        # Event type distribution (top 10)
        event_types = conn.execute(
            "SELECT event, COUNT(*) as cnt FROM events "
            "GROUP BY event ORDER BY cnt DESC LIMIT 10"
        ).fetchall()

        # Actor distribution
        actor_counts = conn.execute(
            "SELECT COALESCE(actor, 'unattributed') as actor, COUNT(*) as cnt "
            "FROM events GROUP BY actor ORDER BY cnt DESC LIMIT 10"
        ).fetchall()

        # Time range
        time_range = conn.execute(
            "SELECT MIN(ts), MAX(ts) FROM events"
        ).fetchone()

        # Chain file size
        chain_size = 0
        if os.path.isfile(self.chain_path):
            chain_size = os.path.getsize(self.chain_path)

        # DB file size
        db_size = 0
        if os.path.isfile(self.db_path):
            db_size = os.path.getsize(self.db_path)

        return {
            "watermark": watermark,
            "last_sync": last_sync,
            "last_rebuild": last_rebuild,
            "events": event_count,
            "sessions": session_count,
            "transitions": transition_count,
            "event_types": [
                {"event": e, "count": c} for e, c in event_types
            ],
            "actors": [
                {"actor": a, "count": c} for a, c in actor_counts
            ],
            "time_range": {
                "earliest": str(time_range[0]) if time_range[0] else None,
                "latest": str(time_range[1]) if time_range[1] else None,
            },
            "chain_file_bytes": chain_size,
            "db_file_bytes": db_size,
            "db_path": self.db_path,
            "chain_path": self.chain_path,
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_analytics(args):
    """CLI entry point for charter analytics.

    Actions:
        sync    — Incremental update from chain
        rebuild — Full rebuild from chain
        status  — Show index health
        query   — Run a SQL query against the analytics store
    """
    action = getattr(args, "action", "status")

    if action == "sync":
        indexer = Indexer()
        try:
            result = indexer.sync()
            print(f"Charter Analytics — Sync")
            print(f"{'=' * 40}")
            print(f"  New events indexed: {result['new_events']}")
            print(f"  Total events:       {result['total_events']}")
            print(f"  Duration:           {result['duration_ms']}ms")
            print(f"  Status:             {result['status']}")
        finally:
            indexer.close()

    elif action == "rebuild":
        indexer = Indexer()
        try:
            result = indexer.rebuild()
            print(f"Charter Analytics — Rebuild")
            print(f"{'=' * 40}")
            print(f"  Total events indexed: {result['total_events']}")
            print(f"  Duration:             {result['duration_ms']}ms")
            print(f"  Status:               {result['status']}")
        finally:
            indexer.close()

    elif action == "status":
        indexer = Indexer()
        try:
            s = indexer.status()
            print(f"Charter Analytics — Status")
            print(f"{'=' * 40}")
            print(f"  Watermark:     {s['watermark']}")
            print(f"  Last sync:     {s['last_sync'] or 'never'}")
            print(f"  Last rebuild:  {s['last_rebuild'] or 'never'}")
            print()
            print(f"  Events:        {s['events']:,}")
            print(f"  Sessions:      {s['sessions']:,}")
            print(f"  Transitions:   {s['transitions']:,}")
            print()
            if s["time_range"]["earliest"]:
                print(f"  Time range:    {s['time_range']['earliest']}")
                print(f"               → {s['time_range']['latest']}")
                print()
            print(f"  Chain file:    {_human_bytes(s['chain_file_bytes'])}")
            print(f"  DB file:       {_human_bytes(s['db_file_bytes'])}")
            print(f"  DB path:       {s['db_path']}")
            print()
            if s["event_types"]:
                print(f"  Top event types:")
                for et in s["event_types"]:
                    print(f"    {et['count']:>6,}  {et['event']}")
            print()
            if s["actors"]:
                print(f"  Actor distribution:")
                for a in s["actors"]:
                    label = a["actor"]
                    if len(label) > 16:
                        label = label[:12] + "..."
                    print(f"    {a['count']:>6,}  {label}")
        finally:
            indexer.close()

    elif action == "query":
        sql = getattr(args, "sql", None)
        if not sql:
            print("Usage: charter analytics query \"SELECT ...\"")
            return

        indexer = Indexer()
        try:
            # Auto-sync before query
            indexer.sync()
            conn = indexer.connect()
            start_ms = _now_ms()
            result = conn.execute(sql)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            elapsed = _now_ms() - start_ms

            # Print as table
            if not rows:
                print("(no results)")
            else:
                _print_table(columns, rows)
            print(f"\n{len(rows)} row(s) in {elapsed}ms")
        except Exception as e:
            print(f"Query error: {e}")
        finally:
            indexer.close()

    else:
        print(f"Unknown action: {action}")
        print("Usage: charter analytics [sync|rebuild|status|query]")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _human_bytes(n):
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if n != int(n) else f"{n} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _print_table(columns, rows):
    """Print a simple ASCII table."""
    # Calculate column widths
    widths = [len(str(c)) for c in columns]
    for row in rows:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(str(val)))

    # Cap widths at 40 chars
    widths = [min(w, 40) for w in widths]

    # Header
    header = "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(columns))
    print(header)
    print("  ".join("-" * w for w in widths))

    # Rows
    for row in rows:
        line = "  ".join(
            str(v)[:widths[i]].ljust(widths[i])
            for i, v in enumerate(row)
        )
        print(line)


def _now_ms():
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Derived attribution: _infer_actor
# ---------------------------------------------------------------------------
#
# The chain's `actor` field is a Layer 0 invariant constrained to a
# 3-value enum (human | ai | collaborative). It answers the
# accountability question. For analytics — bias detection, role
# intelligence, the absence detector — we need richer attribution:
# which subsystem, on which account/context, did the work.
#
# _infer_actor() derives a richer label from event type + data
# payload. The result lives only in the warehouse (column
# `actor_inferred`). The chain is never touched.
#
# Format: <role>:<subsystem>:<context> with optional segments.
# Examples:
#   ai:gmail_ingestor:MMLD
#   ai:voice_concierge:mysuperoil
#   ai:auditor
#   human (when chain actor was already human, just pass through)
#
# Inference order:
#   1. If chain actor is "human" or explicit, return it (the chain
#      knew best). For "collaborative" we still try to enrich.
#   2. Look up the event type in EVENT_TO_SUBSYSTEM to get the
#      subsystem name.
#   3. Pull a context segment from the data payload (account,
#      context, store, etc.) when present.
#   4. Compose <role>:<subsystem>[:<context>].
#   5. Fall back to "ai" if nothing matches but the event type
#      looks automated, or "unattributed" if truly unknown.

# Map event type → (role, subsystem). The role is what the chain's
# 3-value enum would have said; the subsystem is the richer label.
# Add entries here as Charter's vocabulary grows.
EVENT_TO_SUBSYSTEM = {
    # Email ingestion
    "email_ingested": ("ai", "gmail_ingestor"),
    "email_sent": ("ai", "gmail_ingestor"),
    # WhatsApp
    "whatsapp_listen_start": ("ai", "whatsapp_listener"),
    "whatsapp_listen_stop": ("ai", "whatsapp_listener"),
    "whatsapp_send": ("ai", "whatsapp_sender"),
    "whatsapp_auth": ("ai", "whatsapp_listener"),
    # Voice concierge — these are human-AI sessions
    "voice_concierge_session_start": ("collaborative", "voice_concierge"),
    "voice_concierge_session_end": ("collaborative", "voice_concierge"),
    "voice_concierge_function_call": ("collaborative", "voice_concierge"),
    # Video education pipeline
    "video_education_script_generated": ("ai", "video_education"),
    "video_education_thumbnail_generated": ("ai", "video_education"),
    "video_education_video_generated": ("ai", "video_education"),
    "video_education_pipeline_complete": ("ai", "video_education"),
    # Governance + audit
    "audit_generated": ("ai", "auditor"),
    "governance_generated": ("ai", "governance_generator"),
    "governance_config_changed": ("collaborative", "governance_editor"),
    "rule_signed": ("collaborative", "rule_signer"),
    "rule_proposed": ("collaborative", "rule_proposer"),
    # Alerting
    "alert_dispatched": ("ai", "alerter"),
    # MCP / config
    "mcp_configs_generated": ("ai", "mcp_configurator"),
    # Discharge bridge (telepharmacy)
    "discharge_bridge_call_initiated": ("ai", "discharge_bridge"),
    # Code + deployment
    "code_committed": ("human", "git"),
    "service_deployed": ("collaborative", "deployer"),
    # Onboarding / prospects / teams
    "prospect_provisioned": ("ai", "onboarder"),
    "team_invite_sent": ("ai", "onboarder"),
    # Stamping / attestation
    "work_product_stamped": ("collaborative", "stamper"),
    "work_product_attested": ("collaborative", "attester"),
    # Context + bridging
    "context_created": ("collaborative", "context_manager"),
    "context_bridged": ("collaborative", "context_manager"),
    "bridge_revoked": ("collaborative", "context_manager"),
    # Approvals
    "human_approval": ("human", "approver"),
    "human_review": ("human", "reviewer"),
    # Data ingestion
    "data_source_added": ("collaborative", "ingestor"),
    "data_access_logged": ("ai", "ingestor"),
    # Detection
    "ai_tool_detected": ("ai", "detector"),
    # Continuation
    "session_continued": ("collaborative", "session"),
    # Anchoring
    "timestamp_anchor": ("ai", "anchor"),
    # Identity / lifecycle
    "identity_created": ("collaborative", "identity"),
    "identity_verified": ("collaborative", "identity"),
    # Federation / network / nodes
    "node_created": ("collaborative", "federation"),
    "team_created": ("collaborative", "federation"),
    "bridge_proposed": ("collaborative", "context_manager"),
    "bridge_approved": ("collaborative", "context_manager"),
    "prospect_revoked": ("collaborative", "onboarder"),
    # Deployment / infra
    "daemon_started": ("ai", "daemon"),
    "service_deployed": ("collaborative", "deployer"),
    "tunnel_deployed": ("collaborative", "deployer"),
    "mcp_server_deployed": ("collaborative", "deployer"),
    "charter_https_verified": ("ai", "verifier"),
    # Graph memory lifecycle
    "graph_snapshot": ("ai", "graph_memory"),
    "graph_memory_phase2_complete": ("collaborative", "graph_memory"),
    "current_relationship_rebuild": ("ai", "graph_memory"),
    # Discharge bridge sessions
    "discharge_bridge_session_start": ("ai", "discharge_bridge"),
    # Strategic decisions
    "strategic_decision": ("collaborative", "strategist"),
    # Contribution tracking
    "contribution_recorded": ("collaborative", "contribution_tracker"),
}

# Per-event hints for which data field carries the context segment.
# When the event type has multiple plausible context fields, list
# them in priority order — the first present non-empty value wins.
EVENT_CONTEXT_FIELDS = {
    "email_ingested": ("account", "context"),
    "email_sent": ("account", "context"),
    "voice_concierge_session_start": ("context", "store"),
    "voice_concierge_session_end": ("context", "store"),
    "voice_concierge_function_call": ("context", "store"),
    "video_education_script_generated": ("context", "topic"),
    "video_education_video_generated": ("context", "topic"),
    "discharge_bridge_call_initiated": ("hospital", "context"),
    "audit_generated": ("context",),
    "governance_generated": ("context", "domain"),
    "governance_config_changed": ("context",),
    "alert_dispatched": ("context", "category"),
    "context_created": ("context_name", "context"),
    "context_bridged": ("context_name", "context"),
    "bridge_revoked": ("context_name", "context"),
}


def _infer_actor(event, chain_actor, data):
    """Derive a richer attribution label for an event.

    See the section header above for design rationale and format.

    Args:
        event: Event type string from the chain entry.
        chain_actor: The chain's `actor` field (may be None).
        data: The event data payload (dict or anything else).

    Returns:
        A string of the form <role>[:<subsystem>[:<context>]].
        Never returns None — falls back to "unattributed".
    """
    if not isinstance(data, dict):
        data = {}

    # 1. Pure-human chain actor: just pass through. The chain told us.
    if chain_actor == "human":
        # Even for human, an event-type subsystem makes the row easier
        # to slice (e.g., human:approver vs human:git).
        mapping = EVENT_TO_SUBSYSTEM.get(event)
        if mapping and mapping[0] == "human":
            return "human:{}".format(mapping[1])
        return "human"

    # 2. Event-type lookup
    mapping = EVENT_TO_SUBSYSTEM.get(event)
    if mapping is not None:
        role, subsystem = mapping
        # If the chain disagrees, prefer the chain's role
        # (it was set deliberately at write time).
        if chain_actor in ("ai", "collaborative", "human"):
            role = chain_actor
        label = "{}:{}".format(role, subsystem)
        context_fields = EVENT_CONTEXT_FIELDS.get(event, ())
        for field in context_fields:
            value = data.get(field)
            if value and isinstance(value, (str, int)):
                return "{}:{}".format(label, value)
        return label

    # 3. Fallback by chain actor when no event mapping
    if chain_actor in ("ai", "collaborative"):
        return chain_actor

    # 4. Truly unattributed
    return "unattributed"
