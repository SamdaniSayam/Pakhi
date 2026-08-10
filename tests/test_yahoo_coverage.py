import pandas as pd
import pytest

from pakhi.src.yahoo import YahooFuturesConnector


def test_yahoo_spread_missing_long_leg(monkeypatch):
    yf = YahooFuturesConnector(tickers={"A": "A", "B": "B"})

    # mock history to return only B
    def mock_history(*args, **kwargs):
        return {"B": pd.DataFrame({"Close": [1]})}

    monkeypatch.setattr(yf, "history", mock_history)
    with pytest.raises(KeyError, match="A not in fetched data"):
        yf.spread("A", "B")
