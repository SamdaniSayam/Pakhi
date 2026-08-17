"""WS-6 Stripe billing webhook receiver (HTTP).

Stripe POSTs signed webhook events here. This route is auth-exempt — Stripe
cannot carry our ``X-Pakhi-Key`` — so authenticity is proven by the Stripe
signature, verified inside ``apply_webhook``. The path is bypassed by the WS-3
auth/rate-limit middleware (see ``pakhi/api/auth.py``).
"""

from __future__ import annotations

import logging
import os

import anyio
from fastapi import APIRouter, Request, Response

from pakhi.ws6.stripe import WebhookError, apply_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/billing", tags=["billing"])


@router.post("/webhook")
async def stripe_webhook(request: Request) -> Response:
    """Receive and apply one Stripe webhook event.

    Returns 200 only after the event is durably applied (or deduped), so Stripe
    stops retrying. Signature failures return 400; missing secret or an
    unavailable store return 503 (Stripe retries).
    """
    raw_body = await request.body()
    signature_header = request.headers.get("stripe-signature", "")
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not secret:
        logger.error("STRIPE_WEBHOOK_SECRET not set; refusing Stripe webhook")
        return Response(
            content='{"error":{"code":"misconfigured","message":"webhook secret unset"}}',
            status_code=503,
            media_type="application/json",
        )
    engine = getattr(request.app.state, "write_engine", None)
    if engine is None:
        return Response(
            content='{"error":{"code":"unavailable","message":"store unavailable"}}',
            status_code=503,
            media_type="application/json",
        )
    try:
        result = await anyio.to_thread.run_sync(
            apply_webhook, engine, raw_body, signature_header, secret
        )
    except WebhookError as exc:
        logger.warning("Rejected Stripe webhook: %s", exc)
        safe = str(exc).replace('"', "'")
        return Response(
            content=f'{{"error":{{"code":"webhook_error","message":"{safe}"}}}}',
            status_code=400,
            media_type="application/json",
        )
    logger.info("Applied Stripe webhook: %s", result)
    return Response(
        content='{"status":"ok"}', status_code=200, media_type="application/json"
    )
