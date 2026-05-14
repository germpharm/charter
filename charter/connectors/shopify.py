"""Shopify connector — wraps the existing shopify_api tool.

The standalone tool lives at:
  /Users/macpro2021/AI Ethical Engine/tools/shopify_api/shopify_tool.py

This connector calls the Shopify Admin API directly using the same
config file the standalone tool uses, then normalizes results into
Charter events. Customers, orders, and products each become their
own event type.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from charter.connectors import ConnectorBase, ConnectorResult


SHOPIFY_TOOL_PATH = (
    "/Users/macpro2021/AI Ethical Engine/tools/shopify_api"
)
CONFIG_FILE = Path(SHOPIFY_TOOL_PATH) / "shopify_config.json"
API_VERSION = "2024-10"


class ShopifyConnector(ConnectorBase):
    """Pull data from Shopify and record as Charter events."""

    name = "shopify"
    description = (
        "Ingest customers, orders, and products from a Shopify "
        "store. Each customer becomes a person entity in the "
        "graph. Each order becomes an 'order_received' chain entry."
    )
    version = "1.0"
    requires_auth = True
    config_schema = {
        "resource": {
            "type": "string",
            "required": True,
            "description": (
                "What to ingest: 'customers', 'orders', "
                "'products', or 'all'"
            ),
        },
        "store": {
            "type": "string",
            "required": False,
            "description": (
                "Shopify store name (defaults to value in "
                "shopify_config.json)"
            ),
        },
    }

    def validate_config(self, config: Optional[Dict[str, Any]] = None) -> List[str]:
        errors = []
        if not config:
            errors.append("config required")
            return errors
        resource = config.get("resource")
        if not resource:
            errors.append("config.resource required")
        elif resource not in ("customers", "orders", "products", "all"):
            errors.append(
                "config.resource must be one of: "
                "customers, orders, products, all"
            )
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

        # Load Shopify config from the existing tool's config file
        if not CONFIG_FILE.exists():
            result.add_error(
                "shopify config not found at {}. Run shopify_tool.py "
                "setup first.".format(CONFIG_FILE)
            )
            result.finish()
            return result

        with open(CONFIG_FILE) as f:
            shopify_config = json.load(f)

        store = config.get("store") or shopify_config.get("store")
        token = shopify_config.get("access_token")
        if not store or not token:
            result.add_error("shopify store or access_token missing")
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

        result.metadata["store"] = store

        resource = config["resource"]
        resources_to_run = (
            ["customers", "orders", "products"]
            if resource == "all" else [resource]
        )

        for res in resources_to_run:
            try:
                self._ingest_resource(
                    res, store, token, since, limit,
                    dry_run, result, requests,
                )
            except Exception as e:
                result.add_error("{}: {}".format(res, str(e)[:200]))

        result.finish()
        return result

    def _ingest_resource(self, resource: str, store: str, token: str,
                          since: Optional[str], limit: Optional[int],
                          dry_run: bool, result: ConnectorResult,
                          requests):
        """Ingest a specific Shopify resource type."""
        url = "https://{}.myshopify.com/admin/api/{}/{}.json".format(
            store, API_VERSION, resource
        )
        headers = {"X-Shopify-Access-Token": token}
        params = {"limit": min(limit or 250, 250)}
        if since and resource in ("customers", "orders"):
            params["created_at_min"] = since

        response = requests.get(url, headers=headers, params=params)
        if response.status_code != 200:
            result.add_error(
                "{} GET failed: {}".format(resource, response.status_code)
            )
            return

        data = response.json()
        items = data.get(resource, [])

        if resource == "customers":
            self._handle_customers(items, dry_run, result)
        elif resource == "orders":
            self._handle_orders(items, dry_run, result)
        elif resource == "products":
            self._handle_products(items, dry_run, result)

    def _handle_customers(self, customers: List[Dict],
                           dry_run: bool, result: ConnectorResult):
        """Process customer records."""
        for c in customers:
            email = c.get("email", "")
            first = c.get("first_name", "") or ""
            last = c.get("last_name", "") or ""
            name = "{} {}".format(first, last).strip() or email

            if dry_run:
                result.events_recorded += 1
                continue

            self._record_event(
                "customer_record_ingested",
                {
                    "shopify_id": c.get("id", ""),
                    "email": email[:100],
                    "name": name[:100],
                    "orders_count": c.get("orders_count", 0),
                    "total_spent": c.get("total_spent", "0"),
                    "created_at": c.get("created_at", ""),
                },
            )
            result.events_recorded += 1

            if name and email:
                added = self._add_entity(
                    entity_type="person",
                    name=name,
                    email=email,
                    context="shopify",
                    properties={
                        "shopify_id": str(c.get("id", "")),
                        "orders_count": c.get("orders_count", 0),
                    },
                )
                if added:
                    result.entities_added += 1

    def _handle_orders(self, orders: List[Dict],
                        dry_run: bool, result: ConnectorResult):
        """Process order records."""
        for o in orders:
            customer = o.get("customer") or {}
            customer_email = customer.get("email", "")

            if dry_run:
                result.events_recorded += 1
                continue

            self._record_event(
                "order_received",
                {
                    "shopify_id": o.get("id", ""),
                    "order_number": o.get("order_number", 0),
                    "customer_email": customer_email[:100],
                    "total_price": o.get("total_price", "0"),
                    "currency": o.get("currency", "USD"),
                    "financial_status": o.get("financial_status", ""),
                    "fulfillment_status": o.get(
                        "fulfillment_status", ""
                    ) or "unfulfilled",
                    "created_at": o.get("created_at", ""),
                },
            )
            result.events_recorded += 1

    def _handle_products(self, products: List[Dict],
                          dry_run: bool, result: ConnectorResult):
        """Process product records."""
        for p in products:
            if dry_run:
                result.events_recorded += 1
                continue

            self._record_event(
                "product_record_ingested",
                {
                    "shopify_id": p.get("id", ""),
                    "title": (p.get("title", "") or "")[:200],
                    "vendor": (p.get("vendor", "") or "")[:100],
                    "product_type": (
                        p.get("product_type", "") or ""
                    )[:100],
                    "status": p.get("status", ""),
                    "created_at": p.get("created_at", ""),
                },
            )
            result.events_recorded += 1
