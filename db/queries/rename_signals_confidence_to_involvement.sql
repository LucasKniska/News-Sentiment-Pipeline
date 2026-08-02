ALTER TABLE signals RENAME COLUMN confidence TO involvement;
ALTER TABLE signals RENAME CONSTRAINT signals_confidence_check TO signals_involvement_check;
