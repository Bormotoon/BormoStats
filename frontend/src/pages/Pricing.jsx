import { useState, useEffect, useMemo } from "react";
import { request, safeCall } from "../utils/api.js";
import { moneyFmt, numberFmt, formatAsOf } from "../utils/formats.js";
import { Spinner } from "../components/StatusChip.jsx";
import { Trash, UploadSimple, Info } from "@phosphor-icons/react";

const TABS = [
  { id: "breakdown", label: "Разбор цены" },
  { id: "compare", label: "Сравнение цен" },
  { id: "costs", label: "Себестоимость" },
];
const MARKETPLACES = [
  { id: "wb", label: "WB" },
  { id: "ozon", label: "Ozon" },
];
const MODES = [
  { id: "buyer_price", label: "цену для покупателя" },
  { id: "seller_price", label: "цену со скидкой продавца" },
];
const MODE_SHORT = { buyer_price: "для покупателя", seller_price: "со скидкой продавца", margin: "по марже" };
// the repricer keeps a buyer price on a discount measured on 3+ of the card's sales, or on WB on
// the account's median over 10+ orders (workers/app/tasks/repricer.py)
function discountUsable(row) {
  if (row.mp_discount_scope === "product") return row.mp_discount_samples >= 3;
  return row.mp_discount_scope === "account" && row.marketplace === "wb" && row.mp_discount_samples >= 10;
}
// a kept price this far from the desired one is highlighted
const GAP_WARN_PCT = 1;

const inputClass =
  "w-24 px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm font-mono text-right";
const thClass =
  "text-left px-3 py-2.5 text-[11px] font-semibold text-[var(--color-on-surface-variant)] tracking-wide uppercase sticky top-0 bg-[var(--color-surface-container)] z-10 align-bottom";
const tdClass = "px-3 py-2 text-[var(--color-on-surface)] align-top";

function pct(value, digits = 1) {
  return value === null || value === undefined ? null : `${numberFmt(value, digits)}%`;
}

function Dash() {
  return <span className="text-[var(--color-on-surface-variant)]">&mdash;</span>;
}

function Money({ value, className = "" }) {
  if (value === null || value === undefined) return <Dash />;
  return <span className={`font-mono whitespace-nowrap ${className}`}>{moneyFmt(value)}</span>;
}

