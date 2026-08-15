"""WS-6 T4 — support SLA + financial-integrity wrap (hermetic, SQLite).

Contract §7/§8 exactly: severities + response targets + triage keywords +
escalation are hash-pinned in the twin and the parser reads only the twin;
S1 incidents surface on /v1/status via the audit chain; financial audit rows
are never pruned by any retention path (the only deletes in the repo prune
backup/ingest *files*).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine

from pakhi.ws4.audit_events import AuditSpec, apply_audit
from pakhi.ws6.contract import billing_contract, contract_consistent
from pakhi.ws6.db import init_db
from pakhi.ws6.support import (
    classify_severity,
    escalation_path,
    recent_incidents,
    response_target,
    support_sla,
)

_NOW = datetime.now(timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def _engine():
    eng = create_engine("sqlite://", future=True)
    init_db(eng)
    return eng


def _s1(eng, tenant: str = "acme", ts: str | None = None, action: str = "metering.s1") -> None:
    from sqlalchemy.orm import Session

    with Session(eng) as s:
        apply_audit(
            s,
            AuditSpec(
                request_id=f"s1-{tenant}-{ts or _NOW.timestamp()}",
                tenant_id=tenant,
                actor_id="ws6.meter",
                action=action,
                resource="metering",
                resource_id=tenant,
                payload={"reason": "drift beyond tolerance", "drift_percent": 3.2},
                ts=ts,
            ),
        )
        s.commit()


def test_support_targets_hash_pinned_in_twin() -> None:
    assert contract_consistent()
    sla = support_sla()
    assert sla["paid_tiers_only"] is True
    assert response_target("S1") == "4h"
    assert response_target("S2") == "12h"
    assert response_target("S3") == "2 business days"
    # parser reads the twin's locked keywords (single source of truth)
    for sev in ("S1", "S2", "S3"):
        assert sla["severities"][sev]["keywords"], f"{sev} has no locked keywords"
    assert set(sla["escalation"]) == {"S1", "S2", "S3"}


def test_severity_parser_is_deterministic() -> None:
    assert classify_severity("the API is DOWN and my data is gone") == "S1"
    assert classify_severity("data integrity breach on backtests") == "S1"
    assert classify_severity("key suspended after drift") == "S1"
    assert classify_severity("pipeline is slow and timing out") == "S2"
    assert classify_severity("blocking bug in refresh") == "S2"
    assert classify_severity("how do I rotate my key?") == "S3"
    assert classify_severity("minor typo in docs") == "S3"
    assert classify_severity("nothing matches any keyword here") == "S3"  # default
    # S1 wins over a later S2/S3 keyword in the same text
    assert classify_severity("service down AND slow responses") == "S1"
    # case-insensitive
    assert classify_severity("OUTAGE NOW") == "S1"


def test_escalation_matrix_documented() -> None:
    assert "page on-call" in escalation_path("S1")
    assert "respond within target" in escalation_path("S2")
    assert "business days" in escalation_path("S3")


def test_s1_incidents_feed_reads_the_audit_chain() -> None:
    eng = _engine()
    _s1(eng, tenant="acme", ts=(_NOW - timedelta(hours=1)).isoformat())
    _s1(eng, tenant="bob", ts=_NOW.isoformat(), action="metering.suspend")
    incidents = recent_incidents(eng, limit=5)
    assert len(incidents) == 2
    assert incidents[0]["tenant"] == "bob"  # newest first
    assert incidents[0]["action"] == "metering.suspend"
    assert {"ts", "tenant", "action", "summary"} <= set(incidents[0])
    assert all(
        i["action"] in {"metering.s1", "metering.suspend", "metering.block_invoice"}
        for i in incidents
    )


def test_status_page_surfaces_incidents_feed(tmp_path) -> None:
    from fastapi.testclient import TestClient

    from pakhi.api.main import create_app
    from pakhi.api.settings import Settings
    from tests.test_ws3_api import _seed

    db = f"sqlite:///{tmp_path / 'store.db'}"
    _seed(db, [])
    app = create_app(Settings(read_db_url=db, write_db_url=db))
    with TestClient(app) as client:
        resp = client.get("/v1/status")
    assert resp.status_code == 200
    body = resp.json()
    assert "incidents" in body
    assert isinstance(body["incidents"], list)


def test_financial_rows_never_pruned_no_db_delete_in_production() -> None:
    """No production code path deletes audit-chain or financial-table rows."""
    forbidden = []
    for rel in sorted(list((ROOT / "pakhi").glob("**/*.py"))):
        text = rel.read_text()
        if ".delete(" in text or "DELETE FROM" in text:
            forbidden.append(str(rel))
    assert forbidden == [], f"production DB deletes found: {forbidden}"
    assert billing_contract()["retention"] == (
        "metering/rollup/billing rows are audit-chain rows, never pruned by the normal retention job"
    )
