from datetime import date, timedelta

import yfinance as yf


def fetch_price_history(ticker: str, start_date: date, end_date: date):
    """Daily OHLC history for one ticker, [start_date, end_date] inclusive.

    yfinance's `end` is exclusive, so it's bumped by a day here to make this
    function's own range inclusive on both ends.
    """
    return yf.Ticker(ticker).history(start=start_date, end=end_date + timedelta(days=1), interval="1d")
