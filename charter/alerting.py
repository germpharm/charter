"""Alerting pipeline for Charter governance.

Dispatches alerts when kill triggers fire, thresholds are hit, or chain
integrity fails.  Uses only the Python standard library (urllib.request,
smtplib) so the module has zero additional dependencies.

Alert channels:
    - Generic webhooks (with optional HMAC-SHA256 signing)
    - Email via SMTP / STARTTLS
    - Slack incoming webhooks

Configuration is read from the ``alerting`` section of ``charter.yaml``.

Usage (CLI):
    charter alerting test        # send test alert through all channels
    charter alerting status      # show configured channels
    charter alerting configure   # print example YAML snippet
"""

import hashlib
import hmac
import json
import os
import smtplib
import time
import urllib.error
import urllib.request
from email.mime.text import MIMEText

from charter import __version__
from charter.config import load_config
from charter.identity import append_to_chain


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Event types that the system emits.  Channels can filter on these.
KNOWN_EVENTS = frozenset({
    "kill_trigger_fired",
    "chain_integrity_failure",
    "threshold_exceeded",
    "audit_overdue",
    "audit_generated",
    "ethical_gradient_acceleration",
    "audit_friction",
    "conscience_conflict",
    "compliance_deviation",
    "ai_tool_ungoverned",
    "retention_applied",
    "alert_test",
})

# Default timeout (seconds) for outbound HTTP requests.
_HTTP_TIMEOUT = 10

