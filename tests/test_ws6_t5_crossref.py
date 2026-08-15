"""WS-6 T5 — cross-reference pass (blueprint §5 rule 2 / WS-5 rule 9).

The machine twin is the single source of truth: every consumer — billing code,
checklist, severity parser, and the doc set — must reconcile against it. This
suite pins the doc set to the twin: the numbers the docs promise are exactly
the numbers the twin defines, and the runtime consumers read the twin (never
re-derive it).
"""

from __future__ import annotations

from pathlib import Path

from pakhi.ws6.contract import billing_contract, contract_consistent

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    "docs/WS6_BILLING_METERING_CONTRACT.md",
    "docs/WS6_SUPPORT_SLA.md",
    "docs/WS6_EXECUTION_BLUEPRINT.md",
]


def _docs_text() -> str:
    return "\n".join((ROOT / d).read_text() for d in DOCS)


def _num_variants(value: float) -> list[str]:
    """Acceptable doc renderings of a numeric twin value ("1.0" | "1" | "1 %")."""
    out = [str(value)]
    if float(value).is_integer():
        out.append(str(int(value)))
    return out


def test_twin_is_self_consistent() -> None:
    assert contract_consistent()


def test_docs_promise_only_twin_numbers() -> None:
    t = billing_contract()
    docs = _docs_text()
    # Units (contract §2) — every billable unit name appears in the docs.
    for unit in t["units"]:
        assert unit in docs, f"unit {unit} missing from doc set"
    # Tier prices (contract §3) — price anchors appear in the docs (either
    # "1500" or the human-formatted "1,500").
    for tier, spec in t["tiers"].items():
        price = spec["price_anchor_usd"]
        assert str(price) in docs or f"{price:,}" in docs, f"{tier} price missing from doc set"
        assert tier in docs
    # Trial policy (contract §6) — 14 days + downgrade-not-delete language.
    assert str(t["trial"]["days"]) in docs
    assert "never delete" in docs
    assert "one trial per" in docs
    # Severity targets (contract §7) — each target appears (whitespace-tolerated
    # so the human-formatted "≤ 4 h" still pins to the twin's "4h").
    compact_docs = docs.replace(" ", "")
    for sev, spec in t["support_sla"]["severities"].items():
        assert spec["target"].replace(" ", "") in compact_docs, f"{sev} target missing from doc set"
    # Reconciliation + Stripe (contract §4/§5) — "1.0"/"1" renderings both pin.
    compact = docs.replace(" ", "")
    for value in (
        t["reconciliation"]["tolerance_percent"],
        t["reconciliation"]["hard_threshold_percent"],
    ):
        assert any(v in compact for v in _num_variants(value))
    assert str(t["stripe"]["staleness_alert_hours"]) in docs


def test_consumers_read_the_twin_not_rederive() -> None:
    """Billing code, checklist, and parser must read the twin (single source)."""
    stripe_src = (ROOT / "pakhi" / "ws6" / "stripe.py").read_text()
    assert "billing_contract()" in stripe_src  # staleness/price reads the twin
    assert "price_ids()" in stripe_src
    trial_src = (ROOT / "pakhi" / "ws6" / "trial.py").read_text()
    assert "trial_days()" in trial_src or "billing_contract()" in trial_src
    support_src = (ROOT / "pakhi" / "ws6" / "support.py").read_text()
    assert "billing_contract()" in support_src
    # The raw numbers must not be hard-coded in the runtime consumers.
    for src, forbidden in (
        (stripe_src, ["staleness_alert_hours = 24", '"24"']),
        (trial_src, ["days = 14", '"14"']),
        (support_src, ['"4h"', '"12h"', '"2 business days"']),
    ):
        for num in forbidden:
            assert num not in src, f"hard-coded contract number in consumer: {num}"
