import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { request } from "../utils/api.js";
import { Spinner } from "../components/StatusChip.jsx";
import { Plus, Trash, PaperPlaneRight, Check, XCircle } from "@phosphor-icons/react";

export default function Integrations() {
  const { t } = useI18n();
  const [tab, setTab] = useState("stock");
  const [subs, setSubs] = useState([]);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [skuInput, setSkuInput] = useState("");
  const [stockInput, setStockInput] = useState("");
  const [warehouseInput, setWarehouseInput] = useState("");
  const [pushResults, setPushResults] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: "", endpoint_url: "", secret: "", events: "" });

  useEffect(() => {
    setLoading(true);
    Promise.all([
      request("/api/v1/integrations/subscriptions").then(r => r || []).catch(() => []),
      request("/api/v1/integrations/logs").then(r => r || []).catch(() => []),
    ]).then(([s, l]) => {
      setSubs(s);
      setLogs(l);
      setLoading(false);
    });
  }, []);

  const handlePushStock = async () => {
    const items = skuInput.split("\n").filter(Boolean).map((line) => {
      const parts = line.split(",");
      return {
        sku: parts[0].trim(),
        stock: parseInt(parts[1] || "0", 10),
        warehouse_id: parseInt(parts[2] || warehouseInput || "0", 10) || null,
      };
    });
    if (items.length === 0) return;
    const params = {};
    const results = await request("/api/v1/integrations/stock/update", {
      method: "POST",
      body: items,
      query: params,
      admin: true,
    }).catch(() => null);
    setPushResults(results);
  };

  const handleAddSub = async () => {
    const body = {
      name: form.name,
      endpoint_url: form.endpoint_url,
      secret: form.secret,
      events: form.events.split(",").map((e) => e.trim()).filter(Boolean),
    };
    const sub = await request("/api/v1/integrations/subscriptions", {
      method: "POST",
      body,
      admin: true,
    }).catch(() => null);
    if (sub) {
      setSubs((prev) => [...prev, sub]);
      setShowForm(false);
      setForm({ name: "", endpoint_url: "", secret: "", events: "" });
    }
  };

  const handleDeleteSub = async (id) => {
    await request(`/api/v1/integrations/subscriptions/${id}`, {
      method: "DELETE",
      admin: true,
    }).catch(() => {});
    setSubs((prev) => prev.filter((s) => s.subscription_id !== id));
  };

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex gap-2 border-b border-[var(--color-outline-variant)] pb-2">
        {["stock", "webhooks", "logs"].map((tKey) => (
          <button
            key={tKey}
            onClick={() => setTab(tKey)}
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
              tab === tKey
                ? "bg-[var(--color-primary)] text-white"
                : "text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container)]"
            }`}
          >
            {tKey === "stock" ? "Загрузка остатков" : tKey === "webhooks" ? "Webhook подписки" : "Логи"}
          </button>
        ))}
      </div>

      {tab === "stock" && (
        <div className="space-y-4">
          <div className="md3-card-elevated p-4 space-y-3">
            <h3 className="text-sm font-semibold text-[var(--color-on-surface)]">
              Отправить остатки на маркетплейсы
            </h3>
            <p className="text-xs text-[var(--color-on-surface-variant)]">
              Формат: каждая строка — <code>sku, количество, warehouse_id</code>
            </p>
            <textarea
              className="w-full px-3 py-2 rounded-lg border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm min-h-[100px] font-mono"
              value={skuInput}
              onChange={(e) => setSkuInput(e.target.value)}
              placeholder="123456, 50, 7543&#10;789012, 25, 7543"
            />
            <div className="flex gap-2 items-center">
              <input
                className="w-32 px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
                value={stockInput}
                onChange={(e) => setStockInput(e.target.value)}
                placeholder="0 (обнулить)"
              />
              <input
                className="w-32 px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
                value={warehouseInput}
                onChange={(e) => setWarehouseInput(e.target.value)}
                placeholder="ID склада WB"
              />
              <button
                onClick={handlePushStock}
                className="flex items-center gap-1 px-4 py-1.5 rounded-full bg-[var(--color-primary)] text-white text-sm font-medium"
              >
                <PaperPlaneRight size={14} /> Отправить
              </button>
            </div>
          </div>

          {pushResults && (
            <div className="space-y-2">
              {pushResults.map((r, i) => (
                <div
                  key={i}
                  className={`md3-card-elevated p-3 flex items-center gap-2 ${
                    r.success ? "border-l-4 border-green-500" : "border-l-4 border-red-500"
                  }`}
                >
                  {r.success ? (
                    <Check size={18} className="text-green-600" />
                  ) : (
                    <XCircle size={18} className="text-red-600" />
                  )}
                  <div>
                    <span className="text-sm font-medium">{r.marketplace.toUpperCase()}</span>
                    {!r.success && r.errors.length > 0 && (
                      <p className="text-xs text-red-600">{r.errors.join("; ")}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {tab === "webhooks" && (
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-sm font-semibold text-[var(--color-on-surface)]">
              Webhook подписки
            </span>
            <button
              onClick={() => setShowForm(!showForm)}
              className="flex items-center gap-1 px-3 py-1 rounded-full bg-[var(--color-primary)] text-white text-sm font-medium"
            >
              <Plus size={14} /> Добавить
            </button>
          </div>

          {showForm && (
            <div className="md3-card-elevated p-3 space-y-2">
              <input
                className="w-full px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                placeholder="Название"
              />
              <input
                className="w-full px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
                value={form.endpoint_url}
                onChange={(e) => setForm((f) => ({ ...f, endpoint_url: e.target.value }))}
                placeholder="https://..."
              />
              <input
                className="w-full px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
                value={form.secret}
                onChange={(e) => setForm((f) => ({ ...f, secret: e.target.value }))}
                placeholder="Secret (опционально)"
              />
              <input
                className="w-full px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
                value={form.events}
                onChange={(e) => setForm((f) => ({ ...f, events: e.target.value }))}
                placeholder="stock.updated, order.created (через запятую)"
              />
              <button
                onClick={handleAddSub}
                className="px-3 py-1 rounded-full bg-[var(--color-primary)] text-white text-sm font-medium"
              >
                <Check size={14} className="inline mr-1" /> Сохранить
              </button>
            </div>
          )}

          {subs.length === 0 ? (
            <p className="text-sm text-[var(--color-on-surface-variant)] py-8 text-center">
              Нет подписок
            </p>
          ) : (
            subs.map((sub) => (
              <div key={sub.subscription_id} className="md3-card-elevated p-3 flex items-start justify-between">
                <div>
                  <p className="text-sm font-medium text-[var(--color-on-surface)]">{sub.name}</p>
                  <p className="text-xs text-[var(--color-on-surface-variant)] font-mono">{sub.endpoint_url}</p>
                  {sub.events?.length > 0 && (
                    <div className="flex gap-1 mt-1">
                      {sub.events.map((ev) => (
                        <span key={ev} className="text-xs px-1.5 py-0.5 rounded bg-[var(--color-surface-container)]">{ev}</span>
                      ))}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => handleDeleteSub(sub.subscription_id)}
                  className="p-1.5 rounded-full hover:bg-[var(--color-surface-container)] text-red-500"
                >
                  <Trash size={14} />
                </button>
              </div>
            ))
          )}
        </div>
      )}

      {tab === "logs" && (
        <div className="space-y-2">
          {logs.length === 0 ? (
            <p className="text-sm text-[var(--color-on-surface-variant)] py-8 text-center">Нет логов</p>
          ) : (
            logs.map((log) => (
              <div
                key={log.log_id}
                className={`md3-card-elevated p-3 border-l-4 ${
                  log.success ? "border-green-500" : "border-red-500"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">{log.event_type}</span>
                  <span className={`text-xs font-semibold ${log.success ? "text-green-600" : "text-red-600"}`}>
                    {log.success ? "OK" : `HTTP ${log.response_status}`}
                  </span>
                </div>
                {log.request_body && (
                  <p className="text-xs text-[var(--color-on-surface-variant)] mt-1 truncate">{log.request_body}</p>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
