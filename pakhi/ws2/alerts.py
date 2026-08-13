"""WS-2 T3: alerting — every pipeline failure surfaces loudly, never silently.

Contract (``docs/WS2_EXECUTION_BLUEPRINT.md`` §3, §5 and the paper-trading
protocol §7): ingestion failure, staleness > 1 cycle, armor rejection, or a
compute crash must raise an alert.  Alerting itself is best-effort fire-and-
forget: a broken webhook or SMTP sink **never** blocks or crashes the worker —
the alert is logged with the failure, and the pipeline continues with its
loud (non-silent) error semantics intact.

Channels (env-configured, all optional):

- ``PAKHI_ALERT_WEBHOOK_URL``  generic webhook (Slack/Discord/Teams style) POST
- ``PAKHI_ALERT_EMAIL``        SMTP recipient (SMTP host/port/user/pass env)
- console stdout                always-on fallback so alerts are never silent

All timestamps UTC; every alert carries the cycle id and a stable severity.
"""

from __future__ import annotations

import json
import logging
import os
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger("ws2.alerts")

SEVERITY_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class AlertError(Exception):
    """A notifier failed to deliver; caught and logged, never propagated."""


@dataclass
class Alert:
    """One structured alert event, serializable to JSON."""

    severity: str = "ERROR"
    summary: str = ""
    cycle_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    recorded_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "summary": self.summary,
            "cycle_id": self.cycle_id,
            "details": self.details,
            "recorded_utc": self.recorded_utc,
        }


Notifier = Callable[[Alert], None]


def _json_body(alert: Alert) -> str:
    return json.dumps(alert.as_dict(), sort_keys=True, default=str)


def console_notifier(alert: Alert) -> None:
    """Always-on stdout/stderr sink — alerts are never silent."""
    line = f"[{alert.severity}] {alert.summary}"
    if alert.cycle_id:
        line += f" (cycle {alert.cycle_id})"
    logger.error(line)
    print(line, flush=True)


def webhook_notifier(
    url: str | None = None, timeout: float = 10.0, label: str = "webhook"
) -> Notifier:
    """POST the alert JSON to a generic webhook; failures are logged, not thrown."""
    endpoint = url or os.environ.get("PAKHI_ALERT_WEBHOOK_URL")
    if not endpoint:
        return _noop(label)

    def _notify(alert: Alert) -> None:
        req = Request(
            endpoint,
            data=_json_body(alert).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(req, timeout=timeout) as resp:
                # 4xx/5xx raise HTTPError (a URLError) inside urlopen, so the
                # except below is the delivery-failure path for every status.
                if getattr(resp, "status", 200) >= 400:
                    raise AlertError(f"{label} returned HTTP {resp.status}")
        except (URLError, OSError, AlertError) as exc:
            logger.warning("alert %s delivery failed: %s", label, exc)

    _notify.label = label  # type: ignore[attr-defined]
    return _notify


def email_notifier(
    recipient: str | None = None,
    smtp_host: str | None = None,
    smtp_port: int = 587,
    smtp_user: str | None = None,
    smtp_pass: str | None = None,
) -> Notifier:
    """Send the alert via SMTP; failures are logged, not thrown."""
    to = recipient or os.environ.get("PAKHI_ALERT_EMAIL")
    host = smtp_host or os.environ.get("PAKHI_SMTP_HOST")
    if not to or not host:
        return _noop("email")

    def _notify(alert: Alert) -> None:
        msg = EmailMessage()
        msg["Subject"] = f"[pakhi ws2 {alert.severity}] {alert.summary}"
        msg["From"] = smtp_user or os.environ.get("PAKHI_SMTP_USER") or "pakhi@localhost"
        msg["To"] = to
        msg.set_content(_json_body(alert))
        try:
            with smtplib.SMTP(host, port=smtp_port, timeout=10) as srv:
                user = smtp_user or os.environ.get("PAKHI_SMTP_USER")
                pwd = smtp_pass or os.environ.get("PAKHI_SMTP_PASS")
                if user and pwd:
                    srv.starttls()
                    srv.login(user, pwd)
                srv.send_message(msg)
        except (OSError, smtplib.SMTPException, ValueError) as exc:
            logger.warning("alert email delivery failed: %s", exc)

    _notify.label = "email"  # type: ignore[attr-defined]
    return _notify


def _noop(label: str) -> Notifier:
    def _notify(alert: Alert) -> None:
        pass

    _notify.label = label  # type: ignore[attr-defined]
    return _notify


def file_notifier(path: Path | str | None = None) -> Notifier:
    """Append alerts as JSON lines to a single sink (default ``data/ws2/alerts.jsonl``)."""
    p = (
        Path(path)
        if path is not None
        else Path(__file__).resolve().parent.parent.parent / "data" / "ws2" / "alerts.jsonl"
    )

    def _notify(alert: Alert) -> None:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a") as fh:
                fh.write(_json_body(alert) + "\n")
        except OSError as exc:
            logger.warning("alert file delivery failed: %s", exc)

    _notify.label = "file"  # type: ignore[attr-defined]
    return _notify


def default_notifiers() -> list[Notifier]:
    """Console always-on, plus the env-configured channels (webhook / email)."""
    channels: list[Notifier] = [console_notifier, file_notifier()]
    if os.environ.get("PAKHI_ALERT_WEBHOOK_URL"):
        channels.append(webhook_notifier())
    if os.environ.get("PAKHI_ALERT_EMAIL") and os.environ.get("PAKHI_SMTP_HOST"):
        channels.append(email_notifier())
    return channels


def send_alert(
    summary: str,
    severity: str = "ERROR",
    cycle_id: str | None = None,
    details: dict[str, Any] | None = None,
    notifiers: list[Notifier] | None = None,
) -> Alert:
    """Dispatch an alert to every notifier; never raises (alerting is best-effort)."""
    if severity not in SEVERITY_LEVELS:
        severity = "ERROR"
    alert = Alert(
        severity=severity,
        summary=summary,
        cycle_id=cycle_id,
        details=details or {},
    )
    for notifier in notifiers or default_notifiers():
        try:
            notifier(alert)
        except Exception as exc:
            logger.error("notifier %s crashed on alert: %s", getattr(notifier, "label", "?"), exc)
    return alert


__all__ = [
    "Alert",
    "AlertError",
    "console_notifier",
    "default_notifiers",
    "email_notifier",
    "file_notifier",
    "send_alert",
    "webhook_notifier",
]
