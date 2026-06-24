SELECT day, sum(revenue) revenue, sum(qty) qty, sum(returns_qty) returns
FROM mrt_sales_daily
WHERE day BETWEEN {{from}} AND {{to}}
GROUP BY day
ORDER BY day;
