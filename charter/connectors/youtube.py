"""YouTube connector — pulls channel/video/comment data into Charter.

Uses Google OAuth and reuses the same `credentials.json` file as the
existing gmail_ingestor and google_calendar tools. Tokens are written
to the google_calendar folder using the pattern
`token_<Account>_youtube.json`, mirroring the calendar token layout.

Each YouTube video becomes a 'content_published' chain entry. Each
comment becomes an 'interaction' chain entry. The channel itself is
added to the graph as an organization entity.

The connector is read-only. It uses the youtube.readonly scope which
covers channel info, video listing, video statistics, and comment
threads. It does NOT request any write or analytics-write scopes.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from charter.connectors import ConnectorBase, ConnectorResult


GMAIL_INGESTOR_PATH = (
    "/Users/macpro2021/AI Ethical Engine/tools/gmail_ingestor"
)
GOOGLE_CALENDAR_PATH = (
    "/Users/macpro2021/AI Ethical Engine/tools/google_calendar"
)
CREDENTIALS_FILE = Path(GMAIL_INGESTOR_PATH) / "credentials.json"
TOKEN_DIR = Path(GOOGLE_CALENDAR_PATH)

# Read-only YouTube Data API scope. Covers channels, videos, comments.
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def _resolve_account(account: str) -> str:
    """Resolve account alias to canonical name via gmail_accounts."""
    if GMAIL_INGESTOR_PATH not in sys.path:
        sys.path.insert(0, GMAIL_INGESTOR_PATH)
    try:
        from gmail_accounts import resolve_account
        return resolve_account(account)
    except Exception:
        return account


def _authenticate(account: str):
    """Authenticate with the YouTube Data API for the given account.

    Reuses credentials.json from gmail_ingestor and stores the token
    in google_calendar/token_<Account>_youtube.json. If no token
    exists, runs the local-server OAuth flow once to mint one.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    canonical = _resolve_account(account)
    token_path = TOKEN_DIR / "token_{}_youtube.json".format(canonical)

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(
            str(token_path), YOUTUBE_SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_FILE.exists():
                raise RuntimeError(
                    "credentials.json not found at {}".format(CREDENTIALS_FILE)
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), YOUTUBE_SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return creds


class YouTubeConnector(ConnectorBase):
    """Pull YouTube channel, video, and comment data into Charter."""

    name = "youtube"
    description = (
        "Ingest data from a YouTube channel via the YouTube Data API "
        "v3. The authenticated user's channel is added as an "
        "organization entity. Each video becomes a 'content_published' "
        "chain entry with title, publish date, view/like/comment "
        "counts. Each top-level comment becomes an 'interaction' "
        "chain entry. Read-only — uses the youtube.readonly scope and "
        "reuses the existing Google credentials.json from gmail_ingestor."
    )
    version = "1.0"
    requires_auth = True
    config_schema = {
        "account": {
            "type": "string",
            "required": True,
            "description": (
                "Google account name (e.g. 'MMLD', 'GermPharm', "
                "'OsteoDensity', 'Personal'). Resolved via gmail_accounts."
            ),
        },
        "channel_id": {
            "type": "string",
            "required": False,
            "description": (
                "YouTube channel ID. Defaults to the authenticated "
                "user's own channel (mine=true)."
            ),
        },
        "include_comments": {
            "type": "boolean",
            "required": False,
            "description": (
                "Whether to fetch comment threads for each video. "
                "Defaults to true."
            ),
        },
    }

    def validate_config(self, config: Optional[Dict[str, Any]] = None) -> List[str]:
        errors = []
        if not config:
            errors.append("config required")
            return errors
        if not config.get("account"):
            errors.append("config.account required")
        return errors

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

        account = config["account"]
        channel_id = config.get("channel_id")
        include_comments = config.get("include_comments", True)
        video_limit = limit or 25

        try:
            creds = _authenticate(account)
        except Exception as e:
            result.add_error(
                "youtube auth failed for {}: {}".format(account, e)
            )
            result.finish()
            return result

        try:
            from googleapiclient.discovery import build
            service = build("youtube", "v3", credentials=creds)
        except Exception as e:
            result.add_error(
                "could not build youtube service: {}".format(e)
            )
            result.finish()
            return result

        # ── 1. Fetch channel info ────────────────────────────────
        try:
            channel_args = {
                "part": "snippet,statistics,contentDetails",
            }
            if channel_id:
                channel_args["id"] = channel_id
            else:
                channel_args["mine"] = True
            channel_resp = service.channels().list(**channel_args).execute()
            channels = channel_resp.get("items", [])
        except Exception as e:
            result.add_error(
                "channels.list failed: {}".format(e)
            )
            result.finish()
            return result

        if not channels:
            result.add_error(
                "no channel found for account {} (channel_id={})".format(
                    account, channel_id or "mine"
                )
            )
            result.finish()
            return result

        channel = channels[0]
        ch_snippet = channel.get("snippet", {})
        ch_stats = channel.get("statistics", {})
        ch_id = channel.get("id", "")
        ch_title = ch_snippet.get("title", "(unknown channel)")
        uploads_playlist = (
            channel.get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads", "")
        )

        result.metadata["account"] = account
        result.metadata["channel_id"] = ch_id
        result.metadata["channel_title"] = ch_title
        result.metadata["subscriber_count"] = ch_stats.get(
            "subscriberCount", "0"
        )
        result.metadata["video_count"] = ch_stats.get("videoCount", "0")

        # Add channel as organization entity
        if not dry_run:
            added = self._add_entity(
                entity_type="organization",
                name=ch_title,
                context="youtube",
                properties={
                    "platform": "youtube",
                    "channel_id": ch_id,
                    "subscriber_count": ch_stats.get("subscriberCount", "0"),
                    "video_count": ch_stats.get("videoCount", "0"),
                    "view_count": ch_stats.get("viewCount", "0"),
                    "description": ch_snippet.get("description", "")[:500],
                },
            )
            if added:
                result.entities_added += 1

        # ── 2. Fetch videos via uploads playlist ─────────────────
        if not uploads_playlist:
            result.add_error(
                "channel has no uploads playlist; cannot list videos"
            )
            result.finish()
            return result

        try:
            playlist_resp = service.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=uploads_playlist,
                maxResults=min(video_limit, 50),
            ).execute()
            playlist_items = playlist_resp.get("items", [])
        except Exception as e:
            result.add_error(
                "playlistItems.list failed: {}".format(e)
            )
            result.finish()
            return result

        video_ids = [
            item.get("contentDetails", {}).get("videoId")
            for item in playlist_items
            if item.get("contentDetails", {}).get("videoId")
        ]
        result.metadata["videos_found"] = len(video_ids)

        if not video_ids:
            result.finish()
            return result

        # ── 3. Fetch video statistics in batch ───────────────────
        try:
            videos_resp = service.videos().list(
                part="snippet,statistics",
                id=",".join(video_ids),
                maxResults=50,
            ).execute()
            videos = videos_resp.get("items", [])
        except Exception as e:
            result.add_error(
                "videos.list failed: {}".format(e)
            )
            result.finish()
            return result

        for video in videos:
            try:
                v_snippet = video.get("snippet", {})
                v_stats = video.get("statistics", {})
                v_id = video.get("id", "")
                published = v_snippet.get("publishedAt", "")

                # Apply since filter at the video level
                if since and published and published < since:
                    continue

                if dry_run:
                    result.events_recorded += 1
                    continue

                self._record_event(
                    "content_published",
                    {
                        "platform": "youtube",
                        "account": account,
                        "channel_id": ch_id,
                        "channel_title": ch_title,
                        "video_id": v_id,
                        "title": v_snippet.get("title", "")[:300],
                        "description": v_snippet.get("description", "")[:500],
                        "published_at": published,
                        "view_count": v_stats.get("viewCount", "0"),
                        "like_count": v_stats.get("likeCount", "0"),
                        "comment_count": v_stats.get("commentCount", "0"),
                        "tags": v_snippet.get("tags", [])[:20],
                        "url": "https://www.youtube.com/watch?v={}".format(v_id),
                    },
                )
                result.events_recorded += 1

                # ── 4. Fetch top-level comments for this video ───
                if not include_comments:
                    continue
                try:
                    comments_resp = service.commentThreads().list(
                        part="snippet",
                        videoId=v_id,
                        maxResults=20,
                        textFormat="plainText",
                    ).execute()
                    threads = comments_resp.get("items", [])
                except Exception as ce:
                    # Comments may be disabled — record but keep going
                    msg = str(ce)[:100]
                    if "disabled" not in msg.lower():
                        result.add_error(
                            "commentThreads {}: {}".format(v_id[:11], msg)
                        )
                    continue

                for thread in threads:
                    try:
                        top = (
                            thread.get("snippet", {})
                            .get("topLevelComment", {})
                            .get("snippet", {})
                        )
                        author = top.get("authorDisplayName", "")
                        text = top.get("textDisplay", "")
                        published_c = top.get("publishedAt", "")
                        self._record_event(
                            "interaction",
                            {
                                "platform": "youtube",
                                "interaction_type": "comment",
                                "video_id": v_id,
                                "channel_id": ch_id,
                                "author": author[:100],
                                "text": text[:500],
                                "like_count": top.get("likeCount", 0),
                                "published_at": published_c,
                            },
                        )
                        result.events_recorded += 1

                        if author:
                            added = self._add_entity(
                                entity_type="person",
                                name=author,
                                context="youtube",
                                properties={"platform": "youtube"},
                            )
                            if added:
                                result.entities_added += 1
                    except Exception as te:
                        result.add_error(
                            "comment thread: {}".format(str(te)[:100])
                        )
            except Exception as e:
                result.add_error(
                    "video {}: {}".format(
                        video.get("id", "?")[:16], str(e)[:100]
                    )
                )

        result.finish()
        return result
