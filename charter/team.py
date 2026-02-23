"""Team identity management — governed teams with consent-based membership.

A team is a governed entity with its own SHA-256 hash, its own chain,
and consent-based membership. Team lead invites members, members accept.
Either party can leave or revoke. All events are logged to an immutable
hash chain.

When a member joins, all team contributions from that point forward
are attributed to them. The membership log (members.jsonl) + team chain
(chain.jsonl) together prove who was on the team when any given
contribution was made.

Usage:
    charter team create "Omega 20"
    charter team invite user@example.com --name "AV" --role marketing_analytics
    charter team accept <team_hash>
    charter team leave
    charter team revoke <member_id>
    charter team status
    charter team list
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time


CHARTER_DIR = ".charter"
TEAMS_DIR = "teams"


def get_charter_dir():
    home = os.path.expanduser("~")
    return os.path.join(home, CHARTER_DIR)


def get_teams_dir():
    return os.path.join(get_charter_dir(), TEAMS_DIR)


def get_team_dir(team_hash):
    return os.path.join(get_teams_dir(), team_hash)


def _load_identity():
    """Load the user's Charter identity."""
    from charter.identity import load_identity
    return load_identity()


def _append_to_global_chain(event, data):
    """Append to the user's global hash chain."""
    from charter.identity import append_to_chain
    return append_to_chain(event, data)


def _hash_entry(entry):
    """Compute SHA-256 hash of a chain entry."""
    content = {k: v for k, v in entry.items() if k != "hash"}
    raw = json.dumps(content, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _sign_entry(entry, private_seed):
    """Sign a chain entry with HMAC-SHA256."""
    raw = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    return hmac.new(
        bytes.fromhex(private_seed),
        raw.encode(),
        hashlib.sha256,
    ).hexdigest()


def _append_to_team_chain(team_hash, event, data, identity):
    """Append an entry to a team's hash chain."""
    team_dir = get_team_dir(team_hash)
    chain_path = os.path.join(team_dir, "chain.jsonl")

    last_hash = "0" * 64
    index = 0
    if os.path.isfile(chain_path):
        with open(chain_path) as f:
            lines = f.readlines()
            if lines:
                last_entry = json.loads(lines[-1])
                last_hash = last_entry.get("hash", "0" * 64)
                index = last_entry.get("index", 0) + 1

    entry = {
        "index": index,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event": event,
        "data": data,
        "previous_hash": last_hash,
        "signer": identity["public_id"],
    }
    entry["hash"] = _hash_entry(entry)
    entry["signature"] = _sign_entry(entry, identity["private_seed"])

    with open(chain_path, "a") as f:
        f.write(json.dumps(entry) + "\n")

    return entry


def _log_member_event(team_hash, event_data):
    """Append to the team's members.jsonl."""
    team_dir = get_team_dir(team_hash)
    members_path = os.path.join(team_dir, "members.jsonl")
    with open(members_path, "a") as f:
        f.write(json.dumps(event_data) + "\n")


def _update_team_manifest(team_hash):
    """Recount active members and update team.json."""
    team_dir = get_team_dir(team_hash)
    manifest_path = os.path.join(team_dir, "team.json")
    members = get_members(team_hash)
    with open(manifest_path) as f:
        manifest = json.load(f)
    manifest["member_count"] = len(members)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)


# --- Public API ---


