SELECT
  s.marketplace,
  s.account_id,
  s.revenue_30d,
  s.qty_30d,
  s.returns_30d,
  ifNull(a.cost_30d, 0) AS cost_30d,
  ifNull(a.acos_30d, 0) AS acos_30d
FROM v_kpi_sales_30d s
LEFT JOIN v_kpi_ads_30d a USING (marketplace, account_id)
WHERE (%(marketplace)s = '' OR s.marketplace = %(marketplace)s)
  AND (%(account_id)s = '' OR s.account_id = %(account_id)s)
ORDER BY s.marketplace, s.account_id
LIMIT %(limit)s
OFFSET %(offset)s