function TabButton({ active, onClick, children }) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
        active
          ? "bg-[var(--color-primary)] text-white"
          : "text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container)]"
      }`}
    >
      {children}
    </button>
  );
}

function parsePrice(text) {
  const value = Number(String(text).replace(/\s/g, "").replace(",", "."));
  return Number.isFinite(value) && value > 0 ? value : null;
}

/** A number cell edited in place; saves on Enter or blur when the value changed. */
function EditableNumber({ value, onSave, label }) {
  const [draft, setDraft] = useState(value ?? "");
  const [state, setState] = useState("idle");

  useEffect(() => setDraft(value ?? ""), [value]);

  const commit = async () => {
    const parsed = parsePrice(draft);
    if (parsed === null) {
      setDraft(value ?? "");
      return;
    }
    if (parsed === value) return;
    setState("saving");
    const ok = await onSave(parsed);
    setState(ok ? "idle" : "error");
    if (!ok) setDraft(value ?? "");
  };

  return (
    <input
      aria-label={label}
      inputMode="decimal"
      className={`${inputClass} ${state === "error" ? "border-red-500" : ""} ${state === "saving" ? "opacity-60" : ""}`}
      value={draft}
      placeholder="—"
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        if (e.key === "Escape") {
          setDraft(value ?? "");
          e.currentTarget.blur();
        }
      }}
    />
  );
}

/** Margin recomputed in the browser after a cost change; the mart catches up on its next run. */
function withCost(row, cost) {
  const margin = row.seller_price - row.fees_rub - cost;
  const share = 1 - row.commission_pct / 100;
  return {
    ...row,
    cost_price: cost,
    margin_rub: Math.round(margin * 100) / 100,
    margin_pct: row.seller_price > 0 ? Math.round((margin / row.seller_price) * 10000) / 100 : null,
    breakeven_price: share > 0 ? Math.round(((cost + row.acquiring_rub + row.logistics_rub) / share) * 100) / 100 : null,
  };
}

function DiscountCell({ row }) {
  if (row.mp_discount_pct === null || row.mp_discount_pct === undefined) {
    return <span title="Нет продаж за последние 30–60 дней, скидку не на чем измерить"><Dash /></span>;
  }
  const estimate = row.mp_discount_scope !== "product";
  const title = estimate
    ? `Оценка: у товара мало недавних продаж, взята медиана по кабинету (${row.mp_discount_samples} продаж)`
    : `Медиана по ${row.mp_discount_samples} последним продажам товара`;
  return (
    <span title={title} className={`font-mono whitespace-nowrap ${estimate ? "text-[var(--color-on-surface-variant)]" : ""}`}>
      {estimate ? "≈ " : ""}
      {pct(row.mp_discount_pct)}
    </span>
  );
}

function TargetCell({ row, mode, onSave }) {
  const gap = row.target_gap_pct;
  const off = gap !== null && gap !== undefined && Math.abs(gap) > GAP_WARN_PCT;
  return (
    <div className="space-y-1">
      <EditableNumber value={row.target_price} onSave={(v) => onSave(row, v, mode)} label={`Желаемая цена ${row.offer_id}`} />
      {row.rule_id && (
        <div className="text-[11px] leading-tight text-[var(--color-on-surface-variant)]">
          {MODE_SHORT[row.mode] || row.mode}
          {off && (
            <span className="block text-amber-700 dark:text-amber-400 font-medium">
              сейчас {gap > 0 ? "+" : ""}
              {numberFmt(gap, 1)}%
            </span>
          )}
          <span className="block">
            {!row.rule_is_active ? "правило выключено" : row.rule_dry_run ? "симуляция" : "удерживается"}
          </span>
          {row.mode === "buyer_price" && !discountUsable(row) && (
            <span className="block" title="Скидку маркетплейса нужно измерить хотя бы на 3 продажах этого товара">
              ждёт продаж для замера скидки
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function FeesCell({ row }) {
  const parts = [`комиссия ${pct(row.commission_pct)} = ${moneyFmt(row.commission_rub)}`];
  if (row.acquiring_rub) parts.push(`эквайринг ${moneyFmt(row.acquiring_rub)}`);
  parts.push(`логистика ${moneyFmt(row.logistics_rub)} за шт.`);
  return (
    <div title={parts.join("\n")}>
      <Money value={row.fees_rub} />
      <div className="text-[11px] text-[var(--color-on-surface-variant)] whitespace-nowrap">комиссия {pct(row.commission_pct)}</div>
    </div>
  );
}

function Breakdown({ rows, setRows, onError }) {
  const [marketplace, setMarketplace] = useState("wb");
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState("buyer_price");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter(
      (r) =>
        r.marketplace === marketplace &&
        (!q || r.offer_id.toLowerCase().includes(q) || (r.title || "").toLowerCase().includes(q))
    );
  }, [rows, marketplace, query]);

  const seenAt = visible[0]?.price_seen_at;

  const saveTarget = async (row, value, newMode) => {
    const res = await safeCall(() =>
      request(`/api/v1/pricing/target/${row.marketplace}/${encodeURIComponent(row.offer_id)}`, {
        method: "PUT",
        admin: true,
        body: { account_id: row.account_id, target_price: value, mode: row.rule_id ? row.mode : newMode },
      })
    );
    if (!res.ok) {
      onError(res.error);
      return false;
    }
    const rule = res.data;
    const kept = rule.mode === "buyer_price" ? row.buyer_price : rule.mode === "seller_price" ? row.seller_price : null;
    setRows((prev) =>
      prev.map((r) =>
        r.marketplace === row.marketplace && r.account_id === row.account_id && r.offer_id === row.offer_id
          ? {
              ...r,
              rule_id: rule.rule_id,
              mode: rule.mode,
              target_price: rule.target_price,
              rule_is_active: rule.is_active,
              rule_dry_run: rule.dry_run,
              target_gap_pct: kept === null || kept === undefined ? null : Math.round(((kept - value) / value) * 10000) / 100,
            }
          : r
      )
    );
    onError("");
    return true;
  };

  const saveCost = async (row, value) => {
    const res = await safeCall(() =>
      request(`/api/v1/pricing/costs/${encodeURIComponent(row.offer_id)}`, {
        method: "PUT",
        admin: true,
        body: { cost_price_rub: value },
      })
    );
    if (!res.ok) {
      onError(res.error);
      return false;
    }
    // the cost belongs to the article, on every marketplace
    setRows((prev) => prev.map((r) => (r.offer_id === row.offer_id ? withCost(r, value) : r)));
    onError("");
    return true;
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        {MARKETPLACES.map((m) => (
          <TabButton key={m.id} active={marketplace === m.id} onClick={() => setMarketplace(m.id)}>
            {m.label}
          </TabButton>
        ))}
        <input
          type="search"
          placeholder="Артикул или название"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="flex-1 min-w-[180px] px-3 py-1.5 rounded-lg border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
        />
        <label className="flex items-center gap-2 text-xs text-[var(--color-on-surface-variant)]">
          Новые цены держат
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            className="px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm text-[var(--color-on-surface)]"
          >
            {MODES.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex items-start gap-2 text-xs text-[var(--color-on-surface-variant)]">
        <Info size={14} className="mt-0.5 shrink-0" />
        <p>
          Скидка маркетплейса (СПП у WB, скидки и баллы за счёт Ozon) измеряется по последним продажам товара; «≈» —
          оценка по кабинету. Новое правило сначала работает в режиме симуляции: репрайсер только записывает, какую цену
          поставил бы. Цены со скидкой продавца сняты {seenAt ? formatAsOf(seenAt) : "—"}.
        </p>
      </div>

      {visible.length === 0 ? (
        <div className="rounded-xl border border-dashed border-[var(--color-outline-variant)] text-[var(--color-on-surface-variant)] text-center py-12 px-4 text-sm">
          Нет товаров. Витрина цен собирается каждые 30 минут после снимка каталога.
        </div>
      ) : (
        <div className="overflow-auto rounded-xl border border-[var(--color-outline-variant)] max-h-[70vh]">
          <table className="w-full min-w-[1100px] text-sm">
            <thead>
              <tr>
                <th className={thClass}>Артикул поставщика</th>
                <th className={thClass}>Цена зачёркнутая</th>
                <th className={thClass}>Скидка продавца</th>
                <th className={thClass}>Цена со скидкой</th>
                <th className={thClass}>Скидка МП</th>
                <th className={thClass}>Цена для покупателя</th>
                <th className={thClass}>Желаемая цена</th>
                <th className={thClass}>Себестоимость</th>
                <th className={thClass}>Комиссии</th>
                <th className={thClass}>Маржа, %</th>
                <th className={thClass}>Маржа, ₽</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-outline-variant)]">
              {visible.map((row) => {
                const loss = row.margin_rub !== null && row.margin_rub < 0;
                return (
                  <tr key={`${row.account_id}:${row.offer_id}`} className="hover:bg-[var(--color-surface-container)]/60">
                    <td className={tdClass}>
                      <div className="flex items-center gap-2">
                        {row.image_url && (
                          <img src={row.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" className="h-10 w-8 rounded object-cover" />
                        )}
                        <div className="min-w-0">
                          <div className="font-mono text-xs">{row.offer_id}</div>
                          {row.title && <div className="text-xs text-[var(--color-on-surface-variant)] truncate max-w-[220px]">{row.title}</div>}
                        </div>
                      </div>
                    </td>
                    <td className={tdClass}><Money value={row.list_price} /></td>
                    <td className={tdClass}><span className="font-mono">{pct(row.seller_discount_pct, 0)}</span></td>
                    <td className={tdClass}><Money value={row.seller_price} /></td>
                    <td className={tdClass}><DiscountCell row={row} /></td>
                    <td className={tdClass}><Money value={row.buyer_price} className="font-semibold" /></td>
                    <td className={tdClass}><TargetCell row={row} mode={mode} onSave={saveTarget} /></td>
                    <td className={tdClass}>
                      <EditableNumber value={row.cost_price} onSave={(v) => saveCost(row, v)} label={`Себестоимость ${row.offer_id}`} />
                    </td>
                    <td className={tdClass}><FeesCell row={row} /></td>
                    <td className={tdClass}>
                      {row.margin_pct === null ? <Dash /> : <span className={`font-mono ${loss ? "text-red-600 font-semibold" : ""}`}>{pct(row.margin_pct)}</span>}
                    </td>
                    <td className={tdClass}>
                      {row.margin_rub === null ? (
                        <span title="Укажите себестоимость"><Dash /></span>
                      ) : (
                        <Money value={row.margin_rub} className={loss ? "text-red-600 font-semibold" : ""} />
                      )}
                      {row.breakeven_price !== null && (
                        <div className="text-[11px] text-[var(--color-on-surface-variant)] whitespace-nowrap">
                          безубыточность {moneyFmt(row.breakeven_price)}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Compare({ rows }) {
  const [query, setQuery] = useState("");
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((r) => !q || r.offer_id.toLowerCase().includes(q) || (r.title || "").toLowerCase().includes(q));
  }, [rows, query]);

  const cell = (buyer, seller) =>
    seller === null || seller === undefined ? (
      <Dash />
    ) : (
      <div>
        <Money value={buyer} className="font-semibold" />
        <div className="text-[11px] text-[var(--color-on-surface-variant)] font-mono whitespace-nowrap">со скидкой продавца {moneyFmt(seller)}</div>
      </div>
    );

  return (
    <div className="space-y-3">
      <input
        type="search"
        placeholder="Артикул или название"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="w-full px-3 py-1.5 rounded-lg border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
      />
      <p className="text-xs text-[var(--color-on-surface-variant)]">
        Цена для покупателя — после скидки маркетплейса. Товары сопоставлены по артикулу поставщика. Яндекс Маркет появится после подключения.
      </p>
      <div className="overflow-auto rounded-xl border border-[var(--color-outline-variant)] max-h-[70vh]">
        <table className="w-full min-w-[640px] text-sm">
          <thead>
            <tr>
              <th className={thClass}>Артикул поставщика</th>
              <th className={thClass}>Цена на WB</th>
              <th className={thClass}>Цена на Ozon</th>
              <th className={thClass}>Цена на ЯМ</th>
              <th className={thClass}>Разница</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-outline-variant)]">
            {visible.map((row) => (
              <tr key={row.offer_id} className="hover:bg-[var(--color-surface-container)]/60">
                <td className={tdClass}>
                  <div className="font-mono text-xs">{row.offer_id}</div>
                  {row.title && <div className="text-xs text-[var(--color-on-surface-variant)] truncate max-w-[260px]">{row.title}</div>}
                </td>
                <td className={tdClass}>{cell(row.wb_buyer_price, row.wb_seller_price)}</td>
                <td className={tdClass}>{cell(row.ozon_buyer_price, row.ozon_seller_price)}</td>
                <td className={tdClass}><Dash /></td>
                <td className={tdClass}>{row.buyer_spread_pct === null ? <Dash /> : <span className="font-mono">{pct(row.buyer_spread_pct)}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Costs({ onImported }) {
  const [costs, setCosts] = useState([]);
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = () =>
    safeCall(() => request("/api/v1/pricing/costs", { admin: true })).then((res) => setCosts(res.ok ? res.data : []));

  useEffect(() => {
    load();
  }, []);

  const handleImport = async () => {
    setBusy(true);
    const res = await safeCall(() => request("/api/v1/pricing/costs/import", { method: "POST", admin: true, body: { text } }));
    setBusy(false);
    setResult(res.ok ? res.data : { imported: 0, errors: [res.error] });
    if (res.ok && res.data.imported) {
      setText("");
      load();
      onImported();
    }
  };

  const handleDelete = async (offerId) => {
    const res = await safeCall(() => request(`/api/v1/pricing/costs/${encodeURIComponent(offerId)}`, { method: "DELETE", admin: true }));
    if (res.ok) setCosts((prev) => prev.filter((c) => c.offer_id !== offerId));
  };

  return (
    <div className="space-y-4">
      <div className="md3-card-elevated p-4 space-y-3">
        <h3 className="text-sm font-semibold">Загрузить себестоимость</h3>
        <p className="text-xs text-[var(--color-on-surface-variant)]">
          Скопируйте из таблицы два столбца — артикул поставщика и себестоимость — и вставьте сюда. Себестоимость одна для
          артикула на всех маркетплейсах; повторная загрузка обновляет значения.
        </p>
        <textarea
          className="w-full px-3 py-2 rounded-lg border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm min-h-[140px] font-mono"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={"btn30pgf05BK9b\t120,50\nbtn204pgf10gorc\t95"}
        />
        <div className="flex items-center gap-3">
          <button
            onClick={handleImport}
            disabled={busy || !text.trim()}
            className="flex items-center gap-1 px-4 py-1.5 rounded-full bg-[var(--color-primary)] text-white text-sm font-medium disabled:opacity-50"
          >
            <UploadSimple size={14} /> Загрузить
          </button>
          {result && (
            <span className="text-sm">
              Загружено: {result.imported}
              {result.errors.length > 0 && <span className="text-red-600"> · ошибок: {result.errors.length}</span>}
            </span>
          )}
        </div>
        {result?.errors?.length > 0 && (
          <ul className="text-xs text-red-700 font-mono list-disc pl-5">
            {result.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        )}
      </div>

      <section className="md3-card-elevated p-4">
        <h3 className="text-sm font-semibold mb-3">Себестоимость по артикулам ({costs.length})</h3>
        {costs.length === 0 ? (
          <p className="text-sm text-[var(--color-on-surface-variant)]">Пока пусто. Без себестоимости маржа не считается.</p>
        ) : (
          <div className="overflow-auto max-h-[50vh]">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className={thClass}>Артикул</th>
                  <th className={thClass}>Себестоимость</th>
                  <th className={thClass}>Обновлено</th>
                  <th className={thClass}><span className="sr-only">Удалить</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-outline-variant)]">
                {costs.map((c) => (
                  <tr key={c.offer_id}>
                    <td className={`${tdClass} font-mono text-xs`}>{c.offer_id}</td>
                    <td className={tdClass}><Money value={c.cost_price_rub} /></td>
                    <td className={`${tdClass} text-xs text-[var(--color-on-surface-variant)]`}>{formatAsOf(c.updated_at)}</td>
                    <td className={tdClass}>
                      <button
                        onClick={() => handleDelete(c.offer_id)}
                        aria-label={`Удалить себестоимость ${c.offer_id}`}
                        className="p-1.5 rounded-lg hover:bg-red-50 text-red-500 transition-colors"
                      >
                        <Trash size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export default function Pricing() {
  const [tab, setTab] = useState("breakdown");
  const [breakdown, setBreakdown] = useState([]);
  const [compare, setCompare] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = () =>
    Promise.all([
      safeCall(() => request("/api/v1/pricing/breakdown", { admin: true })),
      safeCall(() => request("/api/v1/pricing/compare", { admin: true })),
    ]).then(([bRes, cRes]) => {
      setBreakdown(bRes.ok ? bRes.data : []);
      setCompare(cRes.ok ? cRes.data : []);
      setError(bRes.ok ? "" : bRes.error);
      setLoading(false);
    });

  useEffect(() => {
    load();
  }, []);

  if (loading) return <Spinner />;

  return (
    <div className="space-y-4">
      {error && (
        <div role="alert" className="md3-card-elevated p-3 border-l-4 border-red-500 text-sm text-red-700">
          {error}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => (
          <TabButton key={t.id} active={tab === t.id} onClick={() => setTab(t.id)}>
            {t.label}
          </TabButton>
        ))}
      </div>
      {tab === "breakdown" && <Breakdown rows={breakdown} setRows={setBreakdown} onError={setError} />}
      {tab === "compare" && <Compare rows={compare} />}
      {tab === "costs" && <Costs onImported={load} />}
    </div>
  );
}
