INSERT INTO mrt_ad_performance_daily
SELECT
    day,
    marketplace,
    account_id,
    campaign_id,
    sum(impressions) AS impressions,
    sum(clicks) AS clicks,
    sum(cost) AS cost_rub,
    sum(orders) AS orders,
    sum(revenue) AS revenue_rub,
    multiIf(
        revenue_rub > 0,
        cost_rub / revenue_rub * 100,
        999
    ) AS drr_pct,
    multiIf(
        cost_rub > 0,
        revenue_rub / cost_rub,
        0
    ) AS roas,
    multiIf(
        revenue_rub > 0,
        cost_rub / revenue_rub * 100,
        0
    ) AS acos_pct,
    multiIf(
        clicks > 0,
        cost_rub / clicks,
        0
    ) AS cpc_rub,
    multiIf(
        impressions > 0,
        cost_rub / impressions * 1000,
        0
    ) AS cpm_rub,
    multiIf(
        clicks > 0,
        orders / clicks * 100,
        0
    ) AS conversion_pct
FROM stg_ads_daily FINAL
WHERE day >= today() - %(days)s
GROUP BY day, marketplace, account_id, campaign_id
