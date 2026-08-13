"""WS-3 T0: API contract — pre-registered, hash-pinned.

Mirror of the WS-1 evaluation-contract / WS-2 protocol discipline: **before any
endpoint ships**, the API's behavior is locked in writing
(``docs/WS3_API_CONTRACT.md``) and as a self-hash-pinned machine artifact
(``data/ws3/api_contract.json``).

The contract freezes:

- the locked route table and the JSON error envelope
  (``{error: {code, message, details?}}``);
- the rate-limit headers and key policy (``X-Pakhi-Key``, sha256 at rest);
- the freshness semantics (``X-Pakhi-Staleness``, honest stale, 404-vs-empty);
- the ``X-Pakhi-Edge-Status`` computation from the paper ledger
  (``underpowered_n<N>`` / ``unproven_n<N>`` / ``proven_n<N>``);
- the WebSocket message schema and the ``cycle_complete`` NOTIFY channel;
- the backtest input bounds (window, model whitelist, per-key cap).

Two endpoints are locked as **501 ``not_implemented``** because the store does
not yet contain the data they would serve (``/v1/forecasts`` — WS-2 has no
forecast-rows table; ``/v1/ensemble/disagreement`` — deferred from WS-2).  The
API never fabricates what the store does not have.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

__all__ = [
    "API_CONTRACT_DOC",
    "API_CONTRACT_JSON",
    "BACKTEST_BOUNDS",
    "LIVE_INSTRUMENT",
    "MODEL_VERSION_WHITELIST",
    "N_MIN",
    "build_api_contract",
    "contract_consistent",
    "payload_sha256",
]

BACKTEST_BOUNDS = {
    "max_window_days": 365,
    "allowed_models": ["GFS-0p50"],
}

# N_min for the live paper-trading harness (WS-1 significance contract). Imported
# lazily from pakhi.ws1.significance at build time so the contract module stays
# importable without pulling numpy/pandas at module level; the value is verified
# against the WS-1 source of truth in tests.
N_MIN = 8

LOCKED_UTC = "2026-08-13T17:45:00+00:00"  # fixed lock time (stable payload hash)
API_CONTRACT_DOC = "docs/WS3_API_CONTRACT.md"
API_CONTRACT_JSON = "data/ws3/api_contract.json"

LIVE_INSTRUMENT = "OJ_FUTURES"
MODEL_VERSION_WHITELIST = ["GFS-0p50"]  # the only model_version written by WS-2

_HERE = Path(__file__).resolve().parent.parent.parent
G1_DECISION_JSON = _HERE / "data" / "ws1" / "g1_decision.json"


def payload_sha256(payload: dict) -> str:
    """Self-verifying hash over the canonical JSON payload (excluding itself).

    Determinism contract: the payload must be JSON-native (no datetime/Timestamp
    values — ``default=str`` output is NOT ISO8601 and would make the hash a
    silent correctness trap). Floats use shortest-round-trip repr, which is
    stable across runs and platforms.
    """
    body = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(body).hexdigest()


def _n_min() -> int:
    """Cross-check the hardcoded N_MIN against the WS-1 significance source of
    truth; the contract must never silently drift from the evaluation rule."""
    from pakhi.ws1.significance import N_MIN as _N

    return int(_N)


def _predecessor() -> dict:
    """G1 facts from the self-hash-pinned decision record.

    The decision record is a committed artifact, so its absence is a broken
    build — there is deliberately no silent fallback (a fallback with stale
    numbers would make regeneration produce a different hash and pin).
    """
    rec = json.loads(G1_DECISION_JSON.read_text())
    return {
        "g1_report": "docs/WS1_G1_REPORT.md",
        "g1_outcome": rec["outcome"],
        "g1_n_events": rec["headline_metric"]["n_events"],
        "g1_net_of_benchmark_event_sharpe": rec["headline_metric"]["net_of_benchmark_event_sharpe"],
        "g1_decision_json": str(G1_DECISION_JSON.relative_to(_HERE)),
    }


def build_api_contract(locked_utc: str | None = None) -> dict:
    """Build the locked WS-3 API contract payload (self-hash-pinned)."""
    payload = {
        "version": "1.1",
        "status": "LOCKED",
        "locked_utc": locked_utc or LOCKED_UTC,
        "gate": "G1 re-run verdict or explicit infra-first decision (recorded in WS3_PROGRESS.md)",
        "source_doc": API_CONTRACT_DOC,
        "predecessor": _predecessor(),
        "endpoint_policy": {
            "data_handlers": "sync def (anyio threadpool) — blocking DB work never on the event loop",
            "only_async": ["WS /v1/stream/signals"],
            "note": "pure-async (psycopg v3 / asyncpg) is a documented alternative, not Phase-2",
        },
        "cors": {
            "middleware": "CORSMiddleware",
            "allowlist_env": "PAKHI_CORS_ORIGINS",
            "allow_methods": ["GET", "POST", "OPTIONS"],
            "allow_headers": ["X-Pakhi-Key", "X-Pakhi-Version", "Content-Type", "X-Request-ID"],
            "preflight": "OPTIONS returns 204/200 with allow headers; no credentials at Phase-2",
        },
        "engines": {
            "read_engine": {"role": "postgres_readonly", "used_for": ["all GET /v1/*"]},
            "write_engine": {
                "role": "postgres",
                "used_for": ["backtest_jobs INSERT", "API key / rate-limit bookkeeping"],
            },
            "provisioning": "readonly role + app role provisioned as a T1 dependency (before the CI permission test)",
            "enforcement": "T1 exit — CI permission test: read-only role rejects a write (42501); no GET path uses write_engine",
        },
        "versioning": {
            "prefix": "/v1",
            "header": "X-Pakhi-Version",
            "policy": "breaking schema changes bump the major version",
        },
        "auth": {
            "request_header": "X-Pakhi-Key",
            "at_rest": "sha256 hash only; plaintext keys never stored or logged",
            "source": "PAKHI_API_KEYS env (comma-separated) or data/ws3/api_keys.json (gitignored)",
            "unknown_key": "401",
        },
        "error_envelope": {
            "shape": {"error": {"code": "string", "message": "string", "details": "optional"}},
            "mapped_handlers": [
                "RequestValidationError (422)",
                "HTTPException (all statuses)",
                "unhandled Exception (500)",
            ],
            "rule": "no route ever leaks the framework default shape (422, HTTPException, and 500 all map to the envelope)",
        },
        "rate_limits": {
            "bucket": "token-bucket, in-memory, thread-safe",
            "headers": ["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
            "deployment": "single-worker only (uvicorn --workers 1); multi-worker is a WS-5/Redis goal",
            "exceeded": "429 with the locked error envelope",
        },
        "freshness": {
            "endpoint": "GET /v1/status",
            "fields": ["db_ok", "latest_cycle_id", "publication_ts", "staleness_seconds"],
            "header": "X-Pakhi-Staleness",
            "rule": "no cycle today is a visible stale state with last-known data — never a fabricated fresh value",
            "empty_is_404": "GET /v1/signals/{instrument} with no rows returns 404, never an empty 200 body",
        },
        "edge_status": {
            "header": "X-Pakhi-Edge-Status",
            "endpoints": ["/v1/signals/*", "/v1/ledger", "WS /v1/stream/signals"],
            "computed_from": "paper_ledger rows where scored=True",
            "n_min": _n_min(),
            "states": {
                "underpowered": f"n_scored_events < N_MIN ({_n_min()})",
                "unproven": f"n_scored_events >= N_MIN ({_n_min()}) but no recorded PASS G1 re-run verdict",
                "proven": "recorded G1 re-run verdict = PASS",
            },
            "header_format": "{status}_n{n_scored_events}",
        },
        "notify": {
            "channel": "cycle_complete",
            "mechanism": "Postgres NOTIFY issued by the orchestrator immediately after all ledger writes for the cycle have committed",
            "payload": {"cycle_id": "string", "publication_ts": "ISO8601"},
            "transaction_safety": "NOTIFY runs post-commit — a cycle that fails or rolls back never pushes",
            "no_shared_memory": "uvicorn and the orchestrator are separate OS processes; the DB is the bus",
            "listener": "dedicated LISTEN connection in a background thread -> asyncio.Queue -> fan-out; reconnect with backoff",
            "t4_prerequisite": "wire the post-commit NOTIFY into run_ws2_t3_orchestrate.py in T4 (prose-only in this contract)",
        },
        "websocket": {
            "path": "/v1/stream/signals",
            "message": {
                "type": "signals.batch",
                "version": "1",
                "cycle_id": "string",
                "publication_ts": "ISO8601",
                "signals": [
                    {
                        "instrument": "string",
                        "action": "string",
                        "size": "float",
                        "confidence": "float",
                        "reasoning": "string|null",
                        "timestamp": "ISO8601",
                        "forecast_cycle_id": "string",
                        "publication_ts": "ISO8601",
                        "archive_source": "string",
                        "model_version": "string",
                    }
                ],
            },
            "heartbeat": "application-level ping every 30s",
            "history_fallback": "missed subscribers covered by GET /v1/signals history — NOTIFY is a wake-up, not the source of truth",
        },
        "backtest_bounds": {
            "max_window_days": 365,
            "model_version_whitelist": MODEL_VERSION_WHITELIST,
            "instrument_whitelist": [LIVE_INSTRUMENT],
            "per_key_cap": {"max_queued": 1, "window_seconds": 300},
            "rejections": "422 (locked error envelope) for over-bounds params; 429 for queue-full",
        },
        "routes": {
            "GET /v1/health": {
                "purpose": "liveness only (Docker/K8s probes)",
                "response": {"status": "ok"},
            },
            "GET /v1/status": {
                "purpose": "readiness + data freshness",
                "response": {
                    "db_ok": "bool",
                    "latest_cycle_id": "string",
                    "publication_ts": "ISO8601|null",
                    "staleness_seconds": "float|null",
                    "worker_last_run": "ISO8601|null (from metrics worker.last_run when present, else latest cycle publication_ts)",
                },
            },
            "GET /v1/instruments": {
                "purpose": "distinct instruments with latest signal + freshness",
                "not_empty": "404 when the store is empty",
            },
            "GET /v1/signals/{instrument}": {
                "purpose": "latest + history (?limit, ?since, ?cycle_id)",
                "provenance": [
                    "forecast_cycle_id",
                    "publication_ts",
                    "archive_source",
                    "model_version",
                ],
                "empty_is_404": True,
                "header": "X-Pakhi-Edge-Status",
            },
            "GET /v1/forecasts/{instrument}": {
                "purpose": "stored forecast rows (?lead=7d)",
                "status": "501 not_implemented until WS-2 stores forecast rows (no forecasts table in the store today)",
            },
            "GET /v1/ensemble/disagreement": {
                "purpose": "stored disagreement series",
                "status": "501 not_implemented (deferred from WS-2)",
            },
            "GET /v1/ledger": {
                "purpose": "paper-ledger summary",
                "label": "paper / not live capital",
                "header": "X-Pakhi-Edge-Status",
                "semantics": {
                    "total_count": "all paper_ledger rows",
                    "scored_count": "rows where scored=True",
                    "net": "SUM(net_of_benchmark) over scored rows, all-time",
                    "mean_net_of_benchmark": "mean(net_of_benchmark) over scored rows",
                },
            },
            "POST /v1/backtests": {
                "purpose": "validate + enqueue (write_engine)",
                "response": "201 {id, status}",
                "bounds": "see backtest_bounds",
            },
            "GET /v1/backtests/{id}": {
                "purpose": "job status",
                "response": {"id": "string", "status": "queued|running|done|failed"},
            },
            "GET /v1/backtests/{id}/result": {
                "purpose": "stream the stored artifact",
                "not_found": "404 when not done",
            },
            "WS /v1/stream/signals": {
                "purpose": "push each new signal batch on cycle_complete",
                "schema": "see websocket",
            },
        },
        "sdk": {
            "layout": "pakhi.client subpackage inside this repo (from pakhi.client import PakhiClient)",
            "surface": [
                "PakhiClient.status()",
                "PakhiClient.signals(instrument)",
                "PakhiClient.forecasts(instrument)",
                "PakhiClient.ledger()",
                "PakhiClient.backtests.create(...)",
                "PakhiClient.stream_signals(on_signal=...)",
            ],
            "transport": "thin, typed, httpx-based; docstrings link to OpenAPI",
        },
        "deferred": {
            "ws4": ["JWT", "RBAC", "multi-tenancy", "audit logs"],
            "ws5": [
                "Prometheus/Grafana",
                "SLOs",
                "status page",
                "multi-worker rate limiting",
                "DR/backups",
            ],
            "ws6": ["metering / billing"],
        },
    }
    payload["payload_sha256"] = payload_sha256(payload)
    return payload


def contract_consistent(record: dict) -> bool:
    """True iff the record's self-hash still pins the payload."""
    body = {k: v for k, v in record.items() if k != "payload_sha256"}
    return record.get("payload_sha256") == payload_sha256(body)


if __name__ == "__main__":
    contract = build_api_contract()
    Path(API_CONTRACT_JSON).parent.mkdir(parents=True, exist_ok=True)
    Path(API_CONTRACT_JSON).write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    print(f"wrote {API_CONTRACT_JSON} sha256={contract['payload_sha256']}")
