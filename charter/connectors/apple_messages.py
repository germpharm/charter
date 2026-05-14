"""Apple Messages connector — read iMessage / SMS history from chat.db.

This connector reads the local SQLite database that macOS Messages.app
maintains at ~/Library/Messages/chat.db. There is no API, no OAuth,
and no cloud auth flow. Each message becomes a Charter event:

  - is_from_me=1  → 'message_sent'    chain entry
  - is_from_me=0  → 'message_received' chain entry

Each contact handle (phone number or Apple ID email) becomes a person
entity in the graph. If a person entity already exists with that phone
or email, the messages are attributed to it (merge, not duplicate).
Group chats become organization entities keyed by chat_identifier.

## macOS Full Disk Access requirement

Reading chat.db requires the calling process to have macOS Full Disk
Access (TCC permission). This is granted once via:

  System Settings → Privacy & Security → Full Disk Access → "+"

Add the Terminal application (or whichever process is running Charter
— iTerm2, VS Code, Claude Code, etc.) to the list and enable the
toggle. macOS may require restarting the granted application before
the permission takes effect.

If Full Disk Access is missing, sqlite3.connect() raises
"authorization denied" or "unable to open database". The connector
catches this and returns a clean human-readable error explaining
how to grant access. It never crashes and never partially writes.

## Read-only is mandatory

The connector opens chat.db in URI read-only mode
(`mode=ro` + `immutable=1`) and never writes to the live file. It
also never copies chat.db elsewhere. Only normalized events flow into
the Charter chain. The original database is left untouched.

## Privacy

Message text may contain sensitive content (medical, family,
financial). By default the connector does NOT log message text to
stdout — it only writes a truncated copy into the chain payload
(which is signed and stays local). Pass verbose=True if you
explicitly want to see message content during a run.

## Apple epoch

Messages are timestamped with nanoseconds since 2001-01-01 UTC
(Apple's "Mac Absolute Time" reference epoch). The Unix epoch
offset is 978307200 seconds. Convert with:

    unix_seconds = (apple_ns / 1_000_000_000) + 978307200

This is the most common bug source in chat.db tooling. There is a
unit test for it at tests/test_apple_messages.py.
"""

import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from charter.connectors import ConnectorBase, ConnectorResult


DEFAULT_CHAT_DB = os.path.expanduser("~/Library/Messages/chat.db")
DEFAULT_ADDRESSBOOK_GLOB = os.path.expanduser(
    "~/Library/Application Support/AddressBook/Sources/*/"
    "AddressBook-v22.abcddb"
)

# Apple's reference epoch (2001-01-01 UTC) as Unix seconds
APPLE_EPOCH_OFFSET_SECONDS = 978307200


def apple_ns_to_iso(apple_ns: Optional[int]) -> str:
    """Convert Apple Mac Absolute Time (nanoseconds since 2001-01-01 UTC)
    to an ISO 8601 UTC timestamp string.

    Returns "" if the input is None or zero.

    chat.db stores `message.date` in two historical formats:
      - older rows: integer seconds since 2001-01-01
      - newer rows (macOS High Sierra+): integer nanoseconds since
        2001-01-01

    A heuristic distinguishes them: nanosecond values are larger than
    1e15. Anything below that is treated as seconds.
    """
    if not apple_ns:
        return ""
    try:
        if apple_ns > 1_000_000_000_000_000:
            unix_seconds = (apple_ns / 1_000_000_000) + APPLE_EPOCH_OFFSET_SECONDS
        else:
            unix_seconds = apple_ns + APPLE_EPOCH_OFFSET_SECONDS
        dt = datetime.fromtimestamp(unix_seconds, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OSError, OverflowError):
        return ""


def iso_to_apple_ns(iso: str) -> Optional[int]:
    """Convert an ISO 8601 timestamp to Apple Mac Absolute Time
    (nanoseconds since 2001-01-01 UTC). Returns None if unparseable.
    """
    if not iso:
        return None
    try:
        # Accept "2026-04-01" or "2026-04-01T00:00:00Z" or with offset
        s = iso.strip()
        if "T" not in s:
            s = s + "T00:00:00+00:00"
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        unix_seconds = dt.timestamp()
        return int((unix_seconds - APPLE_EPOCH_OFFSET_SECONDS) * 1_000_000_000)
    except (ValueError, TypeError):
        return None


