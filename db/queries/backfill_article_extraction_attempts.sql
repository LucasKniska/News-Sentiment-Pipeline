-- One-time retroactive backfill for article_extraction_attempts.
--
-- article_extraction_attempts was created 2026-08-17 with no data migration, so
-- every (article_id, ticker) pair successfully extracted BEFORE that date has no
-- row in it. fetch_new_articles treats an absent attempts row as "never tried",
-- so every one of those pairs looks brand new on every single run forever - even
-- though article_sentiment already has real data for them and they're already
-- folded into an existing signals row. Discovered 2026-08-18: of 109 (article,
-- ticker) pairs a local backfill run attempted in one sitting, 94 (86%) already
-- had a pre-existing article_sentiment row from 2026-08-16 - meaning the vast
-- majority of that run's scarce Groq quota was burned re-extracting already-done
-- work for zero net new signals, not making forward progress into unprocessed
-- dates. 1,159 pairs total were affected account-wide.
--
-- Backfills attempted_at from article_sentiment's own timestamp (when the
-- original extraction actually happened) rather than now(), so this doesn't
-- misrepresent when the work was done. ON CONFLICT DO NOTHING since a handful
-- of pairs may have already been re-attempted (and thus already recorded) since
-- the table was created.
INSERT INTO article_extraction_attempts (article_id, ticker, attempted_at)
SELECT article_id, ticker, timestamp
FROM article_sentiment
ON CONFLICT (article_id, ticker) DO NOTHING;
