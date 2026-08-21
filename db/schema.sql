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

CREATE TABLE IF NOT EXISTS article_sentiment (
    article_id BIGINT NOT NULL REFERENCES articles(id),
    ticker TEXT NOT NULL,
    sentiment NUMERIC NOT NULL CHECK (sentiment BETWEEN -1 AND 1),
    involvement NUMERIC NOT NULL CHECK (involvement BETWEEN 0 AND 1),
    event_type TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (article_id, ticker)
);

-- Records that (article_id, ticker) was fed to the extraction chain and got a
-- response, regardless of what that response was - including the model
-- correctly returning "no entry for this ticker" (paywalled/blocked text, or
-- an omitted ticker). article_sentiment only holds rows with a real
-- sentiment value, so before this table existed those "correctly excluded"
-- pairs left no record anywhere: fetch_new_articles' only way to know an
-- article/ticker was already handled was checking signals.article_ids, which
-- an empty-result extraction never entered. That made such pairs look "new"
-- forever, and run_backfill's per-date retry loop would burn its two
-- attempts and its whole time budget re-attempting the same already-settled
-- articles every single morning instead of advancing into unprocessed dates
-- (see CLAUDE.md's 2026-08-17 note under sentiment_analysis/run.py).
CREATE TABLE IF NOT EXISTS article_extraction_attempts (
    article_id BIGINT NOT NULL REFERENCES articles(id),
    ticker TEXT NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (article_id, ticker)
);

CREATE TABLE IF NOT EXISTS daily_prices (
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    close NUMERIC NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, date)
);