# SMTP default port for STARTTLS.
_SMTP_DEFAULT_PORT = 587


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso():
    """Return the current UTC time as an ISO-8601 string."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _sign_payload(payload_bytes, secret):
    """Compute HMAC-SHA256 over *payload_bytes* using *secret*.

    Returns:
        Hex digest string prefixed with ``sha256=``.
    """
    sig = hmac.new(
        secret.encode(),
        payload_bytes,
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={sig}"


def _format_event_text(event_type, event_data):
    """Produce a human-readable text block for an event."""
    lines = [
        f"Charter Governance Alert",
        f"Event:   {event_type}",
        f"Time:    {_now_iso()}",
        f"Version: {__version__}",
        "",
    ]
    if isinstance(event_data, dict):
        for key, value in event_data.items():
            lines.append(f"  {key}: {value}")
    else:
        lines.append(f"  {event_data}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# AlertDispatcher
# ---------------------------------------------------------------------------

class AlertDispatcher:
    """Dispatch governance alerts to configured channels.

    Initialise from the ``alerting`` section of a Charter config::

        alerting:
          webhooks:
            - url: "https://hooks.slack.com/services/..."
              events: ["kill_trigger_fired", "chain_integrity_failure"]
              secret: "optional-hmac-secret"
          email:
            smtp_host: "smtp.gmail.com"
            smtp_port: 587
            from_addr: "alerts@example.com"
            to_addrs: ["admin@example.com"]
            username: "alerts@example.com"
            password_env: "CHARTER_SMTP_PASSWORD"
          slack:
            webhook_url: "https://hooks.slack.com/services/..."
            channel: "#governance-alerts"
    """

    def __init__(self, config=None):
        """Initialise from an alerting config dict.

        Args:
            config: The ``alerting`` section of charter.yaml.  If *None*,
                    the dispatcher is inert (all calls succeed silently).
        """
        self._config = config or {}
        self._webhooks = self._config.get("webhooks", [])
        self._email = self._config.get("email", None)
        self._slack = self._config.get("slack", None)

    # -- public API ---------------------------------------------------------

    def dispatch(self, event_type, event_data):
        """Send an alert to every configured channel that matches *event_type*.

        Args:
            event_type: A string identifying the event (e.g.
                        ``"kill_trigger_fired"``).
            event_data: A dict (or string) with event details.

        Returns:
            A dict with keys ``sent``, ``failed``, and ``channels``.
        """
        sent = 0
        failed = 0
        channels = []

        # --- webhooks -------------------------------------------------------
        for wh in self._webhooks:
            if not self._matches_event(wh, event_type):
                continue
            ok = self._send_webhook(wh, event_type, event_data)
            if ok:
                sent += 1
                channels.append(f"webhook:{wh.get('url', '?')}")
            else:
                failed += 1

        # --- email ----------------------------------------------------------
        if self._email:
            ok = self._send_email(event_type, event_data)
            if ok:
                sent += 1
                channels.append("email")
            else:
                failed += 1

        # --- slack ----------------------------------------------------------
        if self._slack:
            ok = self._send_slack(event_type, event_data)
            if ok:
                sent += 1
                channels.append("slack")
            else:
                failed += 1

        # --- chain logging --------------------------------------------------
        try:
            append_to_chain("alert_dispatched", {
                "event_type": event_type,
                "channels": channels,
                "sent": sent,
                "failed": failed,
                "timestamp": _now_iso(),
            })
        except Exception:
            pass  # alerting must never crash the system

        return {"sent": sent, "failed": failed, "channels": channels}

    # -- private: webhook ---------------------------------------------------

    def _send_webhook(self, webhook_config, event_type, event_data):
        """POST a JSON payload to *webhook_config['url']*.

        If the webhook has a ``secret`` field, the payload is signed with
        HMAC-SHA256 and the signature is attached as the
        ``X-Charter-Signature`` header.

        Returns:
            True on success, False otherwise.
        """
        url = webhook_config.get("url")
        if not url:
            return False

        payload = {
            "event": event_type,
            "timestamp": _now_iso(),
            "data": event_data,
            "charter_version": __version__,
        }

        payload_bytes = json.dumps(
            payload, sort_keys=True, separators=(",", ":")
        ).encode()

        headers = {"Content-Type": "application/json"}

        secret = webhook_config.get("secret")
        if secret:
            signature = _sign_payload(payload_bytes, secret)
            headers["X-Charter-Signature"] = signature

        try:
            req = urllib.request.Request(
                url,
                data=payload_bytes,
                headers=headers,
                method="POST",
            )
            urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT)
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            return False
        except Exception:
            return False

    # -- private: email -----------------------------------------------------

    def _send_email(self, event_type, event_data):
        """Send an alert email via SMTP with STARTTLS.

        The SMTP password is read from the environment variable named in
        ``password_env`` (never stored in config directly).

        Returns:
            True on success, False otherwise.
        """
        if not self._email:
            return False

        smtp_host = self._email.get("smtp_host")
        smtp_port = self._email.get("smtp_port", _SMTP_DEFAULT_PORT)
        from_addr = self._email.get("from_addr")
        to_addrs = self._email.get("to_addrs", [])
        username = self._email.get("username", from_addr)
        password_env = self._email.get("password_env", "CHARTER_SMTP_PASSWORD")

        if not (smtp_host and from_addr and to_addrs):
            return False

        password = os.environ.get(password_env)
        if not password:
            return False

        subject = f"[Charter Alert] {event_type}"
        body = _format_event_text(event_type, event_data)

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = ", ".join(to_addrs)

        try:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=_HTTP_TIMEOUT)
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(username, password)
            server.sendmail(from_addr, to_addrs, msg.as_string())
            server.quit()
            return True
        except (smtplib.SMTPException, OSError):
            return False
        except Exception:
            return False

    # -- private: slack -----------------------------------------------------

    def _send_slack(self, event_type, event_data):
        """POST a message to a Slack incoming webhook.

        The message is formatted using Slack Block Kit with a single
        section block containing the event details.

        Returns:
            True on success, False otherwise.
        """
        if not self._slack:
            return False

        webhook_url = self._slack.get("webhook_url")
        if not webhook_url:
            return False

        channel = self._slack.get("channel")
        text = _format_event_text(event_type, event_data)

        payload = {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"*Charter Governance Alert*\n"
                            f"*Event:* `{event_type}`\n"
                            f"*Time:* {_now_iso()}\n"
                            f"*Version:* {__version__}\n"
                            f"```{json.dumps(event_data, indent=2)}```"
                        ),
                    },
                }
            ],
            "text": text,  # fallback for notifications
        }

        if channel:
            payload["channel"] = channel

        payload_bytes = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}

        try:
            req = urllib.request.Request(
                webhook_url,
                data=payload_bytes,
                headers=headers,
                method="POST",
            )
            urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT)
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, OSError):
            return False
        except Exception:
            return False

    # -- private: event matching --------------------------------------------

    @staticmethod
    def _matches_event(webhook_config, event_type):
        """Check whether a webhook config is interested in *event_type*.

        If the webhook has no ``events`` list, or the list is empty, it
        matches *every* event.

        Returns:
            True if the webhook should receive the event.
        """
        events = webhook_config.get("events")
        if not events:
            return True
        return event_type in events


# ---------------------------------------------------------------------------
# Module-level functions
# ---------------------------------------------------------------------------

def load_alerting_config(config=None):
    """Load the ``alerting`` section from charter.yaml.

    Args:
        config: A pre-loaded charter config dict.  If *None*, calls
                ``charter.config.load_config()`` to find and parse it.

    Returns:
        The alerting config dict, or an empty dict if none is configured.
    """
    if config is None:
        config = load_config()
    if not config:
        return {}
    return config.get("alerting", {})


def test_alert(config=None):
    """Send a test alert through all configured channels.

    Returns:
        A results dict from ``AlertDispatcher.dispatch``.
    """
    alerting_cfg = load_alerting_config(config)
    dispatcher = AlertDispatcher(alerting_cfg)
    results = dispatcher.dispatch("alert_test", {
        "message": "This is a test alert from Charter governance.",
        "timestamp": _now_iso(),
        "charter_version": __version__,
    })

    try:
        append_to_chain("alert_test_sent", {
            "results": results,
            "timestamp": _now_iso(),
        })
    except Exception:
        pass  # chain logging is non-critical

    return results


def configure_webhook(url, events=None, secret=None):
    """Build a webhook config dict suitable for ``charter.yaml``.

    Args:
        url:    The webhook endpoint URL.
        events: Optional list of event types to subscribe to.  If *None*
                or empty, the webhook receives all events.
        secret: Optional HMAC-SHA256 shared secret for payload signing.

    Returns:
        A dict ready to be inserted into the ``alerting.webhooks`` list.
    """
    cfg = {"url": url}
    if events:
        cfg["events"] = list(events)
    if secret:
        cfg["secret"] = secret
    return cfg


def _print_status(config=None):
    """Print a summary of configured alerting channels."""
    alerting_cfg = load_alerting_config(config)
    if not alerting_cfg:
        print("No alerting configuration found in charter.yaml.")
        print("Run 'charter alerting configure' to see an example.")
        return

    webhooks = alerting_cfg.get("webhooks", [])
    email = alerting_cfg.get("email")
    slack = alerting_cfg.get("slack")

    print("Charter Alerting — Configured Channels")
    print("=" * 42)

    if webhooks:
        print(f"\nWebhooks ({len(webhooks)}):")
        for i, wh in enumerate(webhooks):
            url = wh.get("url", "(no url)")
            events = wh.get("events", [])
            signed = "yes" if wh.get("secret") else "no"
            event_str = ", ".join(events) if events else "all events"
            print(f"  [{i}] {url}")
            print(f"      Events: {event_str}")
            print(f"      Signed: {signed}")
    else:
        print("\nWebhooks: none configured")

    if email:
        host = email.get("smtp_host", "?")
        port = email.get("smtp_port", _SMTP_DEFAULT_PORT)
        from_addr = email.get("from_addr", "?")
        to_addrs = email.get("to_addrs", [])
        pw_env = email.get("password_env", "CHARTER_SMTP_PASSWORD")
        pw_set = "yes" if os.environ.get(pw_env) else "no"
        print(f"\nEmail:")
        print(f"  Host:     {host}:{port}")
        print(f"  From:     {from_addr}")
        print(f"  To:       {', '.join(to_addrs)}")
        print(f"  Password: env ${pw_env} {'(set)' if pw_set == 'yes' else '(NOT SET)'}")
    else:
        print("\nEmail: not configured")

    if slack:
        url = slack.get("webhook_url", "(no url)")
        channel = slack.get("channel", "(default)")
        print(f"\nSlack:")
        print(f"  Webhook: {url}")
        print(f"  Channel: {channel}")
    else:
        print("\nSlack: not configured")


def _print_configure():
    """Print an example alerting configuration for charter.yaml."""
    example = """\
