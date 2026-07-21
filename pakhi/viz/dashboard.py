"""Terminal dashboard using plotext for real-time weather and signal display.

Falls back to plain rich tables if plotext is not installed.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

import numpy as np

try:
    import plotext as plt_term

    _HAS_PLOTEXT = True
except ImportError:
    _HAS_PLOTEXT = False

try:
    from rich.console import Console
    from rich.table import Table

    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

__all__ = ["TerminalDashboard"]

logger = logging.getLogger(__name__)


class TerminalDashboard:
    """Rich / plotext terminal dashboard for weather and trading status.

    Parameters
    ----------
    use_plotext : bool
        Try to use plotext for terminal plots.  Falls back to rich
        tables if unavailable.  Default ``True``.

    Examples
    --------
    >>> dash = TerminalDashboard()
    >>> dash.display_current_weather(temp=32.5, wind=15.2, pressure=1012.3)
    """

    def __init__(self, use_plotext: bool = True) -> None:
        self.use_plotext = use_plotext and _HAS_PLOTEXT
        self._console = Console() if _HAS_RICH else None

    def display_current_weather(
        self,
        temp: float,
        wind: float,
        pressure: float,
        humidity: float | None = None,
        description: str | None = None,
    ) -> None:
        """Display current weather conditions in the terminal.

        Parameters
        ----------
        temp : float
            Temperature in °C.
        wind : float
            Wind speed in km/h.
        pressure : float
            Atmospheric pressure in hPa.
        humidity : float, optional
            Relative humidity in %.
        description : str, optional
            Short weather description (e.g. ``"Partly cloudy"``).
        """
        if _HAS_RICH:
            table = Table(title="Current Weather", show_header=True, header_style="bold cyan")
            table.add_column("Parameter", style="white")
            table.add_column("Value", style="green")

            table.add_row("Temperature", f"{temp:.1f} °C")
            table.add_row("Wind Speed", f"{wind:.1f} km/h")
            table.add_row("Pressure", f"{pressure:.1f} hPa")
            if humidity is not None:
                table.add_row("Humidity", f"{humidity:.1f} %")
            if description is not None:
                table.add_row("Conditions", description)

            self._console.print(table)  # type: ignore[union-attr]
        else:
            print("=== Current Weather ===")
            print(f"  Temperature : {temp:.1f} °C")
            print(f"  Wind Speed  : {wind:.1f} km/h")
            print(f"  Pressure    : {pressure:.1f} hPa")
            if humidity is not None:
                print(f"  Humidity    : {humidity:.1f} %")
            if description is not None:
                print(f"  Conditions  : {description}")

    def display_forecast_table(
        self,
        forecast_7day: Sequence[dict[str, Any]],
    ) -> None:
        """Display a 7-day forecast as a formatted table.

        Parameters
        ----------
        forecast_7day : sequence of dict
            Each dict should have keys like ``"date"``, ``"temp_high"``,
            ``"temp_low"``, ``"wind"``, ``"precip_prob"``, ``"description"``.
        """
        if _HAS_RICH:
            table = Table(title="7-Day Forecast", show_header=True, header_style="bold cyan")
            table.add_column("Date", style="white")
            table.add_column("High", justify="right", style="red")
            table.add_column("Low", justify="right", style="blue")
            table.add_column("Wind", justify="right", style="green")
            table.add_column("Precip %", justify="right", style="yellow")
            table.add_column("Conditions", style="white")

            for day in forecast_7day:
                table.add_row(
                    str(day.get("date", "—")),
                    f"{day.get('temp_high', 0):.1f}°",
                    f"{day.get('temp_low', 0):.1f}°",
                    f"{day.get('wind', 0):.0f} km/h",
                    f"{day.get('precip_prob', 0) * 100:.0f}%",
                    str(day.get("description", "—")),
                )

            self._console.print(table)  # type: ignore[union-attr]
        else:
            print("=== 7-Day Forecast ===")
            header = (
                f"{'Date':>10}  {'High':>6}  {'Low':>6}  {'Wind':>8}  {'Precip':>7}  Conditions"
            )
            print(header)
            print("-" * len(header))
            for day in forecast_7day:
                print(
                    f"{day.get('date', '—')!s:>10}  "
                    f"{day.get('temp_high', 0):>5.1f}°  "
                    f"{day.get('temp_low', 0):>5.1f}°  "
                    f"{day.get('wind', 0):>6.0f}  "
                    f"{day.get('precip_prob', 0) * 100:>5.0f}%  "
                    f"{day.get('description', '—')}"
                )

    def display_signal_status(
        self,
        signals: Sequence[dict[str, Any]],
    ) -> None:
        """Display current trading signal statuses.

        Parameters
        ----------
        signals : sequence of dict
            Each dict should have ``"instrument"``, ``"action"``,
            ``"confidence"``, ``"size"``, ``"reasoning"``.
        """
        if _HAS_RICH:
            table = Table(
                title="Active Signals",
                show_header=True,
                header_style="bold magenta",
            )
            table.add_column("Instrument", style="white", no_wrap=True)
            table.add_column("Action", justify="center")
            table.add_column("Confidence", justify="right")
            table.add_column("Size", justify="right")
            table.add_column("Reasoning", style="dim")

            for sig in signals:
                action = sig.get("action", "FLAT")
                if action == "LONG":
                    action_style = "[bold green]LONG[/]"
                elif action == "SHORT":
                    action_style = "[bold red]SHORT[/]"
                else:
                    action_style = "[dim]FLAT[/]"

                table.add_row(
                    str(sig.get("instrument", "—")),
                    action_style,
                    f"{sig.get('confidence', 0):.1%}",
                    f"{sig.get('size', 0):.2%}",
                    str(sig.get("reasoning", "—")),
                )

            self._console.print(table)  # type: ignore[union-attr]
        else:
            print("=== Active Signals ===")
            for sig in signals:
                action = sig.get("action", "FLAT")
                print(
                    f"  {sig.get('instrument', '—'):>15s}  "
                    f"{action:>6s}  "
                    f"conf={sig.get('confidence', 0):.1%}  "
                    f"size={sig.get('size', 0):.2%}  "
                    f"  {sig.get('reasoning', '')}"
                )

    def plot_terminal_chart(
        self,
        data: np.ndarray,
        title: str = "Terminal Chart",
        label: str = "value",
    ) -> None:
        """Display a simple line chart in the terminal using plotext.

        Parameters
        ----------
        data : array
            1-D data series to plot.
        title : str
            Chart title.
        label : str
            Y-axis label.
        """
        if not self.use_plotext:
            logger.warning("plotext is not available; skipping terminal chart.")
            return

        data = np.asarray(data, dtype=np.float64).ravel()
        plt_term.clear_figure()
        plt_term.plot(data, label=label)
        plt_term.title(title)
        plt_term.show()