def _decode_attributed_body(blob: Optional[bytes]) -> str:
    """Best-effort extraction of plain text from a NSKeyedArchiver
    binary plist (the `attributedBody` column).

    Newer macOS versions (Sonoma+) sometimes leave `text` NULL and
    store the message body in `attributedBody`. The full format is
    a binary plist with NSAttributedString embedded. We don't ship
    a full parser — instead we scan for the printable text payload
    that NSString uses inside the archive.

    Returns "" if extraction fails. Caller should treat that as
    "no text available" rather than as an error.
    """
    if not blob:
        return ""
    try:
        # Try the official plistlib path first if available.
        try:
            import plistlib
            obj = plistlib.loads(blob)
            text = _walk_for_string(obj)
            if text:
                return text
        except Exception:
            pass

        # Fallback heuristic: NSString payloads in NSKeyedArchiver
        # are preceded by a length byte (or 0x6f marker for long
        # strings). The text usually appears after the marker
        # `NSString` and before the next type marker.
        data = blob
        marker = b"NSString"
        idx = data.find(marker)
        if idx == -1:
            return ""
        # Skip past the marker and a few framing bytes
        start = idx + len(marker)
        # Find the printable run
        chunk = data[start:start + 4096]
        # Strip leading framing bytes (typically a length prefix)
        printable = bytearray()
        seen_text = False
        for b in chunk:
            if 32 <= b < 127 or b in (9, 10, 13):
                printable.append(b)
                seen_text = True
            elif seen_text:
                break
        text = printable.decode("utf-8", errors="replace").strip()
        # Filter out trailing archive metadata fragments
        text = re.sub(r"(NS\w+|iI|streamtyped).*$", "", text).strip()
        return text
    except Exception:
        return ""


def _walk_for_string(obj: Any, depth: int = 0) -> str:
    """Walk a decoded plist tree looking for the longest string."""
    if depth > 6:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        best = ""
        for v in obj.values():
            s = _walk_for_string(v, depth + 1)
            if len(s) > len(best):
                best = s
        return best
    if isinstance(obj, (list, tuple)):
        best = ""
        for v in obj:
            s = _walk_for_string(v, depth + 1)
            if len(s) > len(best):
                best = s
        return best
    return ""


def _load_contacts_index(glob_pattern: str = DEFAULT_ADDRESSBOOK_GLOB) -> Dict[str, str]:
    """Build a phone/email → display name index from Contacts.app.

    Reads every AddressBook source DB matching glob_pattern and merges
    them into one lookup table. Keys are normalized:

      - phone keys: digits-only ("18017265726")
      - email keys: lowercased ("matt@example.com")

    Values are display names ("Lea Dalton"). When a contact has only
    a first name or only an organization, that's used instead.

    Returns an empty dict if Contacts is unreadable (missing Full Disk
    Access, no AddressBook configured, etc.) — the caller treats an
    empty index as "no enrichment available" and falls back to the
    raw handle string for entity names.

    The function is intentionally tolerant: per-source failures are
    swallowed because Contacts has many overlapping source DBs (one
    per CardDAV / iCloud / Exchange account) and a partial index is
    still useful.
    """
    import glob as _glob
    index: Dict[str, str] = {}
    for path in _glob.glob(glob_pattern):
        try:
            uri = "file:{}?mode=ro&immutable=1".format(path)
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
        except Exception:
            continue
        try:
            phone_rows = conn.execute("""
                SELECT r.ZFIRSTNAME AS first,
                       r.ZLASTNAME  AS last,
                       r.ZORGANIZATION AS org,
                       p.ZFULLNUMBER AS phone
                FROM ZABCDRECORD r
                JOIN ZABCDPHONENUMBER p ON p.ZOWNER = r.Z_PK
                WHERE p.ZFULLNUMBER IS NOT NULL
            """).fetchall()
            for r in phone_rows:
                name = _format_contact_name(r["first"], r["last"], r["org"])
                if not name:
                    continue
                digits = re.sub(r"\D", "", r["phone"] or "")
                if not digits:
                    continue
                # Prefer first writer; don't clobber existing entries
                index.setdefault(digits, name)
                # Also index without leading country-code "1" so US
                # numbers stored both ways collide on the same key.
                if len(digits) == 11 and digits.startswith("1"):
                    index.setdefault(digits[1:], name)

            email_rows = conn.execute("""
                SELECT r.ZFIRSTNAME AS first,
                       r.ZLASTNAME  AS last,
                       r.ZORGANIZATION AS org,
                       e.ZADDRESS AS email
                FROM ZABCDRECORD r
                JOIN ZABCDEMAILADDRESS e ON e.ZOWNER = r.Z_PK
                WHERE e.ZADDRESS IS NOT NULL
            """).fetchall()
            for r in email_rows:
                name = _format_contact_name(r["first"], r["last"], r["org"])
                if not name:
                    continue
                email = (r["email"] or "").strip().lower()
                if email:
                    index.setdefault(email, name)
        except sqlite3.Error:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass
    return index


