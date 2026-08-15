"""WS-5 — reliability, observability, SLAs, DR.

Import-clean by design: ``import pakhi.ws5`` has no side effects — no DB
connections, no environment reads, no global state. The locked rules live in
``docs/WS5_RELIABILITY_CONTRACT.md`` and its machine twin
``data/ws5/reliability_contract.json``.

Prometheus wiring (registry, multiprocess mode) is T2 and is *not* pulled in by
this package import, so the core stays usable and testable without the
``prometheus-client`` dependency.
"""

from pakhi.ws5 import contract, metrics

__all__ = ["contract", "metrics"]
