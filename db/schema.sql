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
    confidence NUMERIC NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    article_ids BIGINT[] NOT NULL CHECK (array_length(article_ids, 1) > 0)
);
