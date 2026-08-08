SELECT ticker, date, close
FROM daily_prices
WHERE ticker = 'AAPL'
ORDER BY date DESC
LIMIT 5;
