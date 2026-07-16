import os
from datetime import date

import finnhub


def get_client() -> finnhub.Client:
    return finnhub.Client(api_key=os.environ["FINNHUB_API_KEY"])


def fetch_company_news(client: finnhub.Client, ticker: str, from_date: date, to_date: date) -> list[dict]:
    return client.company_news(ticker, _from=from_date.isoformat(), to=to_date.isoformat())
