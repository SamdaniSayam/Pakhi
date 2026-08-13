"""WS-3 Public API package (REST + WebSocket).

A thin, fast-read, single-tenant layer over the WS-2 store.  Everything a
consumer needs to know about the API is locked up front in the hash-pinned
contract (``docs/WS3_API_CONTRACT.md`` + ``data/ws3/api_contract.json``), the
WS-3 twin of the WS-1 evaluation-contract / WS-2 protocol discipline.

Notable policies (all decided in T0, all enforced by tests):

- **Two engines, by role:** every ``GET /v1/*`` uses ``read_engine``
  (``postgres_readonly``); the only writes the API is allowed
  (``backtest_jobs`` enqueue + key/rate-limit bookkeeping) use
  ``write_engine`` (app role).  A read-only connection is never used for a
  write and vice-versa.
- **Sync ``def`` data handlers:** blocking DB work happens in the anyio worker
  threadpool so the asyncio loop stays free for WebSockets.  Only WebSocket
  endpoints are ``async def``.
- **Honesty over freshness:** stale data is labeled stale
  (``X-Pakhi-Staleness``), never backfilled; edge status is always disclosed
  (``X-Pakhi-Edge-Status``), computed from the paper ledger.
"""
