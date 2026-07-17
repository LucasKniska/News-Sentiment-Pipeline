CREATE TABLE IF NOT EXISTS articles (
    id BIGINT PRIMARY KEY,
    headline TEXT NOT NULL,
    text TEXT,
    url TEXT,
    datetime TIMESTAMPTZ NOT NULL,
    tickers TEXT[] NOT NULL DEFAULT '{}',
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
