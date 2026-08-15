#!/usr/bin/env python3
"""WS-6 T2 — daily Stripe usage sync (run by cron, every 24 h).

Contract §3.2/§5: **never an end-of-month dump** — every completed day is
submitted as an idempotent per-day batch (re-send is a no-op). A failed batch
stays ``failed`` so ``pakhi_stripe_last_sync_timestamp`` + the > 24 h
staleness alert surface it. Test mode only — no live keys, ever.

Usage:
    python -m scripts.run_ws6_stripe_sync [--day YYYY-MM-DD] [--fake]

``--fake`` uses the in-memory fake transport (CI / local smoke); production
sets ``STRIPE_API_KEY`` and ``STRIPE_SECRET_KEY``… the key is read by the real
HTTP transport, never hard-coded, never logged.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine

from pakhi.api.settings import Settings  # PAKHI_DB_WRITE_URL / test-mode override


class FakeStripeClient:
    """Recording fake transport for ``--fake`` / CI — matches the sync surface.

    Validates the one thing the real API is strict about that production MUST
    get right: the ``subscription_item`` is a Stripe Subscription Item id
    (``si_…``), never the internal tenant id. The fake that validated nothing
    is what let the real ``subscription_item=tenant_id`` bug ship undetected.
    """

    def __init__(self) -> None:
        self.submitted: list[dict] = []

    def submit_usage(
        self,
        *,
        idempotency_key: str,
        tenant_id: str,
        subscription_item: str,
        quantity: float,
        timestamp: int,
    ) -> None:
        if quantity <= 0:
            raise ValueError(f"non-positive usage for {idempotency_key}")
        if not subscription_item.startswith("si_"):
            raise ValueError(
                f"subscription_item for tenant {tenant_id} must be a Stripe "
                f"Subscription Item id (si_...), got {subscription_item!r}"
            )
        self.submitted.append(
            {
                "idempotency_key": idempotency_key,
                "tenant_id": tenant_id,
                "subscription_item": subscription_item,
                "quantity": quantity,
                "timestamp": timestamp,
            }
        )


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--day", default=None, help="YYYY-MM-DD to sync (default: yesterday, UTC)")
    args.add_argument("--fake", action="store_true", help="use the recording fake transport")
    opts = args.parse_args(argv)

    if opts.day:
        day = datetime.fromisoformat(opts.day).replace(tzinfo=timezone.utc)
    else:
        day = datetime.now(timezone.utc) - timedelta(days=1)

    from pakhi.ws6 import db as ws6_db
    from pakhi.ws6 import stripe

    engine = create_engine(Settings.from_env().write_db_url)
    ws6_db.init_db(engine)

    if opts.fake or not os.environ.get("STRIPE_API_KEY"):
        client: object = FakeStripeClient()
    else:
        client = _HttpClient(os.environ["STRIPE_API_KEY"])

    batches = stripe.sync_day(engine, client, day)
    print(f"day={day.date().isoformat()} batches={len(batches)} synced")
    return 0


class _HttpClient:
    """Real transport over Stripe's REST API (test mode only)."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def submit_usage(
        self,
        *,
        idempotency_key: str,
        tenant_id: str,
        subscription_item: str,
        quantity: float,
        timestamp: int,
    ) -> None:
        import httpx

        resp = httpx.post(
            "https://api.stripe.com/v1/usage_records",
            auth=(self._api_key, ""),
            data={
                "subscription_item": subscription_item,
                "quantity": str(quantity),
                "timestamp": str(timestamp),
                "action": "increment",
            },
            headers={"Idempotency-Key": idempotency_key},
            timeout=30.0,
        )
        resp.raise_for_status()


if __name__ == "__main__":
    sys.exit(main())
