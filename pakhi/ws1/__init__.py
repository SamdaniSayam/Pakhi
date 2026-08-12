"""WS-1: as-published backtest platform (evaluation harness).

Modules
-------
pit : PIT load/validation + locked folds, OOS window, embargo, benchmark
episodes : locked freeze-episode segmentation (§2)
signal : 2-session hold schedule + engine-compatible signal generator
metrics : event-based (trade-level) Sharpe, t-stat, bootstrap CI
harness : PIT -> events -> BacktestEngine -> report
"""

from __future__ import annotations

from pakhi.ws1 import episodes, harness, metrics, pit, signal

__all__ = ["episodes", "harness", "metrics", "pit", "signal"]