# Add this section to your charter.yaml to enable alerting.

alerting:
  webhooks:
    - url: "https://hooks.example.com/charter"
      events:
        - kill_trigger_fired
        - chain_integrity_failure
        - threshold_exceeded
      secret: "your-hmac-shared-secret"

    - url: "https://hooks.example.com/all-events"
      # omit 'events' to receive every alert

  email:
    smtp_host: "smtp.gmail.com"
    smtp_port: 587
    from_addr: "alerts@example.com"
    to_addrs:
      - "admin@example.com"
      - "security@example.com"
    username: "alerts@example.com"
    password_env: "CHARTER_SMTP_PASSWORD"   # reads password from this env var

  slack:
    webhook_url: "https://hooks.slack.com/services/T00/B00/xxxx"
    channel: "#governance-alerts"
"""
    print(example)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def run_alerting(args):
    """CLI entry point for ``charter alerting <action>``.

    Supported actions:
        test       -- send a test alert through all channels
        status     -- show configured alerting channels
        configure  -- print example YAML configuration
    """
    action = getattr(args, "action", None)

    if action == "test":
        print("Sending test alert to all configured channels...")
        results = test_alert()
        print(f"\nResults:")
        print(f"  Sent:     {results['sent']}")
        print(f"  Failed:   {results['failed']}")
        print(f"  Channels: {', '.join(results['channels']) or 'none'}")
        if results["sent"] == 0 and results["failed"] == 0:
            print("\nNo channels configured. Run 'charter alerting configure' for setup instructions.")

    elif action == "status":
        _print_status()

    elif action == "configure":
        _print_configure()

    else:
        print("Usage: charter alerting <test|status|configure>")
        print("")
        print("  test       Send a test alert through all configured channels")
        print("  status     Show configured alerting channels and their filters")
        print("  configure  Print example alerting configuration for charter.yaml")
