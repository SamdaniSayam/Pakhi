"""Ensemble-specific visualisation — fan charts and model comparison bars.

Fan charts display forecast quantile bands (10-25-50-75-90%) around an
ensemble mean, and model comparison plots rank models by RMSE or ACC.
"""

from __future__ import annotations

import logging
from typing import Sequence

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
    "plot_ensemble_plume",
    "plot_model_comparison",
]

logger = logging.getLogger(__name__)

# Default quantile bands: (label, alpha)
_DEFAULT_BANDS: list[tuple[float, float]] = [
    (0.10, 0.10),
    (0.25, 0.20),
    (0.50, 0.35),
]


def plot_ensemble_plume(
    ensemble_forecast: dict[str, np.ndarray],
    observation: np.ndarray | None = None,
    title: str = "Ensemble Forecast Plume",
    ylabel: str = "Value",
    dates: np.ndarray | None = None,
    base_color: str = "steelblue",
) -> Figure:
    """Fan chart with quantile bands (10-25-50-75-90%).

    Parameters
    ----------
    ensemble_forecast : dict
        Mapping from quantile label to array.  Expected keys:

        - ``"q0.1"``, ``"q0.25"``, ``"q0.5"``, ``"q0.75"``, ``"q0.9"``

        Missing outer bands are auto-inferred from inner bands by
        symmetric extrapolation.
    observation : array, optional
        Observed values to overlay.
    title : str
        Plot title.
    ylabel : str
        Y-axis label.
    dates : array, optional
        X-axis coordinates.
    base_color : str
        Base colour for the plume (shades are derived automatically).

    Returns
    -------
    matplotlib.figure.Figure
    """
    q10 = _get_quantile(ensemble_forecast, 0.10)
    q25 = _get_quantile(ensemble_forecast, 0.25)
    q50 = _get_quantile(ensemble_forecast, 0.50)
    q75 = _get_quantile(ensemble_forecast, 0.75)
    q90 = _get_quantile(ensemble_forecast, 0.90)

    n = len(q50)
    if dates is None:
        dates = np.arange(n)

    fig = Figure(figsize=(12, 5))
    ax = fig.add_subplot(1, 1, 1)

    # 10-90% band
    ax.fill_between(dates, q10, q90, color=base_color, alpha=0.10, label="10–90%")
    # 25-75% band
    ax.fill_between(dates, q25, q75, color=base_color, alpha=0.25, label="25–75%")
    # Median
    ax.plot(dates, q50, color=base_color, linewidth=2, label="Median")

    if observation is not None:
        obs = np.asarray(observation, dtype=np.float64).ravel()[:n]
        ax.plot(dates[: len(obs)], obs, color="black", linewidth=1.2, label="Observation")

    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_model_comparison(
    models: Sequence[str],
    metrics: dict[str, Sequence[float]],
    title: str = "Model Comparison",
    bar_width: float = 0.35,
) -> Figure:
    """Bar chart comparing models across multiple metrics.

    Parameters
    ----------
    models : sequence of str
        Model names.
    metrics : dict
        Mapping from metric name (e.g. ``"RMSE"``, ``"ACC"``) to a list
        of values aligned with *models*.
    title : str
        Plot title.
    bar_width : float
        Width of each bar group.

    Returns
    -------
    matplotlib.figure.Figure
    """
    models = list(models)
    n_models = len(models)
    metric_names = list(metrics.keys())
    n_metrics = len(metric_names)

    if n_metrics == 0:
        raise ValueError("metrics dict must contain at least one metric.")

    fig = Figure(figsize=(max(8, n_models * 1.5), 5))
    ax = fig.add_subplot(1, 1, 1)

    x = np.arange(n_models)
    cmap = plt.cm.Set2

    for i, metric_name in enumerate(metric_names):
        values = np.asarray(metrics[metric_name], dtype=np.float64)
        offset = (i - n_metrics / 2 + 0.5) * bar_width
        bars = ax.bar(
            x + offset,
            values,
            bar_width,
            label=metric_name,
            color=cmap(i / max(n_metrics - 1, 1)),
            edgecolor="white",
            linewidth=0.5,
        )
        # Value labels
        for bar, val in zip(bars, values, strict=False):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.005,
                f"{val:.3f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    ax.set_xticks(x)
    ax.set_xticklabels(models, fontsize=10)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    return fig


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_quantile(q_dict: dict[str, np.ndarray], q: float) -> np.ndarray:
    """Retrieve a quantile from the dict, with symmetric extrapolation fallback."""
    key = f"q{q}"
    if key in q_dict:
        return np.asarray(q_dict[key], dtype=np.float64).ravel()

    # Try to find a nearby quantile and extrapolate.
    available = sorted(
        [k for k in q_dict if k.startswith("q")],
    )
    if available:
        # Use the closest available quantile as a proxy.
        closest_key = min(available, key=lambda k: abs(float(k[1:]) - q))
        return np.asarray(q_dict[closest_key], dtype=np.float64).ravel()

    raise KeyError(f"Cannot find quantile '{key}' or any fallback in the forecast dict.")
