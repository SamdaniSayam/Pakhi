"""WS-6 metering metrics — registered into the shared WS-5 registry.

``prometheus_client`` is imported lazily so ``import pakhi.ws6`` stays
dependency- and side-effect-free. Metrics register into the WS-5 collector
registry (``/metrics`` renders it); if the registry is not initialized the
setters no-op — mirroring the WS-5 pattern — so metering stays pure in
hermetic tests and the cron path.

No PII rule: labels carry tenant/tier/state only — never keys or tokens.
"""

from __future__ import annotations

from typing import Any

_metrics: dict[str, Any] = {}
_registered = False


def _ensure() -> None:
    global _registered
    if _registered:
        return
    from pakhi.ws5 import metrics as ws5_metrics

    try:
        registry = ws5_metrics.get_registry()
    except RuntimeError:
        return  # app never initialized metrics — no-op, matching WS-5 style
    import prometheus_client as pc

    m: dict[str, Any] = {}
    m["pakhi_metered_api_calls_total"] = pc.Counter(
        "pakhi_metered_api_calls_total",
        "Metered billable API calls (2xx/3xx) by tenant.",
        ["tenant"],
        registry=registry,
    )
    m["pakhi_metered_feed_hours_total"] = pc.Gauge(
        "pakhi_metered_feed_hours_total",
        "Metered feed hours by tenant.",
        ["tenant"],
        registry=registry,
    )
    m["pakhi_metered_backtest_hours_total"] = pc.Gauge(
        "pakhi_metered_backtest_hours_total",
        "Metered backtest compute hours by tenant.",
        ["tenant"],
        registry=registry,
    )
    m["pakhi_metering_reconcile_state"] = pc.Gauge(
        "pakhi_metering_reconcile_state",
        "0=normal, 1=drift, 2=extreme for the last reconciliation.",
        ["tenant"],
        registry=registry,
    )
    m["pakhi_metering_drift_events_total"] = pc.Counter(
        "pakhi_metering_drift_events_total",
        "Metering reconciliation drift events (S1).",
        ["tenant"],
        registry=registry,
    )
    m["pakhi_stripe_last_sync_timestamp"] = pc.Gauge(
        "pakhi_stripe_last_sync_timestamp",
        "Unix seconds of the last successful Stripe usage sync (T2).",
        registry=registry,
    )
    _metrics.update(m)
    _registered = True


def record_usage(tenant_id: str, api_calls: int, feed_hours: float, backtest_hours: float) -> None:
    _ensure()
    api = _metrics.get("pakhi_metered_api_calls_total")
    if api and api_calls:
        api.labels(tenant=tenant_id).inc(api_calls)
    feed = _metrics.get("pakhi_metered_feed_hours_total")
    if feed and feed_hours:
        feed.labels(tenant=tenant_id).set(feed_hours)
    backs = _metrics.get("pakhi_metered_backtest_hours_total")
    if backs and backtest_hours:
        backs.labels(tenant=tenant_id).set(backtest_hours)


def record_reconcile_state(tenant_id: str, state: str, *, drift: bool = False) -> None:
    _ensure()
    gauge = _metrics.get("pakhi_metering_reconcile_state")
    if gauge:
        value = {"normal": 0, "drift": 1, "extreme": 2}.get(state, 0)
        gauge.labels(tenant=tenant_id).set(value)
    if drift:
        counter = _metrics.get("pakhi_metering_drift_events_total")
        if counter:
            counter.labels(tenant=tenant_id).inc()


def record_stripe_sync_timestamp(unix_seconds: float) -> None:
    _ensure()
    gauge = _metrics.get("pakhi_stripe_last_sync_timestamp")
    if gauge:
        gauge.set(unix_seconds)
