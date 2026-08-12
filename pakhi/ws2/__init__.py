"""WS-2: signal service (batch precompute + store) — Phase 2 paper-trading loop.

Modules
-------
protocol : T0 live paper-trading protocol (pre-registered, hash-pinned)
"""

from __future__ import annotations

from pakhi.ws2 import protocol

__all__ = ["protocol"]
