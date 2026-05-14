"""Instagram connector — Meta Graph API for Instagram Business accounts.

This is the first creator-economy connector. It pulls posts, engagement
metrics, and comments from an Instagram Business account through the
Meta Graph API and normalizes them into Charter events.

Unlike gmail.py and shopify.py, this connector does not wrap an existing
standalone tool. There is no /tools/instagram_api/ directory yet — this
connector is the first place Instagram lives in this repo.

Auth model
----------
Instagram Business accounts authenticate through the Meta Graph API
with a Page access token. The token must be issued against a Facebook
Page that is linked to the target Instagram Business account, and the
app must have the instagram_basic, instagram_manage_insights, and
pages_read_engagement permissions approved.

The connector resolves credentials in this order, per account name:

  1. config["access_token"] and config["ig_user_id"] (inline)
  2. Env vars IG_ACCESS_TOKEN_<ACCOUNT> + IG_USER_ID_<ACCOUNT>
     (account name uppercased; e.g. IG_ACCESS_TOKEN_MYSUPEROIL)
  3. Env vars IG_ACCESS_TOKEN + IG_USER_ID (single-account fallback)
  4. ~/.charter/instagram_accounts.json — a JSON map of:
       {
         "mysuperoil": {
           "access_token": "EAAG...",
           "ig_user_id": "17841400000000000"
         }
       }

The accounts file is the recommended path because it keeps secrets out
of shell history and out of the chain. The file should be 0600.

Long-lived Page tokens last ~60 days. The connector detects token
expiration (Meta error code 190) and returns a clear remediation
message — it does NOT silently fail.

Rate limits
-----------
Meta Graph API rate limits are app-level (200 calls per user per hour
on the basic tier). The connector keeps each run small by default
(limit=25) and respects --limit. On HTTP 429 or Meta error codes 4 and
17 (app/user rate limit), the connector backs off once with a 30-second
sleep and retries. A second failure surfaces as an error.

Normalization
-------------
Each Instagram media item becomes a 'content_published' chain event
with the post URL, caption, media type, like count, and comment count.

Each insight metric (impressions, reach, engagement, saved) becomes a
separate 'metric_recorded' chain event tied to the post permalink.

Each comment becomes a 'engagement_received' chain event with the
commenter username and text snippet.

The Instagram account itself becomes an 'organization' entity in the
graph the first time the connector runs against it. Commenters become
'person' entities (with the IG username, no email).

Read-only
---------
This connector is read-only. It never writes to Instagram. The Meta
Graph API permissions requested are all read-scoped.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from charter.connectors import ConnectorBase, ConnectorResult


GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = "https://graph.facebook.com/{}".format(GRAPH_API_VERSION)


def _get_accounts_file():
    """Resolve <charter_home>/instagram_accounts.json at call time so
    multi-tenant deployments see the per-request charter home."""
    from charter.paths import get_charter_home
    return Path(get_charter_home()) / "instagram_accounts.json"

# Insight metrics that work for IG Business media in v21.0.
# Note: 'impressions' was deprecated for some media types after Apr 2024;
# we request the safe set and let the API drop unsupported metrics
# per-item without failing the run.
DEFAULT_MEDIA_METRICS = ["reach", "saved", "shares", "likes", "comments"]


class InstagramConnector(ConnectorBase):
    """Pull posts, insights, and comments from Instagram Business accounts."""

    name = "instagram"
    description = (
        "Ingest posts, engagement metrics, and comments from an "
        "Instagram Business account via the Meta Graph API. Each "
        "post becomes a 'content_published' chain entry. Each "
        "insight metric becomes a 'metric_recorded' entry. Each "
        "comment becomes an 'engagement_received' entry. The IG "
        "account becomes an organization entity in the graph. "
        "Read-only. Requires a long-lived Page access token."
    )
    version = "1.0"
    requires_auth = True
    config_schema = {
        "account": {
            "type": "string",
            "required": True,
            "description": (
                "Account key used to look up credentials in env "
                "vars or ~/.charter/instagram_accounts.json "
                "(e.g. 'mysuperoil')"
            ),
        },
        "access_token": {
            "type": "string",
            "required": False,
            "description": (
                "Inline long-lived Page access token. Prefer the "
                "accounts file or env vars over inlining secrets."
            ),
        },
        "ig_user_id": {
            "type": "string",
            "required": False,
            "description": (
                "Instagram Business Account ID (numeric). Required "
                "if not stored in the accounts file or env."
            ),
        },
        "include": {
            "type": "list",
            "required": False,
            "description": (
                "Which resources to ingest. Subset of "
                "['media', 'insights', 'comments']. "
                "Default: all three."
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
        include = config.get("include")
        if include is not None:
            if not isinstance(include, list):
                errors.append("config.include must be a list")
            else:
                allowed = {"media", "insights", "comments"}
                bad = [i for i in include if i not in allowed]
                if bad:
                    errors.append(
                        "config.include has unknown resources: {} "
                        "(allowed: media, insights, comments)".format(bad)
                    )
        return errors

    # ── credential resolution ─────────────────────────────────

    def _resolve_credentials(self, config: Dict[str, Any]) -> Tuple[
        Optional[str], Optional[str], Optional[str]
    ]:
        """Return (access_token, ig_user_id, error_message)."""
        account = config["account"]

        # 1. Inline config
        token = config.get("access_token")
        user_id = config.get("ig_user_id")
        if token and user_id:
            return token, user_id, None

        # 2. Per-account env vars
        env_key = account.upper().replace("-", "_")
        token = token or os.environ.get(
            "IG_ACCESS_TOKEN_{}".format(env_key)
        )
        user_id = user_id or os.environ.get(
            "IG_USER_ID_{}".format(env_key)
        )
        if token and user_id:
            return token, user_id, None

        # 3. Single-account env fallback
        token = token or os.environ.get("IG_ACCESS_TOKEN")
        user_id = user_id or os.environ.get("IG_USER_ID")
        if token and user_id:
            return token, user_id, None

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
                token = token or entry.get("access_token")
                user_id = user_id or entry.get("ig_user_id")
                if token and user_id:
                    return token, user_id, None

        missing = []
        if not token:
            missing.append("access_token")
        if not user_id:
            missing.append("ig_user_id")
        return None, None, (
            "missing Instagram credentials for account '{}': {}. "
            "Set them via inline config, env vars "
            "IG_ACCESS_TOKEN_{} / IG_USER_ID_{}, or add an entry to "
            "{}. The token must be a long-lived Page access token "
            "with instagram_basic, instagram_manage_insights, and "
            "pages_read_engagement scopes.".format(
                account, ", ".join(missing), env_key, env_key,
                accounts_file,
            )
        )

    # ── HTTP helpers ──────────────────────────────────────────

    def _graph_get(self, requests, path: str, params: Dict[str, Any],
                    result: ConnectorResult,
                    retries: int = 1) -> Optional[Dict[str, Any]]:
        """GET against the Graph API with one rate-limit retry.

        Returns the parsed JSON dict on success, or None on
        unrecoverable error (which is recorded in result).
        """
        url = "{}/{}".format(GRAPH_API_BASE, path.lstrip("/"))
        try:
            resp = requests.get(url, params=params, timeout=30)
        except Exception as e:
            result.add_error(
                "GET {} network error: {}".format(path, str(e)[:120])
            )
            return None

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError:
                result.add_error(
                    "GET {} returned non-JSON body".format(path)
                )
                return None

        # Try to extract a Meta error code for better diagnostics
        meta_code = None
        meta_msg = ""
        try:
            err = resp.json().get("error", {})
            meta_code = err.get("code")
            meta_msg = err.get("message", "")
        except Exception:
            pass

        # OAuth / token expired (Meta code 190)
        if meta_code == 190:
            result.add_error(
                "Instagram access token is expired or invalid (Meta "
                "error 190): {}. Refresh the long-lived Page token "
                "via the Graph API Explorer or your Facebook App "
                "settings. Tokens expire after ~60 days.".format(meta_msg)
            )
            return None

        # Permission denied (Meta code 200, 10, or 803)
        if meta_code in (10, 200, 803):
            result.add_error(
                "Instagram permission denied for {} (Meta error {}): "
                "{}. Confirm your app has instagram_basic, "
                "instagram_manage_insights, and pages_read_engagement "
                "approved.".format(path, meta_code, meta_msg)
            )
            return None

        # Rate limit (Meta codes 4, 17, 32 or HTTP 429)
        if meta_code in (4, 17, 32) or resp.status_code == 429:
            if retries > 0:
                time.sleep(30)
                return self._graph_get(
                    requests, path, params, result, retries=retries - 1
                )
            result.add_error(
                "Instagram rate limit hit on {} (Meta error {}). "
                "Reduce --limit or wait an hour.".format(path, meta_code)
            )
            return None

        result.add_error(
            "GET {} failed: HTTP {} Meta {} {}".format(
                path, resp.status_code, meta_code, meta_msg[:120]
            )
        )
        return None

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

        access_token, ig_user_id, cred_err = self._resolve_credentials(
            config
        )
        if cred_err:
            result.add_error(cred_err)
            result.finish()
            return result

        account = config["account"]
        include = set(config.get("include") or
                      ["media", "insights", "comments"])
        max_items = limit or 25

        result.metadata["account"] = account
        result.metadata["ig_user_id"] = ig_user_id
        result.metadata["include"] = sorted(include)

        # 1. Resolve the account itself — fetch profile and add as
        #    organization entity. This also validates the token and
        #    user id before we spend rate budget on media calls.
        profile = self._graph_get(
            requests,
            ig_user_id,
            {
                "fields": "id,username,name,biography,followers_count,"
                          "media_count,profile_picture_url,website",
                "access_token": access_token,
            },
            result,
        )
        if profile is None:
            # Auth or permission error already recorded
            result.finish()
            return result

        username = profile.get("username", account)
        result.metadata["username"] = username
        result.metadata["followers_count"] = profile.get(
            "followers_count"
        )
        result.metadata["media_count"] = profile.get("media_count")

        if not dry_run:
            added = self._add_entity(
                entity_type="organization",
                name="@{}".format(username),
                context="instagram",
                properties={
                    "ig_user_id": ig_user_id,
                    "followers_count": profile.get("followers_count", 0),
                    "media_count": profile.get("media_count", 0),
                    "website": profile.get("website", "") or "",
                    "biography": (profile.get("biography", "") or "")[:300],
                },
            )
            if added:
                result.entities_added += 1

        # 2. Pull media (posts)
        if "media" not in include and "insights" not in include \
                and "comments" not in include:
            result.finish()
            return result

        media_response = self._graph_get(
            requests,
            "{}/media".format(ig_user_id),
            {
                "fields": "id,caption,media_type,media_url,permalink,"
                          "timestamp,like_count,comments_count",
                "limit": min(max_items, 100),
                "access_token": access_token,
            },
            result,
        )
        if media_response is None:
            result.finish()
            return result

        media_items = media_response.get("data", []) or []
        # Apply 'since' filter if provided
        if since:
            try:
                media_items = [
                    m for m in media_items
                    if (m.get("timestamp") or "") >= since
                ]
            except Exception:
                pass

        media_items = media_items[:max_items]
        result.metadata["media_pulled"] = len(media_items)

        for media in media_items:
            media_id = media.get("id", "")
            permalink = media.get("permalink", "")
            caption = (media.get("caption") or "")[:500]

            # 2a. content_published event
            if "media" in include:
                if not dry_run:
                    self._record_event(
                        "content_published",
                        {
                            "platform": "instagram",
                            "account": "@{}".format(username),
                            "media_id": media_id,
                            "permalink": permalink,
                            "media_type": media.get("media_type", ""),
                            "caption": caption,
                            "like_count": media.get("like_count", 0),
                            "comments_count": media.get(
                                "comments_count", 0
                            ),
                            "timestamp": media.get("timestamp", ""),
                        },
                    )
                result.events_recorded += 1

            # 2b. insights → metric_recorded events
            if "insights" in include:
                self._ingest_media_insights(
                    requests, media_id, permalink, username,
                    access_token, dry_run, result,
                )

            # 2c. comments → engagement_received events
            if "comments" in include and media.get("comments_count", 0) > 0:
                self._ingest_media_comments(
                    requests, media_id, permalink, username,
                    access_token, dry_run, result,
                )

        result.finish()
        return result

    # ── per-media subroutines ─────────────────────────────────

    def _ingest_media_insights(self, requests, media_id: str,
                                permalink: str, username: str,
                                access_token: str, dry_run: bool,
                                result: ConnectorResult):
        metrics_csv = ",".join(DEFAULT_MEDIA_METRICS)
        insights = self._graph_get(
            requests,
            "{}/insights".format(media_id),
            {"metric": metrics_csv, "access_token": access_token},
            result,
        )
        if insights is None:
            return
        for entry in insights.get("data", []) or []:
            metric_name = entry.get("name", "")
            values = entry.get("values", []) or []
            value = values[0].get("value") if values else None
            if value is None:
                continue
            if not dry_run:
                self._record_event(
                    "metric_recorded",
                    {
                        "platform": "instagram",
                        "account": "@{}".format(username),
                        "media_id": media_id,
                        "permalink": permalink,
                        "metric": metric_name,
                        "value": value,
                    },
                )
            result.events_recorded += 1

    def _ingest_media_comments(self, requests, media_id: str,
                                permalink: str, username: str,
                                access_token: str, dry_run: bool,
                                result: ConnectorResult):
        comments = self._graph_get(
            requests,
            "{}/comments".format(media_id),
            {
                "fields": "id,text,username,timestamp,like_count",
                "limit": 50,
                "access_token": access_token,
            },
            result,
        )
        if comments is None:
            return
        for c in comments.get("data", []) or []:
            commenter = c.get("username", "")
            text = (c.get("text") or "")[:300]
            if not dry_run:
                self._record_event(
                    "engagement_received",
                    {
                        "platform": "instagram",
                        "account": "@{}".format(username),
                        "media_id": media_id,
                        "permalink": permalink,
                        "engagement_type": "comment",
                        "commenter": commenter,
                        "text": text,
                        "like_count": c.get("like_count", 0),
                        "timestamp": c.get("timestamp", ""),
                    },
                )
            result.events_recorded += 1

            if commenter:
                added = self._add_entity(
                    entity_type="person",
                    name="@{}".format(commenter),
                    context="instagram",
                    properties={
                        "ig_username": commenter,
                        "discovered_via": "@{}".format(username),
                    },
                )
                if added:
                    result.entities_added += 1
