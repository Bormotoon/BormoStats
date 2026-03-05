SELECT product_id, sum(revenue) revenue, sum(qty) qty
FROM mrt_sales_daily
WHERE day >= today() - 30
GROUP BY product_id
ORDER BY revenue DESC
LIMIT 50;