def _format_contact_name(first: Optional[str], last: Optional[str],
                          org: Optional[str]) -> str:
    """Render a contact's display name from its fields."""
    parts = []
    if first:
        parts.append(first.strip())
    if last:
        parts.append(last.strip())
    name = " ".join(p for p in parts if p)
    if name:
        return name
    if org:
        return org.strip()
    return ""


def _lookup_contact(index: Dict[str, str], kind: str,
                    normalized: str) -> str:
    """Look up a normalized handle key in the contacts index.

    Tries the full normalized form first, then a US-style 10-digit
    fallback so "+18017265726" and "8017265726" collapse to the same
    contact regardless of how each source stored it.
    """
    if not index:
        return ""
    if kind == "phone":
        if normalized in index:
            return index[normalized]
        if len(normalized) == 11 and normalized.startswith("1"):
            short = normalized[1:]
            if short in index:
                return index[short]
        if len(normalized) == 10:
            longer = "1" + normalized
            if longer in index:
                return index[longer]
        return ""
    if kind == "email":
        return index.get(normalized, "")
    return ""


def _normalize_handle(handle_id: str) -> Tuple[str, str, str]:
    """Inspect a handle string and return (kind, normalized, display).

    handle.id values from chat.db look like "+18017258742" for SMS/
    phone iMessage and "matt@example.com" for Apple ID iMessage.

    Returns:
      kind:       "phone" or "email" or "unknown"
      normalized: digits-only for phone, lowercased for email, raw otherwise
      display:    a human-readable form suitable for the entity name
    """
    if not handle_id:
        return ("unknown", "", "")
    if "@" in handle_id:
        norm = handle_id.strip().lower()
        return ("email", norm, norm)
    digits = re.sub(r"\D", "", handle_id)
    if digits:
        return ("phone", digits, handle_id.strip())
    return ("unknown", handle_id.strip(), handle_id.strip())


