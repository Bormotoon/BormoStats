import { useSearchParams } from "react-router-dom";
import { marketplaceName } from "../utils/formats.js";
import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { request, safeCall } from "../utils/api.js";
import { moneyFmt } from "../utils/formats.js";
import { Spinner } from "../components/StatusChip.jsx";
import { ActionLog, CommitRange, DryRunToggle } from "../components/RuleControls.jsx";
import { motion, AnimatePresence } from "motion/react";
import { Megaphone, Sliders, FloppyDisk, Trash } from "@phosphor-icons/react";

export default function Bidder() {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const marketplace = searchParams.get("marketplace") || "";
  const accountId = searchParams.get("accountId") || "";
  const [campaigns, setCampaigns] = useState([]);
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState({});
  const [accountFilter, setAccountFilter] = useState("");
  const [error, setError] = useState("");
  const [bodySku, setBodySku] = useState({});

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    Promise.all([
      safeCall(() => request("/api/v1/bidder/campaigns", { admin: true, signal: controller.signal, query: { marketplace, account_id: accountId } })),
      safeCall(() => request("/api/v1/bidder/rules", { admin: true, signal: controller.signal, query: { marketplace, account_id: accountId } })),
    ]).then(([cRes, rRes]) => {
      if (controller.signal.aborted) return;
      setCampaigns(cRes.ok ? cRes.data : []);
      setRules(rRes.ok ? rRes.data : []);
      setLoading(false);
    });
    return () => controller.abort();
  }, [marketplace, accountId]);

  const campaignKey = (campaign) => `${campaign.marketplace}:${campaign.account_id}:${campaign.campaign_id}`;
  const getRuleForCampaign = (campaign) => rules.find(
    (r) => r.marketplace === campaign.marketplace && r.account_id === campaign.account_id && r.campaign_id === campaign.campaign_id,
  );

  const upsertRule = async (campaign, field, value) => {
    const existing = getRuleForCampaign(campaign);
    const key = campaignKey(campaign);
    if (campaign.marketplace === "ym" && !existing && !bodySku[key]?.trim()) {
      setError("Укажите SKU продавца для правила Яндекс Маркета");
      return;
    }
    const body = {
      campaign_id: campaign.campaign_id,
      marketplace: campaign.marketplace,
      account_id: campaign.account_id,
      target_cpm: existing?.target_cpm ?? (campaign.marketplace === "ym" ? 0.5 : 0),
      max_cpm: existing?.max_cpm ?? 0,
      target_position: existing?.target_position || 0,
      product_id: existing?.product_id || bodySku[campaignKey(campaign)] || campaign.campaign_id,
      [field]: value,
    };

    setSaving((s) => ({ ...s, [key]: true }));

    if (existing) {
      const res = await safeCall(() =>
        request(`/api/v1/bidder/rules/${existing.rule_id}`, {
          method: "PATCH",
          admin: true,
          body: { [field]: value },
        })
      );
      if (res.ok) {
        setRules((prev) =>
          prev.map((r) => (r.rule_id === existing.rule_id ? res.data : r))
        );
      }
      setError(res.ok ? "" : res.error);
    } else {
      const res = await safeCall(() =>
        request("/api/v1/bidder/rules", {
          method: "POST",
          admin: true,
          body,
        })
      );
      if (res.ok) {
        setRules((prev) => [...prev, res.data]);
      }
      setError(res.ok ? "" : res.error);
    }

    setSaving((s) => ({ ...s, [key]: false }));
  };

  const deleteRule = async (ruleId) => {
    const res = await safeCall(() =>
      request(`/api/v1/bidder/rules/${ruleId}`, {
        method: "DELETE",
        admin: true,
      })
    );
    if (res.ok) {
      setRules((prev) => prev.filter((r) => r.rule_id !== ruleId));
    }
  };

  if (loading) return <Spinner />;

  const filtered = accountFilter
    ? campaigns.filter((c) => c.account_id === accountFilter)
    : campaigns;

  const accounts = [...new Set(campaigns.map((c) => c.account_id))];

  return (
    <div className="space-y-4">
      {error && <div role="alert" className="md3-card-elevated p-3 border-l-4 border-red-500 text-sm text-red-700">{error}</div>}
      {accounts.length > 1 && (
        <div className="flex gap-2">
          <select
            value={accountFilter}
            onChange={(e) => setAccountFilter(e.target.value)}
            className="px-3 py-1.5 rounded-lg border border-[var(--color-outline-variant)] bg-[var(--color-surface)] text-sm"
          >
            <option value="">{t("filters.all")}</option>
            {accounts.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
      )}

      {filtered.length === 0 && (
        <div className="text-center py-12 text-[var(--color-on-surface-variant)]">
          <Megaphone size={40} className="mx-auto mb-3 opacity-40" />
          <p className="font-semibold">Нет рекламных кампаний</p>
          <p className="text-sm mt-1">Кампании появятся после синхронизации с API маркетплейсов</p>
        </div>
      )}

      <div className="grid gap-3">
        {filtered.map((campaign) => {
          const rule = getRuleForCampaign(campaign);
          const isSaving = saving[campaignKey(campaign)];

          return (
            <motion.div
              key={campaignKey(campaign)}
              layout
              className="md3-card-elevated p-4"
            >
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="font-semibold text-sm text-[var(--color-on-surface)]">
                    {campaign.title}
                  </h3>
                  <p className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">
                    {marketplaceName(campaign.marketplace)} · {campaign.account_id} · {campaign.campaign_id}
                  </p>
                </div>
                <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                  campaign.status === "active" || campaign.status === "running"
                    ? "bg-green-100 text-green-700"
                    : "bg-[var(--color-surface-container)] text-[var(--color-on-surface-variant)]"
                }`}>
                  {campaign.status}
                </span>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="flex items-center justify-between text-xs font-semibold text-[var(--color-on-surface-variant)] mb-1">
                    <span>{campaign.marketplace === "ym" ? "Ставка буста, %" : "Target CPM"}</span>
                    <span className="font-mono">{campaign.marketplace === "ym" ? `${(rule?.target_cpm ?? 0).toFixed(2)} %` : moneyFmt(rule?.target_cpm ?? 0)}</span>
                  </label>
                  <CommitRange
                    min={campaign.marketplace === "ym" ? 0.5 : 0}
                    max={campaign.marketplace === "ym" ? 99.99 : 500}
                    step={campaign.marketplace === "ym" ? 0.01 : 5}
                    value={rule?.target_cpm ?? 0}
                    onCommit={(v) => upsertRule(campaign, "target_cpm", v)}
                    className="w-full accent-[var(--color-primary)]"
                  />
                  <div className="flex justify-between text-xs text-[var(--color-on-surface-variant)] mt-0.5">
                    <span>{campaign.marketplace === "ym" ? "0,5 %" : "0"}</span>
                    <span>{campaign.marketplace === "ym" ? "99,99 %" : "500 ₽"}</span>
                  </div>
                </div>

                <div>
                  <label className="flex items-center justify-between text-xs font-semibold text-[var(--color-on-surface-variant)] mb-1">
                    <span>{campaign.marketplace === "ym" ? "Максимальная ставка, %" : "Max CPM"}</span>
                    <span className="font-mono">{campaign.marketplace === "ym" ? `${(rule?.max_cpm ?? 0).toFixed(2)} %` : moneyFmt(rule?.max_cpm ?? 0)}</span>
                  </label>
                  <CommitRange
                    min={0}
                    max={campaign.marketplace === "ym" ? 99.99 : 1000}
                    step={campaign.marketplace === "ym" ? 0.01 : 10}
                    value={rule?.max_cpm ?? 0}
                    onCommit={(v) => upsertRule(campaign, "max_cpm", v)}
                    className="w-full accent-[var(--color-warning)]"
                  />
                  <div className="flex justify-between text-xs text-[var(--color-on-surface-variant)] mt-0.5">
                    <span>0</span>
                    <span>{campaign.marketplace === "ym" ? "99,99 %" : "1 000 ₽"}</span>
                  </div>
                </div>

                {campaign.marketplace !== "ym" && <div>
                  <label className="flex items-center justify-between text-xs font-semibold text-[var(--color-on-surface-variant)] mb-1">
                    <span>Target Position</span>
                    <span className="font-mono">{rule?.target_position ?? 0}</span>
                  </label>
                  <CommitRange
                    min={0}
                    max={100}
                    step={1}
                    value={rule?.target_position ?? 0}
                    onCommit={(v) => upsertRule(campaign, "target_position", v)}
                    className="w-full accent-[var(--color-primary)]"
                  />
                  <div className="flex justify-between text-xs text-[var(--color-on-surface-variant)] mt-0.5">
                    <span>0</span>
                    <span>100</span>
                  </div>
                </div>}

                {campaign.marketplace === "ym" && !rule && <label className="flex flex-col gap-1 text-xs font-semibold text-[var(--color-on-surface-variant)]">
                  SKU продавца
                  <input type="text" maxLength={128} value={bodySku[campaignKey(campaign)] ?? ""} onChange={(e) => setBodySku((s) => ({ ...s, [campaignKey(campaign)]: e.target.value }))} className="px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] font-mono" />
                </label>}


                <div className="flex flex-col gap-2">
                  {campaign.marketplace !== "ym" && <label className="text-xs font-semibold text-[var(--color-on-surface-variant)]">
                    Артикул WB (nm_id) для ставки
                    <input
                      type="text"
                      inputMode="numeric"
                      defaultValue={rule?.product_id ?? ""}
                      onBlur={(e) => {
                        if (!rule && e.target.value) upsertRule(campaign, "product_id", e.target.value.trim());
                      }}
                      disabled={!!rule}
                      className="mt-1 w-full px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm font-mono"
                    />
                  </label>}
                  <DryRunToggle rule={rule} disabled={isSaving} onChange={(v) => upsertRule(campaign, "dry_run", v)} />
                </div>

                <div className="flex items-end justify-end gap-2">
                  {isSaving && <FloppyDisk size={16} className="animate-spin text-[var(--color-primary)]" />}
                  {rule && (
                    <button
                      onClick={() => deleteRule(rule.rule_id)}
                      className="p-2 rounded-lg hover:bg-red-50 text-red-500 transition-colors"
                      title="Удалить правило"
                    >
                      <Trash size={16} />
                    </button>
                  )}
                </div>
              </div>

              {campaign.current_cpm !== null && campaign.current_cpm !== undefined && (
                <div className="mt-3 pt-3 border-t border-[var(--color-outline-variant)] text-xs text-[var(--color-on-surface-variant)]">
                  {campaign.marketplace === "ym" ? "Текущая ставка" : "Current CPM"}: <span className="font-mono font-semibold">{campaign.marketplace === "ym" ? `${campaign.current_cpm.toFixed(2)} %` : moneyFmt(campaign.current_cpm)}</span>
                </div>
              )}
            </motion.div>
          );
        })}
      </div>

      <ActionLog source="bidder" />
    </div>
  );
}
