"""WS-4 audit core — hash-chained append + omission reconciliation (T0/T4).

Pure, import-clean, no side effects. Two guarantees, per the §3.5 split:

- **Tamper-evidence:** every row is chained ``hash = sha256(prev_hash |
  canonical_payload)`` so editing a middle row breaks every subsequent link.
- **Omission-evidence:** a reconciliation that replays an *independently
  written* request log (nginx access log, never the app middleware) against
  ``audit_events`` by ``request_id`` and reports any mutating ``request_id``
  with no audit row.

T4 wires these into the appender (atomic-with-mutation) and the sweep; here
they are pure functions so the T4 tests and the runtime share byte-identical
chain logic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable


def canonical_payload(payload: dict[str, Any]) -> str:
    """Deterministic serialization for the chained hash (sort_keys + default=str)."""
    return json.dumps(payload, sort_keys=True, default=str)


def chain_hash(prev_hash: str | None, payload: dict[str, Any]) -> str:
    """Next link in the chain: sha256(prev_hash | canonical_payload).

    ``prev_hash=None`` is the genesis row (chain starts at an explicit
    value so a forged first row cannot be masked by an empty prefix).
    """
    prev = prev_hash if prev_hash is not None else "genesis"
    return hashlib.sha256(f"{prev}|{canonical_payload(payload)}".encode()).hexdigest()


@dataclass
class ChainedRow:
    """A row with its chain fields materialized (``hash``/``prev_hash``)."""

    request_id: str
    action: str
    resource: str
    tenant_id: str
    actor_id: str
    outcome: str
    ts: str
    payload: dict[str, Any] = field(default_factory=dict)
    prev_hash: str | None = None
    hash: str = ""

    def seal(self, prev_hash: str | None) -> None:
        """Compute and store ``prev_hash`` + ``hash`` for this row."""
        self.prev_hash = prev_hash
        self.hash = chain_hash(prev_hash, self.to_payload())

    def to_payload(self) -> dict[str, Any]:
        """Canonical payload this row's hash covers (excludes the hash itself)."""
        return {
            "request_id": self.request_id,
            "action": self.action,
            "resource": self.resource,
            "tenant_id": self.tenant_id,
            "actor_id": self.actor_id,
            "outcome": self.outcome,
            "ts": self.ts,
            **self.payload,
        }


def seal_chain(rows: Iterable[ChainedRow]) -> list[ChainedRow]:
    """Seal a sequence of rows into a chain, mutating each row in place."""
    sealed: list[ChainedRow] = []
    prev: str | None = None
    for row in rows:
        row.seal(prev)
        sealed.append(row)
        prev = row.hash
    return sealed


def verify_chain(rows: Iterable[ChainedRow]) -> tuple[bool, int | None]:
    """Verify a sealed chain. Returns ``(ok, first_bad_index)``.

    ``first_bad_index`` is the 0-based index of the first row whose
    ``prev_hash``/``hash`` no longer matches — None when the chain is intact.
    """
    prev: str | None = None
    for i, row in enumerate(rows):
        expected_hash = chain_hash(prev, row.to_payload())
        if row.hash != expected_hash or row.prev_hash != prev:
            return False, i
        prev = row.hash
    return True, None


def omission_reconciliation(
    access_log: Iterable[dict[str, Any]],
    audit_rows: Iterable[dict[str, Any]],
    *,
    mutating_paths: Iterable[str],
) -> list[str]:
    """Reconcile an independent request log against audit rows.

    ``access_log``: one dict per proxy-logged request, at minimum
    ``{request_id, path}`` — the *nginx* access log, written outside the app.
    ``audit_rows``: audit rows keyed by ``request_id``.
    ``mutating_paths``: request path prefixes that must have an audit row.

    Returns the list of ``request_id`` values that are mutating, present in
    the access log, and missing from the audit rows — the omissions the sweep
    must fail on. Rows are compared by ``request_id`` only, mirroring the T4
    join.
    """
    mutating = {
        r["request_id"] for r in access_log if _is_mutating(r.get("path", ""), mutating_paths)
    }
    audited = {r["request_id"] for r in audit_rows}
    return sorted(mutating - audited)


def _is_mutating(path: str, mutating_paths: Iterable[str]) -> bool:
    return any(path.startswith(prefix) for prefix in mutating_paths)