class AppleMessagesConnector(ConnectorBase):
    """Read iMessage / SMS history from the macOS Messages.app SQLite DB."""

    name = "apple_messages"
    description = (
        "Read iMessage and SMS history from the local macOS "
        "Messages.app database (~/Library/Messages/chat.db). "
        "Requires Full Disk Access. Each message becomes a "
        "'message_sent' or 'message_received' chain entry. Handles "
        "become person entities; group chats become organization "
        "entities. Read-only — never writes to chat.db, never "
        "exfiltrates the database file."
    )
    version = "1.0"
    requires_auth = False  # No remote auth — only local file permission
    config_schema = {
        "db_path": {
            "type": "string",
            "required": False,
            "description": (
                "Override the chat.db path. Defaults to "
                "~/Library/Messages/chat.db."
            ),
        },
        "handle": {
            "type": "string",
            "required": False,
            "description": (
                "Filter to messages exchanged with one handle "
                "(phone number like '+18017258742' or Apple ID "
                "email). Matches loosely on digits / case."
            ),
        },
        "chat": {
            "type": "string",
            "required": False,
            "description": (
                "Filter to one chat by chat_identifier "
                "(individual conversations use the recipient handle; "
                "group chats use a 'chat...' identifier)."
            ),
        },
        "until": {
            "type": "string",
            "required": False,
            "description": "ISO 8601 upper bound on message date.",
        },
        "verbose": {
            "type": "bool",
            "required": False,
            "description": (
                "Print message text to stdout during the run. "
                "OFF by default — messages may contain sensitive "
                "content."
            ),
        },
        "contacts": {
            "type": "bool",
            "required": False,
            "description": (
                "Enrich handles with display names from Contacts.app "
                "(reads ~/Library/Application Support/AddressBook). "
                "Defaults to True. Falls back silently to raw "
                "handles if Contacts is unreadable."
            ),
        },
    }

    def validate_config(self, config: Optional[Dict[str, Any]] = None) -> List[str]:
        # No required fields. The default chat.db path works for any
        # macOS user. We do a soft existence check at run time so the
        # error surfaces in the result envelope, not in validation.
        return []

    def run(self, config: Optional[Dict[str, Any]] = None,
            since: Optional[str] = None,
            limit: Optional[int] = None,
            dry_run: bool = False) -> ConnectorResult:
        result = ConnectorResult(self.name)
        config = config or {}

        db_path = os.path.expanduser(
            config.get("db_path") or DEFAULT_CHAT_DB
        )
        handle_filter = config.get("handle") or None
        chat_filter = config.get("chat") or None
        until = config.get("until") or None
        verbose = bool(config.get("verbose"))
        use_contacts = config.get("contacts", True)

        result.metadata["db_path"] = db_path
        if handle_filter:
            result.metadata["handle_filter"] = handle_filter
        if chat_filter:
            result.metadata["chat_filter"] = chat_filter
        if since:
            result.metadata["since"] = since
        if until:
            result.metadata["until"] = until
        if limit:
            result.metadata["limit"] = limit

        # Existence check (clean error before sqlite, helps users
        # who haven't granted Full Disk Access yet).
        if not os.path.isfile(db_path):
            result.add_error(
                "chat.db not found at {}. If the path is correct, "
                "macOS Full Disk Access is likely missing for this "
                "process. Grant it via System Settings → Privacy & "
                "Security → Full Disk Access, then re-run.".format(
                    db_path
                )
            )
            result.finish()
            return result

        # Open read-only via URI mode. immutable=1 tells sqlite the
        # file will not change under it, which avoids any write-ahead
        # log probing that would touch the file.
        try:
            uri = "file:{}?mode=ro&immutable=1".format(db_path)
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            msg = str(e)
            if "authorization" in msg.lower() or "unable to open" in msg.lower():
                result.add_error(
                    "macOS denied access to chat.db ({}). Grant "
                    "Full Disk Access to this process: System "
                    "Settings → Privacy & Security → Full Disk "
                    "Access → add the Terminal / IDE running "
                    "Charter, then restart it.".format(msg)
                )
            else:
                result.add_error("sqlite open failed: {}".format(msg))
            result.finish()
            return result
        except Exception as e:
            result.add_error("sqlite open failed: {}".format(e))
            result.finish()
            return result

        contacts_index: Dict[str, str] = {}
        if use_contacts:
            try:
                contacts_index = _load_contacts_index()
                result.metadata["contacts_indexed"] = len(contacts_index)
            except Exception as e:
                result.metadata["contacts_indexed"] = 0
                result.add_error(
                    "contacts index failed: {}".format(str(e)[:120])
                )

        try:
            self._run_query(
                conn=conn,
                result=result,
                handle_filter=handle_filter,
                chat_filter=chat_filter,
                since=since,
                until=until,
                limit=limit,
                dry_run=dry_run,
                verbose=verbose,
                contacts_index=contacts_index,
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass

        result.finish()
        return result

    def _run_query(self, conn, result, handle_filter, chat_filter,
                   since, until, limit, dry_run, verbose,
                   contacts_index=None):
        # Build the WHERE clause and parameter list
        clauses = []
        params: List[Any] = []

        if since:
            apple_ns = iso_to_apple_ns(since)
            if apple_ns is None:
                result.add_error("could not parse since: {}".format(since))
            else:
                clauses.append("m.date >= ?")
                params.append(apple_ns)
        if until:
            apple_ns = iso_to_apple_ns(until)
            if apple_ns is None:
                result.add_error("could not parse until: {}".format(until))
            else:
                clauses.append("m.date < ?")
                params.append(apple_ns)

        if handle_filter:
            kind, normalized, _ = _normalize_handle(handle_filter)
            if kind == "phone":
                # Phone numbers in chat.db often include country code,
                # spaces, dashes. Match on the digits-only suffix.
                clauses.append(
                    "REPLACE(REPLACE(REPLACE(REPLACE(h.id, '+', ''), "
                    "' ', ''), '-', ''), '(', '') LIKE ?"
                )
                params.append("%" + normalized + "%")
            elif kind == "email":
                clauses.append("LOWER(h.id) = ?")
                params.append(normalized)
            else:
                clauses.append("h.id = ?")
                params.append(handle_filter)

        if chat_filter:
            clauses.append("c.chat_identifier = ?")
            params.append(chat_filter)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        limit_sql = "LIMIT ?" if limit else ""
        if limit:
            params.append(int(limit))

        sql = """
            SELECT
                m.ROWID            AS message_rowid,
                m.guid             AS message_guid,
                m.text             AS text,
                m.attributedBody   AS attributed_body,
                m.date             AS date,
                m.is_from_me       AS is_from_me,
                m.service          AS service,
                m.cache_has_attachments AS has_attachments,
                h.id               AS handle_id,
                h.service          AS handle_service,
                c.chat_identifier  AS chat_identifier,
                c.display_name     AS chat_display_name
            FROM message m
            LEFT JOIN handle h
                ON m.handle_id = h.ROWID
            LEFT JOIN chat_message_join cmj
                ON m.ROWID = cmj.message_id
            LEFT JOIN chat c
                ON cmj.chat_id = c.ROWID
            {where}
            ORDER BY m.date DESC
            {limit}
        """.format(where=where, limit=limit_sql)

        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as e:
            result.add_error("query failed: {}".format(e))
            return

        result.metadata["rows_returned"] = len(rows)

        # Per-run cache of graph entities so we don't re-open kuzu for
        # every message. Maps normalized handle key → True (entity
        # already created or merged this run).
        seen_handles: Dict[str, bool] = {}
        seen_chats: Dict[str, bool] = {}
        gm = None
        if not dry_run:
            try:
                import sys
                root = os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.dirname(os.path.abspath(__file__))
                )))
                if root not in sys.path:
                    sys.path.insert(0, root)
                from core.graph_memory.engine import GraphMemory
                gm = GraphMemory()
            except Exception as e:
                result.add_error(
                    "graph_memory unavailable: {}".format(e)
                )
                gm = None

        try:
            for row in rows:
                self._process_row(
                    row, result, gm, seen_handles, seen_chats,
                    dry_run=dry_run, verbose=verbose,
                    contacts_index=contacts_index or {},
                )
        finally:
            if gm is not None:
                try:
                    gm.close()
                except Exception:
                    pass

        result.metadata["unique_handles"] = len(seen_handles)
        result.metadata["unique_chats"] = len(seen_chats)

    def _process_row(self, row, result, gm, seen_handles, seen_chats,
                     dry_run, verbose, contacts_index=None):
        try:
            text = row["text"]
            if not text:
                text = _decode_attributed_body(row["attributed_body"])

            handle_id = row["handle_id"] or ""
            chat_identifier = row["chat_identifier"] or ""
            chat_display = row["chat_display_name"] or ""
            is_from_me = bool(row["is_from_me"])
            service = row["service"] or ""
            has_attachments = bool(row["has_attachments"])
            iso_date = apple_ns_to_iso(row["date"])

            event_type = "message_sent" if is_from_me else "message_received"

            event_data = {
                "service": service,
                "direction": "outbound" if is_from_me else "inbound",
                "handle": handle_id,
                "chat_identifier": chat_identifier,
                "is_group_chat": chat_identifier.startswith("chat"),
                "has_attachments": has_attachments,
                "timestamp": iso_date,
                "message_guid": row["message_guid"] or "",
                "text": (text or "")[:500],
                "text_truncated": bool(text and len(text) > 500),
            }

            if verbose:
                preview = (text or "").replace("\n", " ")[:120]
                arrow = ">>" if is_from_me else "<<"
                print("  {} {} {} | {}".format(
                    iso_date, arrow, handle_id or chat_identifier, preview,
                ))

            if not dry_run:
                self._record_event(event_type, event_data)
            result.events_recorded += 1

            # Graph entity for the handle (counterparty, not me)
            if handle_id and not dry_run and gm is not None:
                kind, normalized, display = _normalize_handle(handle_id)
                key = "{}:{}".format(kind, normalized)
                contact_name = _lookup_contact(
                    contacts_index or {}, kind, normalized,
                )
                # Attach the contact name to the chain entry as well so
                # downstream consumers don't have to re-resolve it.
                if contact_name:
                    event_data["contact_name"] = contact_name
                if key not in seen_handles:
                    added = self._merge_or_create_person(
                        gm, kind, normalized, display, handle_id,
                        contact_name=contact_name,
                    )
                    seen_handles[key] = True
                    if added:
                        result.entities_added += 1

            # Graph entity for the group chat
            if chat_identifier and chat_identifier.startswith("chat") \
                    and not dry_run and gm is not None:
                if chat_identifier not in seen_chats:
                    name = chat_display or chat_identifier
                    added = self._upsert_org(gm, chat_identifier, name)
                    seen_chats[chat_identifier] = True
                    if added:
                        result.entities_added += 1
        except Exception as e:
            result.add_error(
                "row {}: {}".format(
                    row["message_rowid"] if "message_rowid" in row.keys() else "?",
                    str(e)[:120],
                )
            )

    def _merge_or_create_person(self, gm, kind: str, normalized: str,
                                 display: str, raw_handle: str,
                                 contact_name: str = "") -> bool:
        """Find an existing person entity by phone/email or create one.

        If contact_name is supplied (from the Contacts.app index), it
        is used as the display name for newly created entities AND
        is used as a secondary lookup key — if no phone/email match
        exists, the connector will try to merge into an existing
        person entity with that exact name. This catches the common
        case where a person was added to the graph via the gmail or
        contacts ingestor before they ever appeared in iMessage.

        Returns True if a new entity was created (not just merged into).
        """
        try:
            from core.graph_memory.engine import make_id

            # 1) Try to find an existing entity with the same phone or email
            existing = None
            try:
                if kind == "phone":
                    rows = gm.backend.execute(
                        "MATCH (e:Entity) "
                        "WHERE e.entity_type = 'person' AND e.phone <> '' "
                        "RETURN e.id, e.name, e.phone, e.email"
                    )
                    for r in rows or []:
                        existing_phone = re.sub(r"\D", "", r.get("e.phone", "") or "")
                        if existing_phone and (
                            existing_phone.endswith(normalized)
                            or normalized.endswith(existing_phone)
                        ):
                            existing = r
                            break
                elif kind == "email":
                    rows = gm.backend.execute(
                        "MATCH (e:Entity) "
                        "WHERE e.entity_type = 'person' "
                        "AND LOWER(e.email) = $email "
                        "RETURN e.id, e.name, e.phone, e.email",
                        {"email": normalized},
                    )
                    if rows:
                        existing = rows[0]
            except Exception:
                # If the lookup fails (schema mismatch, kuzu quirk),
                # fall through to create-as-new path.
                existing = None

            # 1b) Fallback: try a name-based merge into an existing entity
            if not existing and contact_name:
                try:
                    name_id = make_id("person", contact_name)
                    by_name = gm.get_entity(name_id)
                    if by_name:
                        existing = {
                            "e.id": name_id,
                            "e.name": contact_name,
                            "e.phone": by_name.get("e.phone", "") or "",
                            "e.email": by_name.get("e.email", "") or "",
                        }
                except Exception:
                    pass

            if existing:
                # Merged into an existing entity — touch the phone/email
                # field if it was previously blank, but don't rename.
                try:
                    if kind == "phone" and not (existing.get("e.phone") or ""):
                        gm.backend.execute_write(
                            "MATCH (e:Entity) WHERE e.id = $id "
                            "SET e.phone = $phone",
                            {"id": existing["e.id"], "phone": raw_handle},
                        )
                    if kind == "email" and not (existing.get("e.email") or ""):
                        gm.backend.execute_write(
                            "MATCH (e:Entity) WHERE e.id = $id "
                            "SET e.email = $email",
                            {"id": existing["e.id"], "email": normalized},
                        )
                except Exception:
                    pass
                return False

            # 2) No match — create a new person entity. Prefer the
            # Contacts.app display name if we have one; otherwise
            # fall back to the raw handle (phone or email).
            name = contact_name or display or raw_handle
            entity_id = make_id("person", name)
            if gm.get_entity(entity_id):
                return False
            gm.add_entity(
                name=name,
                entity_type="person",
                email=(normalized if kind == "email" else ""),
                phone=(raw_handle if kind == "phone" else ""),
                context="apple_messages",
                properties={
                    "source": "apple_messages",
                    "handle_kind": kind,
                    "raw_handle": raw_handle,
                    "contacts_resolved": bool(contact_name),
                },
            )
            return True
        except Exception:
            return False

    def _upsert_org(self, gm, chat_identifier: str, name: str) -> bool:
        try:
            from core.graph_memory.engine import make_id
            entity_id = make_id("organization", chat_identifier)
            if gm.get_entity(entity_id):
                return False
            gm.add_entity(
                name=name,
                entity_type="organization",
                context="apple_messages_group_chat",
                properties={
                    "source": "apple_messages",
                    "chat_identifier": chat_identifier,
                },
                entity_id=entity_id,
            )
            return True
        except Exception:
            return False
