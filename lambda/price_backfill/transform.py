import pandas as pd


def to_price_rows(ticker: str, history: pd.DataFrame) -> list[dict]:
    """Maps a yfinance history DataFrame (index = tz-aware daily Timestamp,
    columns include "Close") to daily_prices row dicts."""
    return [
        {"ticker": ticker, "date": index.date(), "close": float(row["Close"])}
        for index, row in history.iterrows()
    ]
