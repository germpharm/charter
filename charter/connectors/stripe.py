"""Stripe connector — Stripe REST API for payment data.

This is the second creator-economy connector and the simplest one,
because Stripe authenticates with a single API key (no OAuth dance,
no token refresh, no Page-vs-User token confusion). It pulls
customers, charges, subscriptions, and invoices from a Stripe
account and normalizes them into Charter events.

Like instagram.py and unlike shopify.py, this connector does not
wrap an existing standalone tool. Stripe lives in this connector
file and nowhere else in the repo today.

Auth model
----------
Stripe authenticates with a single secret API key passed as HTTP
basic auth (username = key, no password). For Charter we strongly
prefer a *restricted* read-only key (rk_live_... or rk_test_...)
over a full secret key (sk_live_... / sk_test_...). The connector
will accept either, but the operator setup guide tells you to
create a restricted key with read-only scopes on customers,
charges, subscriptions, and invoices.

Credentials resolve in this order, per account name:

  1. config["api_key"] (inline, discouraged — keeps secrets out
     of shell history)
  2. Env var STRIPE_API_KEY_<ACCOUNT> (account name uppercased,
     dashes -> underscores; e.g. STRIPE_API_KEY_MYSUPEROIL)
  3. Env var STRIPE_API_KEY (single-account fallback)
  4. ~/.charter/stripe_accounts.json — a JSON map of:
       {
         "mysuperoil": {
           "api_key": "rk_live_...",
           "livemode": true
         }
       }

The accounts file is the recommended path. It should be 0600.

Pagination
----------
The Stripe API uses cursor-based pagination via the `starting_after`
query parameter. Each list response includes a `has_more` boolean
and a `data` array. The connector follows the cursor until either
`has_more` is false or it has collected `limit` records.

Per-page size is capped at 100 by the Stripe API. The connector
asks for min(remaining, 100) on each page.

Rate limits
-----------
Stripe's default rate limit is 100 read operations per second in
live mode and 25/sec in test mode. The connector does not run
fast enough to hit this in practice. On HTTP 429, it backs off
once with a 2-second sleep and retries.

Normalization
-------------
Each Stripe customer becomes a 'customer_record_ingested' chain
event AND a 'person' entity in the graph (if email is present).

Each charge becomes a 'payment_processed' chain event with a
normalized currency field (uppercase ISO 4217).

Each subscription becomes a 'subscription_active' chain event
with the plan ID, status, and current period.

Each invoice becomes an 'invoice_issued' chain event with the
amount due, status, and customer reference.

The Stripe account itself becomes an 'organization' entity in
the graph the first time the connector runs against it.

Read-only
---------
This connector is read-only. It only issues GET requests. The
operator setup guide instructs you to create a restricted key
with read-only scopes so that even if the key leaks, it cannot
move money or create resources.
"""

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from charter.connectors import ConnectorBase, ConnectorResult


STRIPE_API_BASE = "https://api.stripe.com/v1"
STRIPE_API_VERSION = "2024-06-20"
ACCOUNTS_FILE = Path.home() / ".charter" / "stripe_accounts.json"

VALID_RESOURCES = ("customers", "charges", "subscriptions", "invoices", "all")


