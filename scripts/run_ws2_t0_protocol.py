#!/usr/bin/env python3
"""WS-2 T0: pre-register the live paper-trading protocol (hash-pinned).

Usage:
    python scripts/run_ws2_t0_protocol.py

Derives the frozen live θ_p from the historical PIT frame (date <= G1 date,
2026-08-12), builds the pre-registered protocol payload, and writes the
machine twin of the human protocol document:

    data/ws2/paper_trading_protocol.json

Exit code 0 when the record is self-consistent (payload sha256 pins the body);
1 otherwise.  This artifact must exist BEFORE any live paper event is recorded.
"""

from __future__ import annotations

import json
from pathlib import Path

from pakhi.ws1.pit import load_pit
from pakhi.ws2.protocol import (
    build_paper_trading_protocol,
    protocol_consistent,
)

HERE = Path(__file__).resolve().parent.parent
WS2 = HERE / "data" / "ws2"


def main() -> None:
    WS2.mkdir(parents=True, exist_ok=True)
    protocol_path = WS2 / "paper_trading_protocol.json"

    pit = load_pit()
    record = build_paper_trading_protocol(pit)
    protocol_path.write_text(json.dumps(record, indent=2, default=str))

    sig = record["signal"]
    tr = record["trade"]
    print("== WS-2 T0: live paper-trading protocol pre-registration ==")
    print(f"predecessor G1   : {record['predecessor']['g1_outcome']} "
          f"(N={record['predecessor']['g1_n_events']}, N_min={record['event_counting']['n_min']})")
    print(f"signal           : {sig['name']} | fire = freeze_prob >= theta_p AND temperature_min <= theta_t")
    print(f"theta_p (FROZEN) : {sig['theta_p']:.6f} "
          f"(median of {sig['theta_p_n_historical_freeze_rows']} historical freeze rows, date <= G1 2026-08-12)")
    print(f"theta_t          : {sig['theta_t_c']:.2f} C (fixed physical gate)")
    print(f"trade            : next-close fill | hold {tr['hold_sessions']} sessions | "
          f"cost {tr['costs_bps_round_trip']} bps RT | net = gross - 0.0030 - rbar")
    print(f"benchmark rbar   : always-long OJ 2-session, backtest "
          f"{record['benchmark']['rbar_2sess_oos_backtest']:.4f}; live recomputed at the G1 re-run")
    print("armor            : timestamp + vintage + roll_jump (violation => cycle rejected)")
    print(f"change control   : {record['change_control']}")

    assert protocol_consistent(record), "protocol self-hash broken"
    print("\nprotocol self-verifying (payload sha256 pinned)")
    print(f"wrote    : {protocol_path}")
    print(f"sha256   : {record['payload_sha256']}")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
