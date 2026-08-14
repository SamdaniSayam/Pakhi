"""WS-3 pakhi.client SDK — thin, typed HTTP + WebSocket client for Pakhi API.

See OpenAPI documentation at `/docs` or `/redoc` on a running server.

Usage:
    >>> from pakhi.client import PakhiClient
    >>> client = PakhiClient(base_url="http://localhost:8000", api_key="my_key")
    >>> client.status()
    >>> client.signals("OJ_FUTURES")
    >>> client.backtests.create(instrument="OJ_FUTURES", window_days=30)
    >>> client.backtests.result("bt_123456")
"""

from __future__ import annotations

from typing import Any, Callable

import httpx


class BacktestClient:
    """Sub-client for backtest job endpoints."""

    def __init__(self, client: PakhiClient) -> None:
        self._client = client

    def create(
        self,
        instrument: str = "OJ_FUTURES",
        window_days: int = 30,
        model_version: str = "GFS-0p50",
        initial_capital: float = 100_000.0,
        commission_bps: float = 5.0,
        slippage_bps: float = 10.0,
    ) -> dict[str, Any]:
        """Submit a backtest job. Returns 201 Created response payload."""
        payload = {
            "instrument": instrument,
            "window_days": window_days,
            "model_version": model_version,
            "initial_capital": initial_capital,
            "commission_bps": commission_bps,
            "slippage_bps": slippage_bps,
        }
        return self._client._post("/v1/backtests", json=payload)

    def get(self, job_id: str) -> dict[str, Any]:
        """Retrieve status and parameters for a backtest job (GET /v1/backtests/{job_id})."""
        return self._client._get(f"/v1/backtests/{job_id}")

    def result(self, job_id: str) -> dict[str, Any]:
        """Retrieve stored backtest result artifact when done (GET /v1/backtests/{job_id}/result)."""
        return self._client._get(f"/v1/backtests/{job_id}/result")


class PakhiClient:
    """Typed Python SDK for the Pakhi REST + WebSocket API."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        api_key: str | None = None,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {}
        if api_key:
            headers["X-Pakhi-Key"] = api_key

        self.base_url = base_url.rstrip("/")
        self._http_client = httpx.Client(
            base_url=self.base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )
        self.backtests = BacktestClient(self)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._http_client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = self._http_client.post(path, json=json)
        resp.raise_for_status()
        return resp.json()

    def health(self) -> dict[str, Any]:
        """Check API liveness (GET /v1/health)."""
        return self._get("/v1/health")

    def status(self) -> dict[str, Any]:
        """Check API readiness & data freshness (GET /v1/status)."""
        return self._get("/v1/status")

    def instruments(self) -> dict[str, Any]:
        """List distinct instruments in store with signal count & freshness (GET /v1/instruments)."""
        return self._get("/v1/instruments")

    def signals(
        self,
        instrument: str,
        limit: int = 20,
        since: str | None = None,
        cycle_id: str | None = None,
    ) -> dict[str, Any]:
        """Retrieve signals for an instrument ordered latest-first (GET /v1/signals/{instrument})."""
        params: dict[str, Any] = {"limit": limit}
        if since is not None:
            params["since"] = since
        if cycle_id is not None:
            params["cycle_id"] = cycle_id
        return self._get(f"/v1/signals/{instrument}", params=params)

    def forecasts(self, instrument: str, lead: str = "7d") -> dict[str, Any]:
        """Retrieve stored forecast rows (GET /v1/forecasts/{instrument})."""
        return self._get(f"/v1/forecasts/{instrument}", params={"lead": lead})

    def ensemble_disagreement(self) -> dict[str, Any]:
        """Retrieve stored ensemble disagreement series (GET /v1/ensemble/disagreement)."""
        return self._get("/v1/ensemble/disagreement")

    def ledger(self) -> dict[str, Any]:
        """Retrieve paper ledger summary (GET /v1/ledger)."""
        return self._get("/v1/ledger")

    def stream_signals(
        self, on_signal: Callable[[dict[str, Any]], None], max_messages: int = 1
    ) -> None:
        """Subscribe to WebSocket signal stream (WS /v1/stream/signals)."""
        ws_url = (
            self.base_url.replace("http://", "ws://").replace("https://", "wss://")
            + "/v1/stream/signals"
        )
        try:
            import asyncio
            import json as _json

            import websockets
        except ImportError as exc:
            raise ImportError(
                "The 'websockets' library is required to stream signals using PakhiClient.stream_signals()."
            ) from exc

        async def _listen():
            async with websockets.connect(ws_url) as ws:
                count = 0
                while count < max_messages:
                    msg = await ws.recv()
                    data = _json.loads(msg)
                    if data.get("type") == "signals.batch":
                        on_signal(data)
                        count += 1

        asyncio.run(_listen())

    def close(self) -> None:
        """Close the underlying HTTP client session."""
        self._http_client.close()

    def __enter__(self) -> PakhiClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
