CREATE TABLE IF NOT EXISTS article_extraction_attempts (
    article_id BIGINT NOT NULL REFERENCES articles(id),
    ticker TEXT NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (article_id, ticker)
);
