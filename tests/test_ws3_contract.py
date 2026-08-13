"""WS-3 T0: locked API contract — self-hash pins + required fields.

The contract is the WS-3 twin of the WS-1 evaluation contract / WS-2 paper
trading protocol: it must exist, self-hash-pin, and cover every policy the
endpoints will be held to.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from pakhi.api.contract import (
    API_CONTRACT_DOC,
    API_CONTRACT_JSON,
    LIVE_INSTRUMENT,
    MODEL_VERSION_WHITELIST,
    N_MIN,
    build_api_contract,
    contract_consistent,
)
from pakhi.ws1.significance import N_MIN as WS1_N_MIN

HERE = Path(__file__).resolve().parent.parent
CONTRACT_PATH = HERE / API_CONTRACT_JSON
DOC_PATH = HERE / API_CONTRACT_DOC


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text())


def test_contract_artifact_exists():
    assert CONTRACT_PATH.exists(), "contract JSON must be generated (python -m pakhi.api.contract)"
    assert DOC_PATH.exists(), "contract doc must exist"
    rec = json.loads(CONTRACT_PATH.read_text())
    assert rec["status"] == "LOCKED"


def test_contract_self_hash_pins():
    rec = json.loads(CONTRACT_PATH.read_text())
    assert contract_consistent(rec), "payload sha256 must still pin the payload"
    assert len(rec["payload_sha256"]) == 64


def test_doc_hash_matches_artifact(contract):
    doc = DOC_PATH.read_text()
    m = re.search(r"sha256\s*`([0-9a-f]{64})`", doc)
    assert m, "contract doc must state the payload sha256"
    assert m.group(1) == contract["payload_sha256"], (
        "doc and JSON must pin the same hash (re-lock both on any change)"
    )


def test_contract_matches_builder():
    rec = json.loads(CONTRACT_PATH.read_text())
    built = build_api_contract(locked_utc=rec["locked_utc"])
    assert rec == built, "artifact must be byte-identical to the builder output"


def test_predecessor_reads_g1_decision(contract):
    pred = contract["predecessor"]
    assert pred["g1_outcome"] == "UNDER_POWERED"
    assert pred["g1_n_events"] == 7
    assert pred["g1_decision_json"].endswith("g1_decision.json")


def test_n_min_matches_ws1_source(contract):
    assert int(WS1_N_MIN) == N_MIN, "contract N_MIN must match pakhi.ws1.significance"
    assert contract["edge_status"]["n_min"] == int(WS1_N_MIN)


def test_edge_status_policy(contract):
    es = contract["edge_status"]
    assert es["n_min"] == int(N_MIN)
    assert es["computed_from"] == "paper_ledger rows where scored=True"
    assert es["header_format"] == "{status}_n{n_scored_events}"
    assert set(es["states"]) == {"underpowered", "unproven", "proven"}
    assert es["header"] == "X-Pakhi-Edge-Status"


def test_backtest_bounds(contract):
    b = contract["backtest_bounds"]
    assert b["max_window_days"] == 365
    assert b["model_version_whitelist"] == MODEL_VERSION_WHITELIST
    assert LIVE_INSTRUMENT in b["instrument_whitelist"]
    assert b["per_key_cap"]["max_queued"] == 1
    assert b["per_key_cap"]["window_seconds"] == 300


def test_error_envelope_locked(contract):
    env = contract["error_envelope"]
    assert env["shape"] == {"error": {"code": "string", "message": "string", "details": "optional"}}
    handlers = " ".join(env["mapped_handlers"])
    assert "RequestValidationError" in handlers
    assert "HTTPException" in handlers
    assert "500" in handlers, "unhandled exceptions must map to the envelope too"


def test_two_engine_policy(contract):
    eng = contract["engines"]
    assert eng["read_engine"]["role"] == "postgres_readonly"
    assert eng["write_engine"]["role"] == "postgres"
    assert "backtest_jobs INSERT" in eng["write_engine"]["used_for"]
    assert "provisioning" in eng, "readonly role provisioning must be tracked as a T1 dependency"


def test_cors_policy(contract):
    cors = contract["cors"]
    assert cors["middleware"] == "CORSMiddleware"
    assert cors["allowlist_env"] == "PAKHI_CORS_ORIGINS"
    assert "GET" in cors["allow_methods"] and "OPTIONS" in cors["allow_methods"]


def test_sdk_layout(contract):
    sdk = contract["sdk"]
    assert sdk["layout"].startswith("pakhi.client")
    surfaces = " ".join(sdk["surface"])
    for method in [
        "status",
        "signals",
        "forecasts",
        "ledger",
        "backtests.create",
        "stream_signals",
    ]:
        assert method in surfaces


def test_sync_def_endpoint_policy(contract):
    ep = contract["endpoint_policy"]
    assert ep["data_handlers"].startswith("sync def")
    assert "WS /v1/stream/signals" in ep["only_async"]


def test_notify_channel(contract):
    n = contract["notify"]
    assert n["channel"] == "cycle_complete"
    assert set(n["payload"]) == {"cycle_id", "publication_ts"}
    assert n["transaction_safety"].startswith("NOTIFY runs post-commit")
    assert "t4_prerequisite" in n, "NOTIFY wiring must be recorded as a T4 prerequisite"


def test_routes_locked(contract):
    routes = contract["routes"]
    required = [
        "GET /v1/health",
        "GET /v1/status",
        "GET /v1/instruments",
        "GET /v1/signals/{instrument}",
        "GET /v1/forecasts/{instrument}",
        "GET /v1/ensemble/disagreement",
        "GET /v1/ledger",
        "POST /v1/backtests",
        "GET /v1/backtests/{id}",
        "GET /v1/backtests/{id}/result",
        "WS /v1/stream/signals",
    ]
    for r in required:
        assert r in routes, f"route {r} must be in the locked contract"
    assert routes["GET /v1/signals/{instrument}"]["empty_is_404"] is True
    assert routes["GET /v1/forecasts/{instrument}"]["status"].startswith("501")
    assert routes["GET /v1/ensemble/disagreement"]["status"].startswith("501")


def test_websocket_schema(contract):
    ws = contract["websocket"]
    assert ws["path"] == "/v1/stream/signals"
    assert ws["message"]["type"] == "signals.batch"
    signal_fields = {
        "instrument",
        "action",
        "size",
        "confidence",
        "reasoning",
        "timestamp",
        "forecast_cycle_id",
        "publication_ts",
        "archive_source",
        "model_version",
    }
    assert set(ws["message"]["signals"][0]) == signal_fields


def test_gate_recorded(contract):
    progress = (HERE / "docs" / "WS3_PROGRESS.md").read_text()
    assert "infra-first" in progress, "gate verdict must be recorded in WS3_PROGRESS.md"
    pred = contract["predecessor"]
    assert pred["g1_outcome"] in progress, "progress gate verdict must cite the real G1 outcome"
    assert str(pred["g1_n_events"]) in progress, "progress gate verdict must cite the real N"
    assert "does not clear G1" in progress, "infra-first build must not over-claim G1"
