"""TikTok connector — TikTok Display API for creator accounts.

This is the second creator-economy connector (after Instagram). It pulls
videos and user info from a TikTok account through the TikTok Display API
(open.tiktokapis.com/v2) and normalizes them into Charter events.

Like instagram.py, this connector does not wrap an existing standalone
tool — there is no /tools/tiktok_api/ directory. This file is the first
place TikTok lives in this repo.

Auth model
----------
TikTok Display API uses OAuth 2.0 with a bearer access token. The token
is issued by the TikTok for Developers platform after a user completes
the Login Kit OAuth flow against an app that has been granted the
following scopes:

  - user.info.basic    (open_id, union_id, avatar, display_name)
  - user.info.profile  (bio, profile_deep_link, is_verified, username)
  - user.info.stats    (follower_count, following_count, likes_count, video_count)
  - video.list         (list videos owned by the user)

Access tokens are short-lived (24 hours). Refresh tokens last ~365 days.
This connector does NOT handle the OAuth dance itself — it expects a
valid access token to already be present. Use the TikTok Login Kit
sandbox or your app's OAuth flow to mint one. Token refresh is documented
as a future enhancement.

The connector resolves credentials in this order, per account name:

  1. config["access_token"] (inline)
  2. Env var TIKTOK_ACCESS_TOKEN_<ACCOUNT>
     (account name uppercased; e.g. TIKTOK_ACCESS_TOKEN_MYSUPEROIL)
  3. Env var TIKTOK_ACCESS_TOKEN (single-account fallback)
  4. ~/.charter/tiktok_accounts.json — a JSON map of:
       {
         "mysuperoil": {
           "access_token": "act.example12345...",
           "open_id": "_000000000000000000000"
         }
       }

The accounts file is the recommended path. The file should be 0600.
The `open_id` field is optional — TikTok's Display API endpoints scope
to the authenticated user automatically, so the connector only stores
open_id for reference and graph entity properties.

API quirks (what we learned)
----------------------------
The Display API has several rough edges that this connector papers over:

  1. **Inconsistent HTTP verbs across read endpoints.** /v2/user/info/
     is GET-only — POSTing to it returns an HTML 404 page, not a JSON
     error. /v2/video/list/ and /v2/video/query/ are POST-only because
     they take pagination params (max_count, cursor) in the body. The
     `fields` selector is always a comma-separated query string param
     regardless of method. We verified this empirically against the
     live endpoint in April 2026; older blog posts and copy-pasted
     examples sometimes get the methods wrong.

  2. **Fields go in the query string.** Unlike Meta Graph which accepts
     `fields` as a query param OR body param, TikTok requires `fields`
     to be a comma-separated query string. Putting fields in the body
     silently returns nothing.

  3. **No stable username for share URLs.** Videos come back with a
     `share_url` of the form https://www.tiktok.com/@username/video/<id>
     where the username can change if the user renames their handle.
     The stable identifier is `id` (video) and `open_id` (user).

  4. **Stats are on the video object, not a separate insights endpoint.**
     Unlike Instagram which requires a second /insights call per media,
     TikTok returns view_count, like_count, comment_count, and
     share_count inline with /v2/video/list/. One request = full data.

  5. **Sandbox mode is real.** During app review, TikTok runs you in
     sandbox where only your own test users can authenticate. This
     connector works fine in sandbox; the data shape is identical to
     production.

  6. **Error envelope is consistent.** Every response has an `error`
     object with `code`, `message`, and `log_id`. Code "ok" means
     success. Anything else is an error worth reporting.

Rate limits
-----------
TikTok Display API rate limits are not publicly documented as hard
numbers. The connector keeps each run small by default (limit=20) and
respects --limit. On HTTP 429 the connector backs off once with a
30-second sleep and retries. A second failure surfaces as an error.

Normalization
-------------
Each TikTok video becomes a 'content_published' chain event with:
  - the video share_url
  - title and description
  - duration
  - view_count, like_count, comment_count, share_count
  - timestamp (create_time, ISO 8601)

The TikTok account itself becomes an 'organization' entity in the graph
the first time the connector runs against it (named '@<username>').

Read-only
---------
This connector is read-only. It never writes to TikTok. The Display API
scopes requested are all read-scoped. The Content Posting API (which
would let an app upload videos) is intentionally NOT used.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from charter.connectors import ConnectorBase, ConnectorResult


TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"


def _get_accounts_file():
    """Resolve <charter_home>/tiktok_accounts.json at call time so multi-tenant
    deployments see the per-request charter home."""
    from charter.paths import get_charter_home
    return Path(get_charter_home()) / "tiktok_accounts.json"

# Fields supported on /v2/user/info/. These are what the Display API
# returns when the corresponding scopes have been approved.
USER_INFO_FIELDS = [
    "open_id",
    "union_id",
    "avatar_url",
    "display_name",
    "bio_description",
    "profile_deep_link",
    "is_verified",
    "username",
    "follower_count",
    "following_count",
    "likes_count",
    "video_count",
]

# Fields supported on /v2/video/list/.
VIDEO_LIST_FIELDS = [
    "id",
    "title",
    "video_description",
    "duration",
    "cover_image_url",
    "share_url",
    "embed_html",
    "embed_link",
    "create_time",
    "view_count",
    "like_count",
    "comment_count",
    "share_count",
]


class TikTokConnector(ConnectorBase):
    """Pull videos and account stats from a TikTok creator account."""

    name = "tiktok"
    description = (
        "Ingest videos and account stats from a TikTok account via "
        "the TikTok Display API (open.tiktokapis.com/v2). Each video "
        "becomes a 'content_published' chain entry with view, like, "
        "comment, and share counts. The TikTok account becomes an "
        "organization entity in the graph. Read-only. Requires a "
        "valid Display API access token (Login Kit OAuth)."
    )
    version = "1.0"
    requires_auth = True
    config_schema = {
        "account": {
            "type": "string",
            "required": True,
            "description": (
                "Account key used to look up credentials in env vars "
                "or ~/.charter/tiktok_accounts.json (e.g. 'mysuperoil')"
            ),
        },
        "access_token": {
            "type": "string",
            "required": False,
            "description": (
                "Inline TikTok Display API access token. Prefer the "
                "accounts file or env vars over inlining secrets."
            ),
        },
        "open_id": {
            "type": "string",
            "required": False,
            "description": (
                "TikTok open_id of the authenticated user. Optional — "
                "Display API endpoints scope to the authenticated "
                "user automatically. Stored as a graph property."
            ),
        },
    }

    def validate_config(self, config: Optional[Dict[str, Any]] = None) -> List[str]:
        errors: List[str] = []
        if not config:
            errors.append("config required")
            return errors
        if not config.get("account"):
            errors.append(
                "config.account required (the account key, e.g. "
                "'mysuperoil')"
            )
        return errors

    # ── credential resolution ─────────────────────────────────

    def _resolve_credentials(self, config: Dict[str, Any]) -> Tuple[
        Optional[str], Optional[str], Optional[str]
    ]:
        """Return (access_token, open_id, error_message)."""
        account = config["account"]

        # 1. Inline config
        token = config.get("access_token")
        open_id = config.get("open_id")
        if token:
            return token, open_id, None

        # 2. Per-account env vars
        env_key = account.upper().replace("-", "_")
        token = os.environ.get(
            "TIKTOK_ACCESS_TOKEN_{}".format(env_key)
        )
        open_id = open_id or os.environ.get(
            "TIKTOK_OPEN_ID_{}".format(env_key)
        )
        if token:
            return token, open_id, None

        # 3. Single-account env fallback
        token = os.environ.get("TIKTOK_ACCESS_TOKEN")
        open_id = open_id or os.environ.get("TIKTOK_OPEN_ID")
        if token:
            return token, open_id, None

        # 4. Accounts file
        accounts_file = _get_accounts_file()
        if accounts_file.exists():
            try:
                with open(accounts_file) as f:
                    accounts = json.load(f)
            except json.JSONDecodeError as e:
                return None, None, (
                    "{} is not valid JSON: {}".format(accounts_file, e)
                )
            entry = accounts.get(account)
            if isinstance(entry, dict):
                token = entry.get("access_token")
                open_id = open_id or entry.get("open_id")
                if token:
                    return token, open_id, None

        return None, None, (
            "missing TikTok credentials for account '{}': no "
            "access_token. Set TIKTOK_ACCESS_TOKEN_{} env var, or "
            "add an entry to {}. The token must be a TikTok Display "
            "API access token with user.info.basic, user.info.stats, "
            "and video.list scopes. Tokens are short-lived (24h); "
            "refresh via the TikTok Login Kit OAuth flow.".format(
                account, env_key, accounts_file,
            )
        )

    # ── HTTP helper ───────────────────────────────────────────

    def _tiktok_request(self, requests, method: str, path: str,
                         fields: Optional[List[str]],
                         body: Optional[Dict[str, Any]],
                         access_token: str,
                         result: ConnectorResult,
                         retries: int = 1) -> Optional[Dict[str, Any]]:
        """Issue a Display API request with one rate-limit retry.

        Display API endpoints split between GET and POST based on
        whether they take pagination params. /v2/user/info/ is GET-only;
        /v2/video/list/ and /v2/video/query/ are POST. The `fields`
        selector is always a comma-separated query string param. POST
        bodies carry pagination (max_count, cursor) and filters.

        Returns the parsed `data` dict on success, or None on
        unrecoverable error (which is recorded in result).
        """
        url = "{}/{}".format(TIKTOK_API_BASE, path.lstrip("/"))
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        headers = {
            "Authorization": "Bearer {}".format(access_token),
            "Content-Type": "application/json",
        }
        method_upper = method.upper()
        try:
            if method_upper == "GET":
                resp = requests.get(
                    url, params=params, headers=headers, timeout=30,
                )
            else:
                resp = requests.post(
                    url, params=params, json=(body or {}),
                    headers=headers, timeout=30,
                )
        except Exception as e:
            result.add_error(
                "{} {} network error: {}".format(
                    method_upper, path, str(e)[:120]
                )
            )
            return None

        # Try to parse JSON regardless of status — TikTok's error
        # envelope lives in the body even on 4xx.
        try:
            payload = resp.json()
        except ValueError:
            result.add_error(
                "{} {} returned non-JSON body (HTTP {})".format(
                    method_upper, path, resp.status_code
                )
            )
            return None

        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        err_code = err.get("code", "")
        err_msg = err.get("message", "")
        log_id = err.get("log_id", "")

        if resp.status_code == 200 and err_code == "ok":
            return payload.get("data", {}) or {}

        # Token expired or invalid
        if err_code in (
            "access_token_invalid",
            "access_token_expired",
            "scope_not_authorized",
        ):
            result.add_error(
                "TikTok access token rejected ({}): {}. Refresh the "
                "token via the Login Kit OAuth flow. Display API "
                "access tokens last ~24 hours; refresh tokens last "
                "~365 days. (log_id={})".format(err_code, err_msg, log_id)
            )
            return None

        # Rate limit
        if resp.status_code == 429 or err_code == "rate_limit_exceeded":
            if retries > 0:
                time.sleep(30)
                return self._tiktok_request(
                    requests, method_upper, path, fields, body,
                    access_token, result, retries=retries - 1,
                )
            result.add_error(
                "TikTok rate limit hit on {}. Reduce --limit or "
                "wait. (log_id={})".format(path, log_id)
            )
            return None

        result.add_error(
            "{} {} failed: HTTP {} code={} msg={} log_id={}".format(
                method_upper, path, resp.status_code, err_code,
                err_msg[:120], log_id
            )
        )
        return None

    # ── normalization helpers ─────────────────────────────────

    def _create_time_to_iso(self, create_time: Any) -> str:
        """Convert TikTok create_time (unix seconds int) to ISO 8601."""
        try:
            ts = int(create_time)
        except (TypeError, ValueError):
            return ""
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        except Exception:
            return ""

    # ── main run ──────────────────────────────────────────────

    def run(self, config: Optional[Dict[str, Any]] = None,
            since: Optional[str] = None,
            limit: Optional[int] = None,
            dry_run: bool = False) -> ConnectorResult:
        result = ConnectorResult(self.name)

        errors = self.validate_config(config)
        if errors:
            for e in errors:
                result.add_error(e)
            result.finish()
            return result

        try:
            import requests
        except ImportError:
            result.add_error(
                "requests library not installed (pip install requests)"
            )
            result.finish()
            return result

        access_token, open_id, cred_err = self._resolve_credentials(config)
        if cred_err:
            result.add_error(cred_err)
            result.finish()
            return result

        account = config["account"]
        max_items = limit or 20

        result.metadata["account"] = account
        if open_id:
            result.metadata["open_id"] = open_id

        # 1. Fetch user info — also validates the token before we spend
        #    any rate budget on video calls. /v2/user/info/ is GET-only;
        #    POSTing to it returns HTML 404 (verified empirically against
        #    the live endpoint April 2026).
        user_data = self._tiktok_request(
            requests,
            method="GET",
            path="user/info/",
            fields=USER_INFO_FIELDS,
            body=None,
            access_token=access_token,
            result=result,
        )
        if user_data is None:
            result.finish()
            return result

        user = user_data.get("user", {}) or {}
        username = user.get("username") or user.get("display_name") or account
        result.metadata["username"] = username
        result.metadata["display_name"] = user.get("display_name", "")
        result.metadata["follower_count"] = user.get("follower_count")
        result.metadata["video_count"] = user.get("video_count")

        # Update open_id from API response if we didn't have it
        if not open_id:
            open_id = user.get("open_id")
            if open_id:
                result.metadata["open_id"] = open_id

        if not dry_run:
            added = self._add_entity(
                entity_type="organization",
                name="@{}".format(username),
                context="tiktok",
                properties={
                    "tiktok_open_id": open_id or "",
                    "tiktok_union_id": user.get("union_id", "") or "",
                    "display_name": user.get("display_name", "") or "",
                    "follower_count": user.get("follower_count", 0) or 0,
                    "following_count": user.get("following_count", 0) or 0,
                    "likes_count": user.get("likes_count", 0) or 0,
                    "video_count": user.get("video_count", 0) or 0,
                    "is_verified": bool(user.get("is_verified", False)),
                    "profile_deep_link": user.get(
                        "profile_deep_link", ""
                    ) or "",
                    "bio": (user.get("bio_description", "") or "")[:300],
                },
            )
            if added:
                result.entities_added += 1

        # 2. Pull video list. Display API caps max_count at 20 per page.
        page_size = min(max_items, 20)
        videos: List[Dict[str, Any]] = []
        cursor = 0
        has_more = True

        while has_more and len(videos) < max_items:
            data = self._tiktok_request(
                requests,
                method="POST",
                path="video/list/",
                fields=VIDEO_LIST_FIELDS,
                body={
                    "max_count": page_size,
                    "cursor": cursor,
                },
                access_token=access_token,
                result=result,
            )
            if data is None:
                # Error already recorded; bail out of pagination
                break

            page_videos = data.get("videos", []) or []
            videos.extend(page_videos)

            has_more = bool(data.get("has_more", False))
            cursor = data.get("cursor", 0) or 0
            if not page_videos:
                break

        # Apply 'since' filter (compare ISO 8601 strings against
        # converted create_time)
        if since:
            filtered = []
            for v in videos:
                v_iso = self._create_time_to_iso(v.get("create_time"))
                if v_iso and v_iso >= since:
                    filtered.append(v)
            videos = filtered

        videos = videos[:max_items]
        result.metadata["videos_pulled"] = len(videos)

        # 3. Normalize each video into a content_published event
        for v in videos:
            video_id = v.get("id", "")
            share_url = v.get("share_url", "")
            iso_ts = self._create_time_to_iso(v.get("create_time"))

            if not dry_run:
                self._record_event(
                    "content_published",
                    {
                        "platform": "tiktok",
                        "account": "@{}".format(username),
                        "video_id": video_id,
                        "share_url": share_url,
                        "title": (v.get("title") or "")[:300],
                        "description": (
                            v.get("video_description") or ""
                        )[:500],
                        "duration_seconds": v.get("duration", 0) or 0,
                        "view_count": v.get("view_count", 0) or 0,
                        "like_count": v.get("like_count", 0) or 0,
                        "comment_count": v.get("comment_count", 0) or 0,
                        "share_count": v.get("share_count", 0) or 0,
                        "cover_image_url": v.get(
                            "cover_image_url", ""
                        ) or "",
                        "embed_link": v.get("embed_link", "") or "",
                        "timestamp": iso_ts,
                    },
                )
            result.events_recorded += 1

        result.finish()
        return result
