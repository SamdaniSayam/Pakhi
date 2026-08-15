#!/usr/bin/env python3
"""WS-4 T1: bootstrap an admin user + first token pair (exit 0/1).

Usage:
    PAKHI_DB_WRITE_URL=postgresql://postgres:postgres@localhost:5432/pakhi \
    PAKHI_JWT_SECRET=<platform secret> \
    python scripts/run_ws4_t1_tokens.py [--user admin] [--tenant pakhi-internal] [--roles admin]

Creates/upserts the admin user and issues one access JWT + refresh pair, then
prints them (the refresh token is shown exactly once). Exit 0 on success, 1 on
failure. Refuses to run when ``PAKHI_JWT_SECRET`` is missing or equal to a
documented test default.
"""

from __future__ import annotations

import argparse
import sys

from pakhi.api.db import build_engine
from pakhi.api.settings import DEFAULT_WRITE_DB_URL
from pakhi.ws4.db import init_db
from pakhi.ws4.service import issue_tokens
from pakhi.ws4.tokens import ACCESS_TOKEN_TTL_MINUTES

# Documented test defaults the boot gate refuses (mirrors the T3 boot gate).
_WEAK_SECRETS = {
    "test-secret-change-me",
    "change-me",
    "insecure-jwt-secret",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="WS-4 T1 admin bootstrap")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--tenant", default="pakhi-internal")
    parser.add_argument("--roles", default="admin")
    parser.add_argument("--db-url", default=DEFAULT_WRITE_DB_URL)
    args = parser.parse_args()

    import os

    secret = os.environ.get("PAKHI_JWT_SECRET") or ""
    if not secret or secret in _WEAK_SECRETS or len(secret) < 16:
        print("ERROR: PAKHI_JWT_SECRET must be set to a strong, non-default value", file=sys.stderr)
        return 1

    roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    if not roles:
        print("ERROR: --roles must not be empty", file=sys.stderr)
        return 1

    engine = build_engine(args.db_url)
    init_db(engine)
    try:
        result = issue_tokens(
            engine,
            user_id=args.user,
            tenant_id=args.tenant,
            roles=roles,
            secret=secret,
            tier="free",
            created_by="bootstrap-cli",
        )
    finally:
        engine.dispose()

    print("== WS-4 T1: admin bootstrap token ==")
    print(f"user_id      : {result.user_id}")
    print(f"tenant_id    : {result.tenant_id}")
    print(f"access_token : {result.access_token}")
    print(f"refresh_token: {result.refresh_token}  (shown once; hashed at rest)")
    print(f"expires_in   : {result.expires_in}s (access JWT, {ACCESS_TOKEN_TTL_MINUTES} min)")
    print(f"token_type   : {result.token_type}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
