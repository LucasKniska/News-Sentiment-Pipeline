CREATE TABLE IF NOT EXISTS articles (
    id BIGINT PRIMARY KEY,
    headline TEXT NOT NULL,
    text TEXT,
    url TEXT,
    datetime TIMESTAMPTZ NOT NULL,
    tickers TEXT[] NOT NULL DEFAULT '{}',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS signals (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT,
    sentiment NUMERIC NOT NULL CHECK (sentiment BETWEEN -1 AND 1),
    involvement NUMERIC NOT NULL CHECK (involvement BETWEEN 0 AND 1),
    article_ids BIGINT[] NOT NULL CHECK (array_length(article_ids, 1) > 0)
);

-- One row per (article, tracked ticker) the extraction chain (chain.py) produced a
-- TickerSentiment for - the raw per-article values that feed into signals' blended
-- combine step, kept here for traceability/debugging independent of that blend.
-- A real FK is possible here (unlike signals.article_ids, an array column Postgres
-- can't FK into) since article_id is a single scalar per row.
CREATE TABLE IF NOT EXISTS article_sentiment (
    article_id BIGINT NOT NULL REFERENCES articles(id),
    ticker TEXT NOT NULL,
    sentiment NUMERIC NOT NULL CHECK (sentiment BETWEEN -1 AND 1),
    involvement NUMERIC NOT NULL CHECK (involvement BETWEEN 0 AND 1),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (article_id, ticker)
);

-- One row per ticker per trading day's close, sourced from Finnhub's /quote
-- endpoint during news_ingestion's per-ticker run (see handler.py). Kept
-- separate from the future daily_returns table (Week 5-6 backtest output,
-- which joins this against signals) - this is just the raw price series.
CREATE TABLE IF NOT EXISTS daily_prices (
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    close NUMERIC NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, date)
);
