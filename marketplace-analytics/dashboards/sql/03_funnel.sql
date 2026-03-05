SELECT day, product_id, views, adds_to_cart, orders, cr_order, cr_cart
FROM mrt_funnel_daily
WHERE day BETWEEN {{from}} AND {{to}}
ORDER BY day, product_id;
