"""Time-series visualisation — forecasts, ensembles, and trading signals.

Standard line plots for comparing forecasts to observations, ensemble
spaghetti plots, and signal-over-price overlays.
"""

from __future__ import annotations

import logging

import numpy as np

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
except ImportError:
    raise ImportError(
        "matplotlib is required for pakhi.viz. Install it with: pip install 'pakhi[viz]'"
    )

__all__ = [
    "plot_ensemble_spread",
    "plot_forecast_vs_obs",
    "plot_signal_history",
]

logger = logging.getLogger(__name__)


def plot_forecast_vs_obs(
    forecast: np.ndarray,
    observations: np.ndarray,
    forecast_dates: np.ndarray | None = None,
    obs_dates: np.ndarray | None = None,
    title: str = "Forecast vs Observations",
    ylabel: str = "Value",
    confidence_lower: np.ndarray | None = None,
    confidence_upper: np.ndarray | None = None,
) -> Figure:
    """Line plot of forecast against observations with optional confidence bands.

    Parameters
    ----------
    forecast : array of shape ``(n,)``
        Forecast values.
    observations : array of shape ``(n,)``
        Observed values (aligned to the same time axis).
    forecast_dates, obs_dates : array, optional
        X-axis values (e.g. ``np.arange(n)`` or datetime array).
    title : str
        Plot title.
    ylabel : str
        Y-axis label.
    confidence_lower, confidence_upper : array, optional
        Bounds for a shaded confidence band around the forecast.

    Returns
    -------
    matplotlib.figure.Figure
    """
    forecast = np.asarray(forecast, dtype=np.float64).ravel()
    observations = np.asarray(observations, dtype=np.float64).ravel()
    n = len(forecast)

    if forecast_dates is None:
        forecast_dates = np.arange(n)
    if obs_dates is None:
        obs_dates = np.arange(len(observations))

    fig, ax = plt.subplots(figsize=(12, 5))

    ax.plot(obs_dates[:n], observations[:n], color="black", linewidth=1.2, label="Observations")
    ax.plot(forecast_dates[:n], forecast[:n], color="steelblue", linewidth=1.2, label="Forecast")

    if confidence_lower is not None and confidence_upper is not None:
        cl = np.asarray(confidence_lower, dtype=np.float64).ravel()[:n]
        cu = np.asarray(confidence_upper, dtype=np.float64).ravel()[:n]
        ax.fill_between(
            forecast_dates[:n],
            cl,
            cu,
            color="steelblue",
            alpha=0.2,
            label="Confidence band",
        )

    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_ensemble_spread(
    ensemble_members: np.ndarray,
    observations: np.ndarray,
    member_dates: np.ndarray | None = None,
    obs_dates: np.ndarray | None = None,
    title: str = "Ensemble Spread",
    ylabel: str = "Value",
    member_alpha: float = 0.3,
    member_color: str = "steelblue",
) -> Figure:
    """Spaghetti plot of ensemble members against observations.

    Parameters
    ----------
    ensemble_members : array of shape ``(n_members, n_timesteps)``
        Each row is one ensemble member's trajectory.
    observations : array of shape ``(n_timesteps,)``
        Observed values.
    member_dates, obs_dates : array, optional
        X-axis coordinates.
    title : str
        Plot title.
    ylabel : str
        Y-axis label.
    member_alpha : float
        Transparency for individual member lines.
    member_color : str
        Base colour for ensemble members.

    Returns
    -------
    matplotlib.figure.Figure
    """
    ensemble_members = np.asarray(ensemble_members, dtype=np.float64)
    observations = np.asarray(observations, dtype=np.float64).ravel()

    n_members, n_steps = ensemble_members.shape

    if member_dates is None:
        member_dates = np.arange(n_steps)
    if obs_dates is None:
        obs_dates = np.arange(len(observations))

    fig, ax = plt.subplots(figsize=(12, 5))

    for i in range(n_members):
        ax.plot(
            member_dates[:n_steps],
            ensemble_members[i, :n_steps],
            color=member_color,
            alpha=member_alpha,
            linewidth=0.8,
        )

    # Ensemble mean
    ens_mean = np.mean(ensemble_members, axis=0)
    ax.plot(
        member_dates[:n_steps],
        ens_mean[:n_steps],
        color="darkblue",
        linewidth=2,
        label="Ensemble mean",
    )

    ax.plot(
        obs_dates[:n_steps],
        observations[:n_steps],
        color="black",
        linewidth=1.5,
        label="Observations",
    )

    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_signal_history(
    signals: np.ndarray,
    prices: np.ndarray,
    signal_dates: np.ndarray | None = None,
    price_dates: np.ndarray | None = None,
    title: str = "Trading Signals",
    ylabel: str = "Price",
) -> Figure:
    """Overlay trading signals on a price chart.

    Parameters
    ----------
    signals : array of shape ``(n,)``
        Signal values.  Positive = long, negative = short, zero = flat.
    prices : array of shape ``(n,)``
        Instrument prices.
    signal_dates, price_dates : array, optional
        X-axis coordinates.
    title : str
        Plot title.
    ylabel : str
        Y-axis label for the price series.

    Returns
    -------
    matplotlib.figure.Figure
    """
    signals = np.asarray(signals, dtype=np.float64).ravel()
    prices = np.asarray(prices, dtype=np.float64).ravel()
    n = min(len(signals), len(prices))

    if signal_dates is None:
        signal_dates = np.arange(n)
    if price_dates is None:
        price_dates = np.arange(n)

    fig, ax1 = plt.subplots(figsize=(12, 5))

    ax1.plot(price_dates[:n], prices[:n], color="black", linewidth=1.0, label="Price")
    ax1.set_ylabel(ylabel, color="black")
    ax1.tick_params(axis="y", labelcolor="black")

    ax2 = ax1.twinx()

    # Color-coded signal bars
    colors = np.where(
        signals[:n] > 0,
        "green",
        np.where(signals[:n] < 0, "red", "gray"),
    )
    ax2.bar(signal_dates[:n], signals[:n], color=colors, alpha=0.5, width=1.0, label="Signal")
    ax2.set_ylabel("Signal", color="gray")
    ax2.tick_params(axis="y", labelcolor="gray")

    # Add horizontal line at zero
    ax2.axhline(y=0, color="gray", linewidth=0.5, linestyle="--")

    ax1.set_title(title, fontsize=13, fontweight="bold")
    ax1.grid(True, alpha=0.2)

    # Combined legend
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="best", fontsize=9)

    fig.tight_layout()
    return fig
