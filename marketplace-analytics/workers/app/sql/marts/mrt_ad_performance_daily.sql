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
        sum(revenue) > 0,
        sum(cost) / sum(revenue) * 100,
        999
    ) AS drr_pct,
    multiIf(
        sum(cost) > 0,
        sum(revenue) / sum(cost),
        0
    ) AS roas,
    multiIf(
        sum(revenue) > 0,
        sum(cost) / sum(revenue) * 100,
        0
    ) AS acos_pct,
    multiIf(
        sum(clicks) > 0,
        sum(cost) / sum(clicks),
        0
    ) AS cpc_rub,
    multiIf(
        sum(impressions) > 0,
        sum(cost) / sum(impressions) * 1000,
        0
    ) AS cpm_rub,
    multiIf(
        sum(clicks) > 0,
        sum(orders) / sum(clicks) * 100,
        0
    ) AS conversion_pct
FROM stg_ads_daily FINAL
WHERE day >= today() - %(days)s
GROUP BY day, marketplace, account_id, campaign_id
