import { useState, useEffect } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { request } from "../utils/api.js";
import { Spinner } from "../components/StatusChip.jsx";
import { Plus, Trash, PaperPlaneRight, Check, XCircle, ArrowsClockwise, Lightning, Copy } from "@phosphor-icons/react";

const DELIVERY_STYLES = {
  delivered: "border-green-500",
  retrying: "border-amber-500",
  dead_letter: "border-red-500",
  blocked: "border-red-500",
  skipped: "border-gray-400",
};

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
  const [form, setForm] = useState({ name: "", endpoint_url: "", events: [] });
  const [eventTypes, setEventTypes] = useState([]);
  const [revealedSecret, setRevealedSecret] = useState(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    Promise.all([
      request("/api/v1/integrations/subscriptions").then(r => r || []).catch(() => []),
      request("/api/v1/integrations/logs").then(r => r || []).catch(() => []),
      request("/api/v1/integrations/events").then(r => r || []).catch(() => []),
    ]).then(([s, l, e]) => {
      setSubs(s);
      setLogs(l);
      setEventTypes(e);
      setLoading(false);
    });
  }, []);

  const run = async (fn) => {
    setError("");
    setNotice("");
    try {
      return await fn();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
    }
  };

  const toggleEvent = (eventType) => {
    setForm((f) => ({
      ...f,
      events: f.events.includes(eventType)
        ? f.events.filter((e) => e !== eventType)
        : [...f.events, eventType],
    }));
  };

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
    const results = await run(() => request("/api/v1/integrations/stock/update", {
      method: "POST",
      body: items,
      query: params,
      admin: true,
    }));
    setPushResults(results);
  };

  const handleAddSub = async () => {
    const created = await run(() => request("/api/v1/integrations/subscriptions", {
      method: "POST",
      body: { name: form.name, endpoint_url: form.endpoint_url, events: form.events },
      admin: true,
    }));
    if (created) {
      const { secret, ...sub } = created;
      setSubs((prev) => [sub, ...prev]);
      setRevealedSecret({ name: sub.name, secret });
      setShowForm(false);
      setForm({ name: "", endpoint_url: "", events: [] });
    }
  };

  const handleRotate = async (sub) => {
    const rotated = await run(() => request(`/api/v1/integrations/subscriptions/${sub.subscription_id}/rotate-secret`, {
      method: "POST",
      admin: true,
    }));
    if (rotated) setRevealedSecret({ name: sub.name, secret: rotated.secret });
  };

  const handleTest = async (sub) => {
    const result = await run(() => request(`/api/v1/integrations/subscriptions/${sub.subscription_id}/test`, {
      method: "POST",
      admin: true,
    }));
    if (result) setNotice(`Тестовое событие ${result.event_id} поставлено в очередь`);
  };

  const handleDeleteSub = async (id) => {
    const ok = await run(() => request(`/api/v1/integrations/subscriptions/${id}`, {
      method: "DELETE",
      admin: true,
    }));
    if (ok) setSubs((prev) => prev.filter((s) => s.subscription_id !== id));
  };

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      {error && (
        <div role="alert" className="md3-card-elevated p-3 border-l-4 border-red-500 text-sm text-red-700">{error}</div>
      )}
      {notice && (
        <div role="status" className="md3-card-elevated p-3 border-l-4 border-green-500 text-sm">{notice}</div>
      )}
      {revealedSecret && (
        <div role="alert" className="md3-card-elevated p-3 border-l-4 border-amber-500 space-y-2">
          <p className="text-sm font-semibold">
            Секрет подписи для «{revealedSecret.name}» — показывается один раз. Сохраните его у получателя.
          </p>
          <div className="flex items-center gap-2">
            <code className="text-xs break-all bg-[var(--color-surface-container)] px-2 py-1 rounded">{revealedSecret.secret}</code>
            <button
              type="button"
              aria-label="Скопировать секрет"
              onClick={() => navigator.clipboard?.writeText(revealedSecret.secret)}
              className="p-1.5 rounded-full hover:bg-[var(--color-surface-container)]"
            >
              <Copy size={14} />
            </button>
          </div>
          <button type="button" onClick={() => setRevealedSecret(null)} className="text-xs underline">Я сохранил секрет</button>
        </div>
      )}
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
              <fieldset className="flex flex-wrap gap-3">
                <legend className="text-xs text-[var(--color-on-surface-variant)] mb-1">События</legend>
                {eventTypes.map((eventType) => (
                  <label key={eventType} className="flex items-center gap-1 text-xs">
                    <input
                      type="checkbox"
                      checked={form.events.includes(eventType)}
                      onChange={() => toggleEvent(eventType)}
                    />
                    <span className="font-mono">{eventType}</span>
                  </label>
                ))}
              </fieldset>
              <p className="text-xs text-[var(--color-on-surface-variant)]">
                Только HTTPS-адреса в интернете. Секрет подписи будет сгенерирован и показан один раз.
              </p>
              <button
                onClick={handleAddSub}
                disabled={!form.name || !form.endpoint_url || form.events.length === 0}
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
                <div className="flex gap-1">
                  <button
                    onClick={() => handleTest(sub)}
                    aria-label="Отправить тестовое событие"
                    title="Отправить тестовое событие"
                    className="p-1.5 rounded-full hover:bg-[var(--color-surface-container)]"
                  >
                    <Lightning size={14} />
                  </button>
                  <button
                    onClick={() => handleRotate(sub)}
                    aria-label="Сменить секрет"
                    title="Сменить секрет"
                    className="p-1.5 rounded-full hover:bg-[var(--color-surface-container)]"
                  >
                    <ArrowsClockwise size={14} />
                  </button>
                  <button
                    onClick={() => handleDeleteSub(sub.subscription_id)}
                    aria-label="Удалить подписку"
                    title="Удалить подписку"
                    className="p-1.5 rounded-full hover:bg-[var(--color-surface-container)] text-red-500"
                  >
                    <Trash size={14} />
                  </button>
                </div>
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
                  DELIVERY_STYLES[log.status] || (log.success ? "border-green-500" : "border-red-500")
                }`}
              >
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-xs font-mono text-[var(--color-on-surface-variant)]">{log.event_type}</span>
                  <span className={`text-xs font-semibold ${log.success ? "text-green-600" : "text-red-600"}`}>
                    {log.status || (log.success ? "OK" : "failed")}
                    {log.response_status ? ` · HTTP ${log.response_status}` : ""}
                  </span>
                  <span className="text-xs text-[var(--color-on-surface-variant)]">попытка {log.attempt}</span>
                  {log.next_retry_at && (
                    <span className="text-xs text-[var(--color-on-surface-variant)]">повтор: {new Date(log.next_retry_at).toLocaleString()}</span>
                  )}
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
