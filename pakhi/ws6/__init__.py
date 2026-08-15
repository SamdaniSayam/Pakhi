"""WS-6 — Billing, Metering, Ops.

Metering is a read-only aggregation over durable sources (audit chain,
backtest jobs, feed events); it never gets its own per-request counter.
Prometheus/Stripe wiring is imported lazily so ``import pakhi.ws6`` stays
dependency- and side-effect-free (T0 contract).
"""

from __future__ import annotations

from pakhi.ws6 import contract, metering, reconcile

__all__ = ["contract", "metering", "reconcile"]
