"""WS-4 — auth, security, tenancy, compliance.

Import-clean by design: ``import pakhi.ws4`` has no side effects — no DB
connections, no environment reads, no global state. The locked rules live in
``docs/WS4_SECURITY_AND_TENANCY_CONTRACT.md`` and its machine twin
``data/ws4/security_tenancy_contract.json``.

FastAPI-coupled dependencies (``get_tenant_scope`` / ``require_role``) live in
``pakhi.ws4.deps`` and are *not* pulled in by this package import, so the core
stays usable and testable without the ``api`` extra.
"""

from pakhi.ws4 import audit, tenant

__all__ = ["audit", "tenant"]
