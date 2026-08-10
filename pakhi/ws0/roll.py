"""WS-0 continuous futures contracts with roll adjustment and provenance.

A naive splice of front-month prices has phantom jumps at roll dates that are
unrelated to the signal. This module:

- maps each trading day to its contract month via the roll calendar;
- applies a back-adjustment factor at each roll date;
- runs a roll-jump assertion to flag any move that is either a real event
  co-located with a roll or a roll artifact that would corrupt a backtest;
- records per-roll provenance (date, adjustment type, factor, flags).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd


@dataclass
class RollProvenance:
    """Provenance record for one roll event."""

    roll_date: date
    contract_from: str
    contract_to: str
    adjustment_type: str
    factor: float
    flagged: bool
    flag_reason: str = ""


@dataclass
class ContinuousSeries:
    """Roll-adjusted continuous series plus its roll provenance."""

    prices: pd.Series
    provenance: list[RollProvenance] = field(default_factory=list)
    raw: pd.Series | None = None

    def provenance_frame(self) -> pd.DataFrame:
        return pd.DataFrame([vars(r) for r in self.provenance])


def front_month_map(
    dates: pd.DatetimeIndex,
    calendar: pd.DataFrame,
    roll_rule: str = "FND",
) -> pd.Series:
    """Map each trading day to its active contract month.

    Args:
        dates: Trading dates.
        calendar: Contract calendar with ``first_notice_day`` / ``last_trading_day``
            columns (and a ``month_name`` column for provenance).
        roll_rule: "FND" (roll on First Notice Day) or "LTD" (roll on Last
            Trading Day).

    Returns:
        Series of contract month names indexed by date.
    """
    trigger_col = "first_notice_day" if roll_rule == "FND" else "last_trading_day"
    triggers = pd.to_datetime(calendar[trigger_col]).sort_values()
    contract_names = dict(zip(pd.to_datetime(calendar[trigger_col]), calendar["month_name"]))

    def _contract(d: pd.Timestamp) -> str:
        active = triggers[triggers >= d] if roll_rule == "LTD" else triggers[triggers > d]
        if active.empty:
            return contract_names[triggers.iloc[-1]]
        return contract_names[active.iloc[0]]

    return pd.Series([_contract(d) for d in dates], index=dates, name="contract")


def back_adjust(
    front_series: pd.Series,
    calendar: pd.DataFrame,
    roll_rule: str = "FND",
    n_sigma: float = 5.0,
    sigma_window: int = 30,
) -> ContinuousSeries:
    """Build a back-adjusted continuous series with roll-jump assertions.

    At each roll date the price gap across the roll is measured. Gaps below
    ``n_sigma`` daily-volatility units are treated as roll artifacts and removed
    by back-adjusting earlier prices. Larger gaps are flagged (suspected real
    events) and left unadjusted, so they are never silently deleted.

    Args:
        front_series: Raw front-month continuous price series (DatetimeIndex).
        calendar: Contract calendar.
        roll_rule: "FND" or "LTD".
        n_sigma: Multiple of rolling daily sigma above which a roll-date gap is
            flagged as a real event instead of adjusted away.
        sigma_window: Rolling window for the daily-sigma estimate.

    Returns:
        ContinuousSeries with adjusted prices and provenance records.
    """
    adj = front_series.copy()
    rets = front_series.pct_change()
    sigma = rets.rolling(sigma_window, min_periods=10).std()
    trigger_col = "first_notice_day" if roll_rule == "FND" else "last_trading_day"
    calendar_sorted = calendar.sort_values(trigger_col)
    provenance: list[RollProvenance] = []

    for idx, row in calendar_sorted.iterrows():
        roll_dt = pd.Timestamp(row[trigger_col])
        if roll_dt not in adj.index:
            continue
        pos = adj.index.get_loc(roll_dt)
        if pos == 0:
            continue
        prev_close = adj.iloc[pos - 1]
        gap = adj.iloc[pos] / prev_close if prev_close else 1.0
        sig = sigma.iloc[pos - 1] if pos >= 1 else np.nan
        if not np.isnan(sig) and sig > 1e-6:
            threshold = 1 + n_sigma * sig
        else:
            threshold = 1.5  # degenerate flat regime: >1.5x gap is a real event
        flagged = bool(gap >= threshold or gap <= 1 / threshold)
        if not flagged and gap != 1.0:
            adj.iloc[:pos] = adj.iloc[:pos] * gap
        provenance.append(
            RollProvenance(
                roll_date=roll_dt.date(),
                contract_from=str(calendar_sorted["month_name"].iloc[idx - 1])
                if idx > 0
                else "",
                contract_to=str(row["month_name"]),
                adjustment_type="back" if not flagged else "none",
                factor=float(gap),
                flagged=flagged,
                flag_reason="" if not flagged else f"gap>{n_sigma}x daily sigma",
            )
        )

    return ContinuousSeries(prices=adj, provenance=provenance, raw=front_series)


def roll_jump_assertion(
    prices: pd.Series,
    roll_dates: list[pd.Timestamp],
    n_sigma: float = 5.0,
    sigma_window: int = 30,
    window_days: int = 3,
) -> pd.DataFrame:
    """Flag any move larger than n_sigma*daily-sigma near a roll date.

    Returns a DataFrame of flagged days with the flag reason, so a backtest can
    reject a result that depends on an un-flagged roll artifact.
    """
    rets = prices.pct_change()
    sigma = rets.rolling(sigma_window, min_periods=10).std()
    flagged: list[dict] = []
    for roll_dt in roll_dates:
        near = pd.date_range(roll_dt - pd.Timedelta(days=window_days),
                             roll_dt + pd.Timedelta(days=window_days))
        for d in prices.index.intersection(near):
            i = prices.index.get_loc(d)
            sig = sigma.iloc[i - 1] if i >= 1 else np.nan
            if not np.isnan(sig) and sig > 1e-6:
                threshold = n_sigma * sig
            else:
                threshold = 1.5
            if abs(rets.iloc[i]) >= threshold:
                flagged.append(
                    {
                        "date": d,
                        "return": float(rets.iloc[i]),
                        "daily_sigma": float(sig),
                        "ratio": float(abs(rets.iloc[i]) / sig) if sig else np.nan,
                        "near_roll": str(roll_dt.date()),
                    }
                )
    return pd.DataFrame(flagged)