class StripeConnector(ConnectorBase):
    """Pull customers, charges, subscriptions, and invoices from Stripe."""

    name = "stripe"
    description = (
        "Ingest customers, charges, subscriptions, and invoices "
        "from a Stripe account via the REST API. Each customer "
        "becomes a 'customer_record_ingested' chain entry and a "
        "person entity in the graph. Each charge becomes a "
        "'payment_processed' entry. Each subscription becomes a "
        "'subscription_active' entry. Each invoice becomes an "
        "'invoice_issued' entry. Read-only. Requires a Stripe "
        "restricted API key with read-only scopes."
    )
    version = "1.0"
    requires_auth = True
    config_schema = {
        "account": {
            "type": "string",
            "required": True,
            "description": (
                "Account key used to look up credentials in env "
                "vars or ~/.charter/stripe_accounts.json "
                "(e.g. 'mysuperoil')"
            ),
        },
        "resource": {
            "type": "string",
            "required": True,
            "description": (
                "What to ingest: 'customers', 'charges', "
                "'subscriptions', 'invoices', or 'all'"
            ),
        },
        "api_key": {
            "type": "string",
            "required": False,
            "description": (
                "Inline Stripe restricted API key (rk_live_... or "
                "rk_test_...). Prefer the accounts file or env "
                "vars over inlining secrets."
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
                "config.account required (e.g. 'mysuperoil')"
            )
        resource = config.get("resource")
        if not resource:
            errors.append("config.resource required")
        elif resource not in VALID_RESOURCES:
            errors.append(
                "config.resource must be one of: {}".format(
                    ", ".join(VALID_RESOURCES)
                )
            )
        return errors

    # ── credential resolution ─────────────────────────────────

    def _resolve_credentials(self, config: Dict[str, Any]) -> Tuple[
        Optional[str], Optional[str]
    ]:
        """Return (api_key, error_message)."""
        account = config["account"]

        # 1. Inline config
        api_key = config.get("api_key")
        if api_key:
            return api_key, None

        # 2. Per-account env var
        env_key = account.upper().replace("-", "_")
        api_key = os.environ.get("STRIPE_API_KEY_{}".format(env_key))
        if api_key:
            return api_key, None

        # 3. Single-account env fallback
        api_key = os.environ.get("STRIPE_API_KEY")
        if api_key:
            return api_key, None

        # 4. Accounts file
        if ACCOUNTS_FILE.exists():
            try:
                with open(ACCOUNTS_FILE) as f:
                    accounts = json.load(f)
            except json.JSONDecodeError as e:
                return None, (
                    "{} is not valid JSON: {}".format(ACCOUNTS_FILE, e)
                )
            entry = accounts.get(account)
            if isinstance(entry, dict):
                api_key = entry.get("api_key")
                if api_key:
                    return api_key, None

        return None, (
            "missing Stripe API key for account '{}'. Set it via "
            "inline config, env var STRIPE_API_KEY_{} (or "
            "STRIPE_API_KEY), or add an entry to {}. Use a "
            "restricted key (rk_live_... or rk_test_...) with "
            "read-only scopes on customers, charges, subscriptions, "
            "and invoices.".format(account, env_key, ACCOUNTS_FILE)
        )

    # ── HTTP helpers ──────────────────────────────────────────

    def _stripe_get(self, requests, path: str, params: Dict[str, Any],
                     api_key: str, result: ConnectorResult,
                     retries: int = 1) -> Optional[Dict[str, Any]]:
        """GET against the Stripe API with one rate-limit retry.

        Returns the parsed JSON dict on success, or None on
        unrecoverable error (which is recorded in result).
        """
        url = "{}/{}".format(STRIPE_API_BASE, path.lstrip("/"))
        headers = {"Stripe-Version": STRIPE_API_VERSION}
        try:
            resp = requests.get(
                url,
                params=params,
                headers=headers,
                auth=(api_key, ""),
                timeout=30,
            )
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

        # Try to extract a Stripe error message
        stripe_msg = ""
        stripe_code = ""
        try:
            err = resp.json().get("error", {})
            stripe_msg = err.get("message", "")
            stripe_code = err.get("code", "") or err.get("type", "")
        except Exception:
            pass

        # 401 — bad/missing key
        if resp.status_code == 401:
            result.add_error(
                "Stripe authentication failed (401): {}. Check "
                "that the API key is valid and not revoked.".format(
                    stripe_msg
                )
            )
            return None

        # 403 — key lacks permission for this resource
        if resp.status_code == 403:
            result.add_error(
                "Stripe permission denied (403) on {}: {}. The "
                "restricted key needs read access for this "
                "resource.".format(path, stripe_msg)
            )
            return None

        # 429 — rate limit
        if resp.status_code == 429:
            if retries > 0:
                time.sleep(2)
                return self._stripe_get(
                    requests, path, params, api_key, result,
                    retries=retries - 1,
                )
            result.add_error(
                "Stripe rate limit hit on {}. Reduce --limit or "
                "wait.".format(path)
            )
            return None

        result.add_error(
            "GET {} failed: HTTP {} Stripe {} {}".format(
                path, resp.status_code, stripe_code, stripe_msg[:120]
            )
        )
        return None

    def _paginate(self, requests, path: str, base_params: Dict[str, Any],
                   api_key: str, max_items: int,
                   result: ConnectorResult) -> List[Dict[str, Any]]:
        """Follow Stripe cursor pagination until max_items collected
        or has_more is False.
        """
        collected: List[Dict[str, Any]] = []
        starting_after: Optional[str] = None

        while len(collected) < max_items:
            page_size = min(max_items - len(collected), 100)
            params = dict(base_params)
            params["limit"] = page_size
            if starting_after:
                params["starting_after"] = starting_after

            page = self._stripe_get(
                requests, path, params, api_key, result,
            )
            if page is None:
                break

            data = page.get("data", []) or []
            if not data:
                break

            collected.extend(data)

            if not page.get("has_more"):
                break

            starting_after = data[-1].get("id")
            if not starting_after:
                break

        return collected[:max_items]

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

        api_key, cred_err = self._resolve_credentials(config)
        if cred_err:
            result.add_error(cred_err)
            result.finish()
            return result

        account = config["account"]
        resource = config["resource"]
        max_items = limit or 25

        result.metadata["account"] = account
        result.metadata["livemode"] = api_key.startswith(
            ("sk_live_", "rk_live_")
        )
        result.metadata["key_type"] = (
            "restricted" if api_key.startswith("rk_") else "secret"
        )

        # 1. Resolve the account itself — fetch /account to validate
        #    the key and add the account as an organization entity.
        account_info = self._stripe_get(
            requests, "account", {}, api_key, result,
        )
        if account_info is None:
            result.finish()
            return result

        account_name = (
            account_info.get("settings", {})
            .get("dashboard", {})
            .get("display_name")
            or account_info.get("business_profile", {}).get("name")
            or account
        )
        result.metadata["account_name"] = account_name
        result.metadata["account_id"] = account_info.get("id", "")

        if not dry_run:
            added = self._add_entity(
                entity_type="organization",
                name=account_name,
                context="stripe",
                properties={
                    "stripe_account_id": account_info.get("id", ""),
                    "country": account_info.get("country", ""),
                    "default_currency": (
                        account_info.get("default_currency", "") or ""
                    ).upper(),
                },
            )
            if added:
                result.entities_added += 1

        # Build common 'created[gte]' filter from since (epoch seconds)
        created_filter: Dict[str, Any] = {}
        if since:
            try:
                from datetime import datetime
                # Accept either ISO 8601 or epoch seconds
                if since.isdigit():
                    created_filter["created[gte]"] = int(since)
                else:
                    dt = datetime.fromisoformat(
                        since.replace("Z", "+00:00")
                    )
                    created_filter["created[gte]"] = int(dt.timestamp())
            except Exception:
                result.add_error(
                    "could not parse 'since' as ISO 8601 or epoch: "
                    "{}".format(since)
                )

        resources_to_run = (
            ["customers", "charges", "subscriptions", "invoices"]
            if resource == "all" else [resource]
        )

        for res in resources_to_run:
            try:
                self._ingest_resource(
                    res, requests, api_key, max_items, created_filter,
                    dry_run, result,
                )
            except Exception as e:
                result.add_error("{}: {}".format(res, str(e)[:200]))

        result.finish()
        return result

    # ── per-resource handlers ─────────────────────────────────

    def _ingest_resource(self, resource: str, requests, api_key: str,
                          max_items: int, created_filter: Dict[str, Any],
                          dry_run: bool, result: ConnectorResult):
        items = self._paginate(
            requests, resource, dict(created_filter), api_key,
            max_items, result,
        )
        result.metadata["{}_pulled".format(resource)] = len(items)

        if resource == "customers":
            self._handle_customers(items, dry_run, result)
        elif resource == "charges":
            self._handle_charges(items, dry_run, result)
        elif resource == "subscriptions":
            self._handle_subscriptions(items, dry_run, result)
        elif resource == "invoices":
            self._handle_invoices(items, dry_run, result)

    def _handle_customers(self, customers: List[Dict],
                           dry_run: bool, result: ConnectorResult):
        for c in customers:
            email = (c.get("email") or "")[:120]
            name = (c.get("name") or "").strip() or email or c.get("id", "")

            if not dry_run:
                self._record_event(
                    "customer_record_ingested",
                    {
                        "platform": "stripe",
                        "stripe_id": c.get("id", ""),
                        "email": email,
                        "name": name[:120],
                        "currency": (c.get("currency") or "").upper(),
                        "delinquent": c.get("delinquent", False),
                        "balance": c.get("balance", 0),
                        "created": c.get("created", 0),
                    },
                )
            result.events_recorded += 1

            if name and not dry_run:
                added = self._add_entity(
                    entity_type="person",
                    name=name,
                    email=email,
                    context="stripe",
                    properties={
                        "stripe_id": c.get("id", ""),
                        "delinquent": c.get("delinquent", False),
                    },
                )
                if added:
                    result.entities_added += 1

    def _handle_charges(self, charges: List[Dict],
                         dry_run: bool, result: ConnectorResult):
        for ch in charges:
            amount = ch.get("amount", 0)  # in smallest currency unit
            currency = (ch.get("currency") or "").upper()
            customer = ch.get("customer", "") or ""
            if isinstance(customer, dict):
                customer = customer.get("id", "")

            if not dry_run:
                self._record_event(
                    "payment_processed",
                    {
                        "platform": "stripe",
                        "stripe_id": ch.get("id", ""),
                        "amount_minor": amount,
                        "amount": amount / 100.0,
                        "currency": currency,
                        "status": ch.get("status", ""),
                        "paid": ch.get("paid", False),
                        "refunded": ch.get("refunded", False),
                        "customer_id": customer,
                        "description": (
                            ch.get("description") or ""
                        )[:200],
                        "receipt_email": (
                            ch.get("receipt_email") or ""
                        )[:120],
                        "created": ch.get("created", 0),
                    },
                )
            result.events_recorded += 1

    def _handle_subscriptions(self, subs: List[Dict],
                                dry_run: bool, result: ConnectorResult):
        for s in subs:
            customer = s.get("customer", "") or ""
            if isinstance(customer, dict):
                customer = customer.get("id", "")

            # Pull plan/price info from the first item if present
            plan_id = ""
            plan_amount = 0
            plan_currency = ""
            plan_interval = ""
            items = (s.get("items") or {}).get("data", []) or []
            if items:
                price = items[0].get("price") or {}
                plan_id = price.get("id", "") or ""
                plan_amount = price.get("unit_amount", 0) or 0
                plan_currency = (price.get("currency") or "").upper()
                recurring = price.get("recurring") or {}
                plan_interval = recurring.get("interval", "") or ""

            if not dry_run:
                self._record_event(
                    "subscription_active",
                    {
                        "platform": "stripe",
                        "stripe_id": s.get("id", ""),
                        "customer_id": customer,
                        "status": s.get("status", ""),
                        "plan_id": plan_id,
                        "plan_amount_minor": plan_amount,
                        "plan_amount": plan_amount / 100.0,
                        "plan_currency": plan_currency,
                        "plan_interval": plan_interval,
                        "current_period_start": s.get(
                            "current_period_start", 0
                        ),
                        "current_period_end": s.get(
                            "current_period_end", 0
                        ),
                        "cancel_at_period_end": s.get(
                            "cancel_at_period_end", False
                        ),
                        "created": s.get("created", 0),
                    },
                )
            result.events_recorded += 1

    def _handle_invoices(self, invoices: List[Dict],
                          dry_run: bool, result: ConnectorResult):
        for inv in invoices:
            customer = inv.get("customer", "") or ""
            if isinstance(customer, dict):
                customer = customer.get("id", "")
            currency = (inv.get("currency") or "").upper()

            if not dry_run:
                self._record_event(
                    "invoice_issued",
                    {
                        "platform": "stripe",
                        "stripe_id": inv.get("id", ""),
                        "number": inv.get("number", "") or "",
                        "customer_id": customer,
                        "customer_email": (
                            inv.get("customer_email") or ""
                        )[:120],
                        "amount_due_minor": inv.get("amount_due", 0),
                        "amount_due": inv.get("amount_due", 0) / 100.0,
                        "amount_paid_minor": inv.get("amount_paid", 0),
                        "amount_paid": inv.get("amount_paid", 0) / 100.0,
                        "currency": currency,
                        "status": inv.get("status", ""),
                        "paid": inv.get("paid", False),
                        "hosted_invoice_url": (
                            inv.get("hosted_invoice_url") or ""
                        )[:300],
                        "created": inv.get("created", 0),
                    },
                )
            result.events_recorded += 1