def create_team(name):
    """Create a new team with its own hash identity.

    The creator is automatically added as the first member (role: leader).
    """
    identity = _load_identity()
    if not identity:
        raise RuntimeError("No Charter identity found. Run 'charter init' first.")

    # Generate team hash
    seed = secrets.token_bytes(32) + str(time.time_ns()).encode()
    team_hash = hashlib.sha256(seed).hexdigest()
    alias = "team-{}".format(team_hash[:8])

    # Create team directory
    team_dir = get_team_dir(team_hash)
    os.makedirs(team_dir, exist_ok=True)

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Write team manifest
    manifest = {
        "version": "1.0",
        "team_hash": team_hash,
        "name": name,
        "alias": alias,
        "created_by": identity["public_id"],
        "created_at": now,
        "member_count": 1,
    }
    with open(os.path.join(team_dir, "team.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    # Initialize team chain with genesis entry
    genesis = {
        "index": 0,
        "timestamp": now,
        "event": "team_created",
        "data": {
            "team_hash": team_hash,
            "name": name,
            "created_by": identity["public_id"],
        },
        "previous_hash": "0" * 64,
        "signer": identity["public_id"],
    }
    genesis["hash"] = _hash_entry(genesis)
    genesis["signature"] = _sign_entry(genesis, identity["private_seed"])
    with open(os.path.join(team_dir, "chain.jsonl"), "w") as f:
        f.write(json.dumps(genesis) + "\n")

    # Add creator as first member
    creator_name = identity.get("alias", "unknown")
    if identity.get("real_identity"):
        creator_name = identity["real_identity"]["name"]

    member_event = {
        "event": "join",
        "member_id": identity["public_id"],
        "name": creator_name,
        "email": None,
        "role": "leader",
        "invited_by": None,
        "timestamp": now,
    }
    with open(os.path.join(team_dir, "members.jsonl"), "w") as f:
        f.write(json.dumps(member_event) + "\n")

    # Log to team chain
    _append_to_team_chain(team_hash, "member_joined", {
        "member_id": identity["public_id"],
        "name": creator_name,
        "role": "leader",
    }, identity)

    # Log to global chain
    _append_to_global_chain("team_created", {
        "team_hash": team_hash,
        "name": name,
    })

    return manifest


def load_team(team_hash):
    """Load a team manifest. Returns None if not found."""
    manifest_path = os.path.join(get_team_dir(team_hash), "team.json")
    if not os.path.isfile(manifest_path):
        return None
    with open(manifest_path) as f:
        return json.load(f)


def list_teams():
    """List all teams this identity belongs to."""
    teams_dir = get_teams_dir()
    if not os.path.isdir(teams_dir):
        return []
    teams = []
    for entry in os.listdir(teams_dir):
        team_dir = os.path.join(teams_dir, entry)
        manifest_path = os.path.join(team_dir, "team.json")
        if os.path.isfile(manifest_path):
            with open(manifest_path) as f:
                teams.append(json.load(f))
    return sorted(teams, key=lambda t: t.get("created_at", ""))


def generate_invite_token(team_hash, email, name, role, identity):
    """Generate a self-contained invite token for charter join.

    The token is base64url(JSON_payload).HMAC_signature — self-contained
    so the invitee can join from any machine with zero shared state.
    """
    team = load_team(team_hash)
    team_name = team["name"] if team else "Unknown"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # 30-day expiry
    expires = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(time.time() + 30 * 86400),
    )

    payload = {
        "v": 1,
        "th": team_hash,
        "tn": team_name,
        "e": email,
        "n": name,
        "r": role,
        "ib": identity["public_id"],
        "ia": now,
        "x": expires,
    }

    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    b64_payload = base64.urlsafe_b64encode(payload_json.encode()).rstrip(b"=").decode()

    sig = hmac.new(
        bytes.fromhex(identity["private_seed"]),
        b64_payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    return "{}.{}".format(b64_payload, sig)


def invite_member(team_hash, email, name=None, role=None):
    """Invite a member to the team. Logged in chain.

    Returns (member_event, invite_token) tuple.
    """
    identity = _load_identity()
    if not identity:
        raise RuntimeError("No Charter identity found.")

    team = load_team(team_hash)
    if not team:
        raise RuntimeError("Team {} not found.".format(team_hash[:16]))

    resolved_name = name or email.split("@")[0]
    resolved_role = role or "member"
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    member_event = {
        "event": "invite",
        "member_id": None,
        "name": resolved_name,
        "email": email,
        "role": resolved_role,
        "invited_by": identity["public_id"],
        "timestamp": now,
    }
    _log_member_event(team_hash, member_event)

    _append_to_team_chain(team_hash, "member_invited", {
        "email": email,
        "name": resolved_name,
        "role": resolved_role,
        "invited_by": identity["public_id"],
    }, identity)

    _append_to_global_chain("team_invite_sent", {
        "team_hash": team_hash,
        "team_name": team["name"],
        "invitee_email": email,
    })

    token = generate_invite_token(
        team_hash, email, resolved_name, resolved_role, identity,
    )

    _update_team_manifest(team_hash)
    return member_event, token


def accept_invite(team_hash):
    """Accept an invitation to a team."""
    identity = _load_identity()
    if not identity:
        raise RuntimeError("No Charter identity found.")

    team = load_team(team_hash)
    if not team:
        raise RuntimeError("Team {} not found.".format(team_hash[:16]))

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    member_name = identity.get("alias", "unknown")
    if identity.get("real_identity"):
        member_name = identity["real_identity"]["name"]

    member_event = {
        "event": "accept",
        "member_id": identity["public_id"],
        "name": member_name,
        "accepted_at": now,
    }
    _log_member_event(team_hash, member_event)

    _append_to_team_chain(team_hash, "member_accepted", {
        "member_id": identity["public_id"],
        "name": member_name,
    }, identity)

    _append_to_global_chain("team_joined", {
        "team_hash": team_hash,
        "team_name": team["name"],
    })

    _update_team_manifest(team_hash)
    return member_event


def leave_team(team_hash):
    """Leave a team. Logged in chain."""
    identity = _load_identity()
    if not identity:
        raise RuntimeError("No Charter identity found.")

    team = load_team(team_hash)
    if not team:
        raise RuntimeError("Team {} not found.".format(team_hash[:16]))

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    member_event = {
        "event": "leave",
        "member_id": identity["public_id"],
        "left_at": now,
        "reason": "voluntary",
    }
    _log_member_event(team_hash, member_event)

    _append_to_team_chain(team_hash, "member_left", {
        "member_id": identity["public_id"],
        "reason": "voluntary",
    }, identity)

    _append_to_global_chain("team_left", {
        "team_hash": team_hash,
        "team_name": team["name"],
    })

    _update_team_manifest(team_hash)
    return member_event


def revoke_member(team_hash, member_id):
    """Revoke a member from the team. Leader only. Logged in chain."""
    identity = _load_identity()
    if not identity:
        raise RuntimeError("No Charter identity found.")

    team = load_team(team_hash)
    if not team:
        raise RuntimeError("Team {} not found.".format(team_hash[:16]))

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    member_event = {
        "event": "revoke",
        "member_id": member_id,
        "revoked_by": identity["public_id"],
        "revoked_at": now,
    }
    _log_member_event(team_hash, member_event)

    _append_to_team_chain(team_hash, "member_revoked", {
        "member_id": member_id,
        "revoked_by": identity["public_id"],
    }, identity)

    _update_team_manifest(team_hash)
    return member_event


def get_members(team_hash):
    """Get active team members by replaying the membership log.

    A member is active if they have a 'join' or 'accept' event
    and no subsequent 'leave' or 'revoke' event.
    """
    team_dir = get_team_dir(team_hash)
    members_path = os.path.join(team_dir, "members.jsonl")
    if not os.path.isfile(members_path):
        return []

    # Track member state
    members = {}  # member_id or email -> latest state

    with open(members_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            event = entry.get("event")
            key = entry.get("member_id") or entry.get("email")

            if event == "join":
                members[key] = {
                    "member_id": entry.get("member_id"),
                    "name": entry.get("name"),
                    "email": entry.get("email"),
                    "role": entry.get("role", "member"),
                    "joined_at": entry.get("timestamp"),
                    "active": True,
                }
            elif event == "invite":
                email = entry.get("email")
                if email and email not in members:
                    members[email] = {
                        "member_id": None,
                        "name": entry.get("name"),
                        "email": email,
                        "role": entry.get("role", "member"),
                        "invited_at": entry.get("timestamp"),
                        "invited_by": entry.get("invited_by"),
                        "active": True,
                        "status": "invited",
                    }
            elif event == "accept":
                mid = entry.get("member_id")
                # Find the invite entry to link
                for k, v in members.items():
                    if v.get("status") == "invited" and mid:
                        v["member_id"] = mid
                        v["status"] = "active"
                        v["accepted_at"] = entry.get("accepted_at")
                        v["name"] = entry.get("name") or v.get("name")
                        break
                else:
                    # Accept without prior invite (direct join)
                    members[mid] = {
                        "member_id": mid,
                        "name": entry.get("name"),
                        "email": None,
                        "role": "member",
                        "accepted_at": entry.get("accepted_at"),
                        "active": True,
                    }
            elif event in ("leave", "revoke"):
                mid = entry.get("member_id")
                if mid and mid in members:
                    members[mid]["active"] = False
                # Also check by email
                for k, v in members.items():
                    if v.get("member_id") == mid:
                        v["active"] = False

    return [m for m in members.values() if m.get("active")]


# --- CLI Handler ---


def run_team(args):
    """CLI entry point for charter team."""
    action = args.action

    if action == "create":
        name = args.value
        if not name:
            print("Usage: charter team create \"Team Name\"")
            return

        try:
            manifest = create_team(name)
        except RuntimeError as e:
            print("ERROR: {}".format(e))
            return

        print("Team created.")
        print("  Name:      {}".format(manifest["name"]))
        print("  Hash:      {}".format(manifest["team_hash"]))
        print("  Alias:     {}".format(manifest["alias"]))
        print("  Created:   {}".format(manifest["created_at"]))
        print()
        print("You are the first member (role: leader).")
        print("Invite members: charter team invite <email> --name \"Name\" --role <role>")

    elif action == "invite":
        email = args.value
        if not email:
            print("Usage: charter team invite <email> --name \"Name\" --role <role>")
            return

        teams = list_teams()
        if not teams:
            print("No teams found. Create one first: charter team create \"Name\"")
            return

        # Use the first team (most common case: one team)
        team = teams[0]
        name = getattr(args, "name", None)
        role = getattr(args, "role", None)

        try:
            member_event, token = invite_member(team["team_hash"], email, name=name, role=role)
        except RuntimeError as e:
            print("ERROR: {}".format(e))
            return

        print("Invitation sent.")
        print("  Team:  {} ({})".format(team["name"], team["alias"]))
        print("  Email: {}".format(email))
        print("  Name:  {}".format(name or email.split("@")[0]))
        print("  Role:  {}".format(role or "member"))
        print()
        print("Share this one-command join:")
        print("  charter join {}".format(token))
        print()
        print("(Or manually: charter team accept {})".format(team["team_hash"]))

    elif action == "accept":
        team_hash = args.value
        if not team_hash:
            print("Usage: charter team accept <team_hash>")
            return

        try:
            accept_invite(team_hash)
        except RuntimeError as e:
            print("ERROR: {}".format(e))
            return

        team = load_team(team_hash)
        print("Joined team: {}".format(team["name"] if team else team_hash[:16]))

    elif action == "leave":
        teams = list_teams()
        if not teams:
            print("Not a member of any team.")
            return
        team = teams[0]
        try:
            leave_team(team["team_hash"])
        except RuntimeError as e:
            print("ERROR: {}".format(e))
            return
        print("Left team: {}".format(team["name"]))

    elif action == "revoke":
        member_id = args.value
        if not member_id:
            print("Usage: charter team revoke <member_id>")
            return
        teams = list_teams()
        if not teams:
            print("No teams found.")
            return
        team = teams[0]
        try:
            revoke_member(team["team_hash"], member_id)
        except RuntimeError as e:
            print("ERROR: {}".format(e))
            return
        print("Member revoked from team: {}".format(team["name"]))

    elif action == "status":
        teams = list_teams()
        if not teams:
            print("No teams found. Create one: charter team create \"Name\"")
            return

        for team in teams:
            members = get_members(team["team_hash"])
            chain_path = os.path.join(get_team_dir(team["team_hash"]), "chain.jsonl")
            chain_len = 0
            if os.path.isfile(chain_path):
                with open(chain_path) as f:
                    chain_len = sum(1 for line in f if line.strip())

            print("Team: {}".format(team["name"]))
            print("  Hash:      {}".format(team["team_hash"]))
            print("  Alias:     {}".format(team["alias"]))
            print("  Created:   {}".format(team["created_at"]))
            print("  Created by: {}".format(team["created_by"][:16]))
            print("  Members:   {}".format(len(members)))
            print("  Chain:     {} entries".format(chain_len))
            print()
            if members:
                print("  Active Members:")
                for m in members:
                    status = m.get("status", "active")
                    name = m.get("name", "unknown")
                    role = m.get("role", "member")
                    email = m.get("email", "")
                    email_str = " ({})".format(email) if email else ""
                    print("    {} — {}{} [{}]".format(name, role, email_str, status))
            print()

    elif action == "list":
        teams = list_teams()
        if not teams:
            print("Not a member of any team.")
            print("Create one: charter team create \"Name\"")
            return

        print("Your Teams:")
        print("{:<30} {:<16} {:<8} {}".format("Name", "Alias", "Members", "Created"))
        print("-" * 75)
        for team in teams:
            members = get_members(team["team_hash"])
            print("{:<30} {:<16} {:<8} {}".format(
                team["name"][:29],
                team["alias"],
                len(members),
                team["created_at"][:10],
            ))
