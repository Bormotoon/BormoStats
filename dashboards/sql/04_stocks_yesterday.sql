SELECT marketplace, product_id, sum(stock_end) stock_end
FROM mrt_stock_daily
WHERE day = today() - 1
GROUP BY marketplace, product_id
ORDER BY stock_end ASC;
