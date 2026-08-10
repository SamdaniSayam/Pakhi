import pakhi.viz.dashboard as db
from pakhi.viz.dashboard import TerminalDashboard


def test_dashboard_forecast_table_rich(monkeypatch, capsys):
    dash = TerminalDashboard()

    # Force _HAS_RICH to True
    monkeypatch.setattr(db, "_HAS_RICH", True)

    # We need to mock Console so it doesn't actually print/fail
    class MockConsole:
        def print(self, table):
            pass

    dash._console = MockConsole()

    dash.display_forecast_table(
        [
            {
                "date": "2023-01-01",
                "temp_high": 10,
                "temp_low": 5,
                "wind": 15,
                "precip_prob": 0.5,
                "description": "Rain",
            }
        ]
    )


def test_dashboard_signal_status_rich(monkeypatch):
    dash = TerminalDashboard()
    monkeypatch.setattr(db, "_HAS_RICH", True)

    class MockConsole:
        def print(self, table):
            pass

    dash._console = MockConsole()

    dash.display_signal_status(
        [
            {
                "instrument": "NG",
                "action": "LONG",
                "confidence": 0.8,
                "size": 1.0,
                "reasoning": "Cold",
            },
            {
                "instrument": "CL",
                "action": "SHORT",
                "confidence": 0.8,
                "size": 1.0,
                "reasoning": "Warm",
            },
            {
                "instrument": "ZC",
                "action": "FLAT",
                "confidence": 0.8,
                "size": 1.0,
                "reasoning": "Neutral",
            },
        ]
    )
