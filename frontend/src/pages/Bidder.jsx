import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { request, safeCall } from "../utils/api.js";
import { moneyFmt } from "../utils/formats.js";
import { Spinner } from "../components/StatusChip.jsx";
import { motion, AnimatePresence } from "motion/react";
import { Megaphone, Sliders, FloppyDisk, Trash } from "@phosphor-icons/react";

export default function Bidder() {
  const { t } = useI18n();
  const [campaigns, setCampaigns] = useState([]);
  const [rules, setRules] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState({});
  const [accountFilter, setAccountFilter] = useState("");

  useEffect(() => {
    setLoading(true);
    Promise.all([
      safeCall(() => request("/api/v1/bidder/campaigns", { admin: true })),
      safeCall(() => request("/api/v1/bidder/rules", { admin: true })),
    ]).then(([cRes, rRes]) => {
      setCampaigns(cRes.ok ? cRes.data : []);
      setRules(rRes.ok ? rRes.data : []);
      setLoading(false);
    });
  }, []);

  const getRuleForCampaign = (campaignId) =>
    rules.find((r) => r.campaign_id === campaignId);

  const upsertRule = async (campaign, field, value) => {
    const existing = getRuleForCampaign(campaign.campaign_id);
    const body = {
      campaign_id: campaign.campaign_id,
      marketplace: campaign.marketplace,
      account_id: campaign.account_id,
      [field]: value,
      target_cpm: existing?.target_cpm || 0,
      max_cpm: existing?.max_cpm || 0,
      target_position: existing?.target_position || 0,
    };

    setSaving((s) => ({ ...s, [campaign.campaign_id]: true }));

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
    }

    setSaving((s) => ({ ...s, [campaign.campaign_id]: false }));
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
          const rule = getRuleForCampaign(campaign.campaign_id);
          const isSaving = saving[campaign.campaign_id];

          return (
            <motion.div
              key={campaign.campaign_id}
              layout
              className="md3-card-elevated p-4"
            >
              <div className="flex items-start justify-between mb-3">
                <div>
                  <h3 className="font-semibold text-sm text-[var(--color-on-surface)]">
                    {campaign.title}
                  </h3>
                  <p className="text-xs text-[var(--color-on-surface-variant)] mt-0.5">
                    {campaign.marketplace === "wb" ? "WB" : "Ozon"} · {campaign.account_id} · {campaign.campaign_id}
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
                    <span>Target CPM</span>
                    <span className="font-mono">{moneyFmt(rule?.target_cpm ?? 0)}</span>
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={500}
                    step={5}
                    value={rule?.target_cpm ?? 0}
                    onChange={(e) => upsertRule(campaign, "target_cpm", Number(e.target.value))}
                    className="w-full accent-[var(--color-primary)]"
                  />
                  <div className="flex justify-between text-xs text-[var(--color-on-surface-variant)] mt-0.5">
                    <span>0</span>
                    <span>500 ₽</span>
                  </div>
                </div>

                <div>
                  <label className="flex items-center justify-between text-xs font-semibold text-[var(--color-on-surface-variant)] mb-1">
                    <span>Max CPM</span>
                    <span className="font-mono">{moneyFmt(rule?.max_cpm ?? 0)}</span>
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={1000}
                    step={10}
                    value={rule?.max_cpm ?? 0}
                    onChange={(e) => upsertRule(campaign, "max_cpm", Number(e.target.value))}
                    className="w-full accent-[var(--color-warning)]"
                  />
                  <div className="flex justify-between text-xs text-[var(--color-on-surface-variant)] mt-0.5">
                    <span>0</span>
                    <span>1 000 ₽</span>
                  </div>
                </div>

                <div>
                  <label className="flex items-center justify-between text-xs font-semibold text-[var(--color-on-surface-variant)] mb-1">
                    <span>Target Position</span>
                    <span className="font-mono">{rule?.target_position ?? 0}</span>
                  </label>
                  <input
                    type="range"
                    min={0}
                    max={100}
                    step={1}
                    value={rule?.target_position ?? 0}
                    onChange={(e) => upsertRule(campaign, "target_position", Number(e.target.value))}
                    className="w-full accent-[var(--color-primary)]"
                  />
                  <div className="flex justify-between text-xs text-[var(--color-on-surface-variant)] mt-0.5">
                    <span>0</span>
                    <span>100</span>
                  </div>
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
                  Current CPM: <span className="font-mono font-semibold">{moneyFmt(campaign.current_cpm)}</span>
                </div>
              )}
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}
