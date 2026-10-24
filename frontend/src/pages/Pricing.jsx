import { useState, useEffect, useMemo, useRef } from "react";
import { request, safeCall } from "../utils/api.js";
import { moneyFmt, numberFmt, formatAsOf } from "../utils/formats.js";
import { downloadXlsx, readTableFile } from "../utils/xlsx.js";
import { Spinner } from "../components/StatusChip.jsx";
import DataTable from "../components/DataTable.jsx";
import { Trash, UploadSimple, Info, FileXls, Warning } from "@phosphor-icons/react";

const TABS = [
  { id: "breakdown", label: "Разбор цены" },
  { id: "compare", label: "Сравнение цен" },
  { id: "costs", label: "Себестоимость" },
];
const MARKETPLACES = [
  { id: "wb", label: "WB" },
  { id: "ozon", label: "Ozon" },
];
// the desired price is the price the buyer sees on the marketplace, after its discounts;
// older rules made on the repricer page may keep another price
const MODE_SHORT = { seller_price: "держит цену со скидкой продавца", margin: "держит маржу" };
// the repricer keeps a buyer price on a discount measured on the card's own sales (3+ on WB, any
// on Ozon), or on WB on the account's median over 10+ orders (workers/app/tasks/repricer.py)
function minSamples(marketplace) {
  return marketplace === "ozon" ? 1 : 3;
}
function discountUsable(row) {
  if (row.mp_discount_scope === "product") return row.mp_discount_samples >= minSamples(row.marketplace);
  return row.mp_discount_scope === "account" && row.marketplace === "wb" && row.mp_discount_samples >= 10;
}
// what a buyer-price rule does while the card's discount cannot be measured (no_discount_fallback);
// the account's median only on WB: Ozon's discounts ("баллы за скидки") are given per card
const FALLBACKS = [
  { id: "", label: "ждать продаж", note: "" },
  { id: "account_median", label: "по медиане кабинета", note: "пока нет продаж — по скидке-медиане кабинета", only: "wb" },
  { id: "seller_price", label: "как цену продавца", note: "пока скидка не измерена — держит как цену продавца" },
];
function fallbacksFor(marketplace) {
  return FALLBACKS.filter((f) => !f.only || f.only === marketplace);
}
/** Whether a buyer-price rule has a discount to act on: the card's own or its fallback. */
function ruleCanAct(row) {
  if (row.mode !== "buyer_price" || discountUsable(row)) return true;
  if (row.no_discount_fallback === "seller_price") return true;
  return row.no_discount_fallback === "account_median" && row.marketplace === "wb" && row.mp_discount_pct !== null && row.mp_discount_pct !== undefined;
}
/** The price a rule keeps on the card now: the buyer's, or the seller's under that fallback. */
function keptPrice(row) {
  if (row.mode === "buyer_price" && !discountUsable(row) && row.no_discount_fallback === "seller_price") return row.seller_price;
  return row.mode === "buyer_price" ? row.buyer_price : row.mode === "seller_price" ? row.seller_price : null;
}
// a kept price this far from the desired one is highlighted
const GAP_WARN_PCT = 1;

const inputClass =
  "w-24 px-2 py-1 rounded border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm font-mono text-right";
const thClass =
  "text-center px-3 py-2.5 text-[11px] font-semibold text-[var(--color-on-surface-variant)] tracking-wide uppercase sticky top-0 bg-[var(--color-surface-container)] z-10 align-bottom";
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
    const title =
      row.marketplace === "ozon"
        ? "Нет продаж товара за 60 дней. Скидку Ozon («баллы за скидки») Ozon даёт каждому товару свою, у новых её почти нет — на витрине, скорее всего, цена со скидкой продавца"
        : "Нет продаж за последние 30 дней, скидку не на чем измерить";
    return <span title={title}><Dash /></span>;
  }
  const estimate = row.mp_discount_scope !== "product";
  const title = estimate
    ? `Оценка: у товара мало недавних продаж, взята медиана по кабинету (${row.mp_discount_samples} продаж)`
    : row.marketplace === "ozon"
      ? `Медиана по ${row.mp_discount_samples} последним продажам товара: скидка Ozon за его счёт («баллы за скидки»). Ozon меняет её, сейчас на витрине она может быть другой`
      : `Медиана по ${row.mp_discount_samples} последним продажам товара`;
  return (
    <span title={title} className={`font-mono whitespace-nowrap ${estimate ? "text-[var(--color-on-surface-variant)]" : ""}`}>
      {estimate ? "≈ " : ""}
      {pct(row.mp_discount_pct)}
    </span>
  );
}

function ruleStatus(row) {
  if (!row.rule_is_active) return "правило выключено";
  if (!ruleCanAct(row)) return "не действует: ждёт продаж для замера скидки";
  const prefix = row.rule_dry_run ? "симуляция: " : "";
  if (row.marketplace === "ozon" && row.mode === "buyer_price") {
    // Ozon cuts its points while the price index is red: the measured discount no longer holds
    if (row.price_index_color === "RED") return `${prefix}индекс цены Ozon красный — снижаем`;
    if (row.price_index_color === "YELLOW") return `${prefix}индекс цены Ozon жёлтый — не поднимаем`;
  }
  return row.rule_dry_run ? "симуляция" : "держится на площадке";
}

function TargetCell({ row, onSave, onFallback, fromFile }) {
  const gap = row.target_gap_pct;
  const off = gap !== null && gap !== undefined && Math.abs(gap) > GAP_WARN_PCT;
  const noDiscount = row.mode === "buyer_price" && !discountUsable(row);
  const fallbacks = fallbacksFor(row.marketplace);
  const fallback = fallbacks.find((f) => f.id === (row.no_discount_fallback || "")) || fallbacks[0];
  return (
    <div className="space-y-1">
      <EditableNumber value={row.target_price} onSave={(v) => onSave(row, v)} label={`Желаемая цена ${row.offer_id}`} />
      {fromFile && <span className="block text-[11px] leading-tight font-medium text-[var(--color-primary)] whitespace-nowrap">загружено из файла</span>}
      {row.rule_id && (
        <div className="text-[11px] leading-tight text-[var(--color-on-surface-variant)]">
          {MODE_SHORT[row.mode] && <span className="block">{MODE_SHORT[row.mode]}</span>}
          {off && (
            <span className="block text-amber-700 dark:text-amber-400 font-medium">
              сейчас {gap > 0 ? "+" : ""}
              {numberFmt(gap, 1)}%
            </span>
          )}
          <span className="block" title={noDiscount ? (row.marketplace === "ozon" ? "Скидку Ozon нужно измерить хотя бы на одной продаже этого товара" : "Скидку маркетплейса нужно измерить хотя бы на 3 продажах этого товара") : undefined}>
            {ruleStatus(row)}
          </span>
          {noDiscount && ruleCanAct(row) && fallback.note && <span className="block">{fallback.note}</span>}
          {(noDiscount || fallback.id) && row.mode === "buyer_price" && (
            <label className="block pt-0.5">
              <span className="sr-only">Пока нет продаж для замера скидки {row.offer_id}</span>
              <select
                className="max-w-full rounded border border-[var(--color-outline)] bg-[var(--color-surface)] px-1 py-0.5 text-[11px]"
                value={fallback.id}
                title="Что делать, пока скидку маркетплейса не на чем измерить"
                onChange={(e) => onFallback(row, e.target.value)}
              >
                {fallbacks.map((f) => (
                  <option key={f.id} value={f.id}>
                    без продаж: {f.label}
                  </option>
                ))}
              </select>
            </label>
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

const buttonClass =
  "flex items-center gap-1 px-3 py-1.5 rounded-full border border-[var(--color-outline-variant)] text-sm font-medium hover:bg-[var(--color-surface-container)] disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]";

/** Two-column rows of an uploaded .xlsx / .csv as the "article<TAB>value" text the API parses. */
async function fileToText(file) {
  const rows = await readTableFile(file);
  return rows.map((r) => `${r[0] ?? ""}\t${r[1] ?? ""}`).join("\n");
}

function fileError(error) {
  const code = error instanceof Error ? error.message : String(error);
  if (code === "old_xls") return "Старый формат .xls не поддерживается — сохраните файл как .xlsx (Книга Excel)";
  if (code === "not_a_zip" || code === "bad_zip" || code === "no_sheet") return "Не удалось прочитать файл — нужен .xlsx или .csv";
  return code;
}

/** A button that opens a file picker and hands the file's rows to `onText` as text. */
function FileImportButton({ onText, busy, children }) {
  const input = useRef(null);
  const [error, setError] = useState("");
  return (
    <>
      <input
        ref={input}
        type="file"
        accept=".xlsx,.csv,.txt,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"
        className="hidden"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          e.target.value = "";
          if (!file) return;
          setError("");
          try {
            await onText(await fileToText(file));
          } catch (err) {
            setError(fileError(err));
          }
        }}
      />
      <button type="button" className={buttonClass} disabled={busy} onClick={() => input.current?.click()}>
        <UploadSimple size={16} aria-hidden="true" /> {children}
      </button>
      {error && <span role="alert" className="text-xs text-red-700">{error}</span>}
    </>
  );
}

/** Shows only the articles of the last upload, which are also highlighted in the table. */
function LoadedToggle({ count, on, onChange }) {
  if (!count) return null;
  return (
    <label className="inline-flex items-center gap-2 text-sm cursor-pointer">
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} className="accent-[var(--color-primary)]" />
      Показать только загруженные ({count})
    </label>
  );
}

function ImportResult({ result, what, onlyLoaded, setOnlyLoaded }) {
  if (!result) return null;
  return (
    <div className="text-sm space-y-1" role="status">
      <p>
        {what}: {result.imported}
        {result.errors.length > 0 && <span className="text-red-600"> · ошибок: {result.errors.length}</span>}
        {result.not_found?.length > 0 && <span className="text-amber-700"> · нет на площадке: {result.not_found.length}</span>}
      </p>
      {result.updated?.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="text-xs text-[var(--color-on-surface-variant)]">Загруженные строки подсвечены в таблице ниже.</span>
          {setOnlyLoaded && <LoadedToggle count={result.updated.length} on={onlyLoaded} onChange={setOnlyLoaded} />}
        </div>
      )}
      {result.errors.length > 0 && (
        <ul className="text-xs text-red-700 font-mono list-disc pl-5">
          {result.errors.map((e) => <li key={e}>{e}</li>)}
        </ul>
      )}
      {result.not_found?.length > 0 && (
        <p className="text-xs text-amber-800 font-mono break-words">Не найдены: {result.not_found.join(", ")}</p>
      )}
    </div>
  );
}

/** Desired prices of one marketplace: a template, an upload and whether they are kept live. */
function TargetsPanel({ marketplace, rows, onImported, actionsEnabled, onlyLoaded, setOnlyLoaded }) {
  const label = MARKETPLACES.find((m) => m.id === marketplace)?.label || marketplace;
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [message, setMessage] = useState("");
  useEffect(() => {
    setResult(null);
    setMessage("");
  }, [marketplace]);

  const withTarget = rows.filter((r) => r.rule_id && r.mode === "buyer_price" && r.target_price);
  const live = withTarget.filter((r) => r.rule_is_active && !r.rule_dry_run).length;
  const idle = withTarget.filter((r) => r.rule_is_active && !ruleCanAct(r)).length;
  const priceColumn = `Желаемая цена для МП (${label})`;

  // only the headers: the seller pastes their own articles and prices under them
  const downloadTemplate = () =>
    downloadXlsx(`Желаемые цены ${label}`, `Желаемые цены ${label}`, [
      { label: "Артикул продавца", type: "text", width: 30 },
      { label: priceColumn, type: "money", width: 28 },
    ], []);

  const upload = async (text) => {
    setBusy(true);
    const res = await safeCall(() => request("/api/v1/pricing/targets/import", { method: "POST", admin: true, body: { marketplace, text } }));
    setBusy(false);
    setResult(res.ok ? res.data : { imported: 0, errors: [res.error] });
    onImported(res.ok ? res.data.updated : []);
  };

  const keep = async (value) => {
    setBusy(true);
    const res = await safeCall(() => request("/api/v1/pricing/targets/keep", { method: "POST", admin: true, body: { marketplace, keep: value } }));
    setBusy(false);
    if (!res.ok) {
      setMessage(res.error.includes("403") ? "Нет права менять цены на площадке (нужна роль администратора с правом execute_marketplace)" : res.error);
      return;
    }
    setMessage(value ? `Держатся на ${label}: ${res.data.rules} цен` : `Переведено в симуляцию: ${res.data.rules} цен`);
    onImported();
  };

  return (
    <div className="md3-card-elevated p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold">Желаемые цены {label}</h3>
          <p className="text-xs text-[var(--color-on-surface-variant)]">
            Задано: {withTarget.length} · на площадке: {live} · в симуляции: {withTarget.length - live}
            {idle > 0 && ` · не действуют без продаж: ${idle}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={buttonClass} onClick={downloadTemplate}>
            <FileXls size={16} aria-hidden="true" /> Шаблон Excel
          </button>
          <FileImportButton onText={upload} busy={busy}>Загрузить из Excel</FileImportButton>
        </div>
      </div>
      <p className="text-xs text-[var(--color-on-surface-variant)]">
        В шаблоне для {label} только заголовки «Артикул продавца» и «{priceColumn}». Вставьте под них два столбца из своей
        таблицы — в любом порядке и сколько угодно артикулов — и загрузите файл: цена встанет к своему артикулу. Артикулы,
        которых нет в файле, и пустые цены не меняются. Цены других площадок загружаются отдельным файлом на своей вкладке.
      </p>
      <ImportResult result={result} what="Загружено цен" onlyLoaded={onlyLoaded} setOnlyLoaded={setOnlyLoaded} />

      <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-[var(--color-outline-variant)]">
        <button
          type="button"
          disabled={busy || !withTarget.length}
          onClick={() => keep(true)}
          className="px-4 py-1.5 rounded-full bg-[var(--color-primary)] text-white text-sm font-medium disabled:opacity-50"
        >
          Держать цены на {label}
        </button>
        <button type="button" disabled={busy || !live} onClick={() => keep(false)} className={buttonClass}>
          Только симуляция
        </button>
        {message && <span className="text-sm" role="status">{message}</span>}
      </div>
      {!actionsEnabled && (
        <p className="flex items-start gap-2 text-xs text-amber-800 dark:text-amber-300">
          <Warning size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
          Запись цен на площадки выключена на сервере (MARKETPLACE_ACTIONS_ENABLED=false): даже «держащиеся» цены пока
          только записываются в журнал репрайсера. Включите переключатель в настройках сервера, чтобы цены менялись на площадке.
        </p>
      )}
    </div>
  );
}

function Breakdown({ rows, setRows, onError, onReload, actionsEnabled }) {
  const [marketplace, setMarketplace] = useState("wb");
  const [query, setQuery] = useState("");
  // articles of the last desired-price upload on this marketplace, highlighted in the table
  const [loaded, setLoaded] = useState(new Set());
  const [onlyLoaded, setOnlyLoaded] = useState(false);
  useEffect(() => {
    setLoaded(new Set());
    setOnlyLoaded(false);
  }, [marketplace]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter(
      (r) =>
        r.marketplace === marketplace &&
        (!onlyLoaded || loaded.has(r.offer_id)) &&
        (!q || r.offer_id.toLowerCase().includes(q) || (r.title || "").toLowerCase().includes(q))
    );
  }, [rows, marketplace, query, onlyLoaded, loaded]);

  const onImported = (offers) => {
    setLoaded(new Set(offers));
    setOnlyLoaded(false);
    if (offers.length) onReload();
  };

  const seenAt = visible[0]?.price_seen_at;

  const saveTarget = async (row, value, extra = {}) => {
    const res = await safeCall(() =>
      request(`/api/v1/pricing/target/${row.marketplace}/${encodeURIComponent(row.offer_id)}`, {
        method: "PUT",
        admin: true,
        body: { account_id: row.account_id, target_price: value, mode: "buyer_price", ...extra },
      })
    );
    if (!res.ok) {
      onError(res.error);
      return false;
    }
    const rule = res.data;
    setRows((prev) =>
      prev.map((r) => {
        if (r.marketplace !== row.marketplace || r.account_id !== row.account_id || r.offer_id !== row.offer_id) return r;
        const next = {
          ...r,
          rule_id: rule.rule_id,
          mode: rule.mode,
          target_price: rule.target_price,
          no_discount_fallback: rule.no_discount_fallback,
          rule_is_active: rule.is_active,
          rule_dry_run: rule.dry_run,
        };
        const kept = keptPrice(next);
        next.target_gap_pct = kept === null || kept === undefined ? null : Math.round(((kept - value) / value) * 10000) / 100;
        return next;
      })
    );
    onError("");
    return true;
  };

  const saveFallback = (row, fallback) => saveTarget(row, row.target_price, { no_discount_fallback: fallback });

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
      </div>

      <TargetsPanel
        marketplace={marketplace}
        rows={rows.filter((r) => r.marketplace === marketplace)}
        onImported={onImported}
        actionsEnabled={actionsEnabled}
        onlyLoaded={onlyLoaded}
        setOnlyLoaded={setOnlyLoaded}
      />

      <div className="flex items-start gap-2 text-xs text-[var(--color-on-surface-variant)]">
        <Info size={14} className="mt-0.5 shrink-0" />
        <p>
          Желаемая цена — цена для покупателя на площадке после всех её скидок (СПП у WB, скидки и баллы за счёт Ozon).
          Скидка площадки измеряется по последним продажам товара; «≈» — оценка по кабинету. Репрайсер каждые 10 минут
          подбирает цену продавца так, чтобы покупатель видел желаемую. Цены со скидкой продавца сняты{" "}
          {seenAt ? formatAsOf(seenAt) : "—"}.
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
                <th className={thClass}>Артикул продавца</th>
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
                const fromFile = loaded.has(row.offer_id);
                return (
                  <tr
                    key={`${row.account_id}:${row.offer_id}`}
                    className={fromFile ? "bg-[var(--color-primary-container)]/50" : "hover:bg-[var(--color-surface-container)]/60"}
                  >
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
                    <td className={tdClass}><TargetCell row={row} onSave={saveTarget} onFallback={saveFallback} fromFile={fromFile} /></td>
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

function priceCell(buyer, seller) {
  if (seller === null || seller === undefined) return <Dash />;
  return (
    <div className="text-right">
      <Money value={buyer} className="font-semibold" />
      <div className="text-[11px] text-[var(--color-on-surface-variant)] font-mono whitespace-nowrap">со скидкой продавца {moneyFmt(seller)}</div>
    </div>
  );
}

function Compare({ rows }) {
  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--color-on-surface-variant)]">
        Цена для покупателя — после скидки маркетплейса, измеренной на продажах товара; на Ozon без продаж — прочерк, там на
        витрине обычно цена со скидкой продавца. Товары сопоставлены по артикулу продавца. Яндекс Маркет появится после
        подключения. В фильтрах цен можно писать «&gt; 500», «&lt; 300» или «200-400».
      </p>
      <DataTable
        rows={rows}
        exportName="Сравнение цен"
        columns={[
          { key: "image_url", type: "image" },
          { key: "offer_id", label: "Артикул продавца", type: "text", render: (r) => <span className="font-mono text-xs">{r.offer_id}</span> },
          { key: "title", label: "Название", type: "text", width: 40 },
          { key: "wb_buyer_price", label: "Цена на WB", type: "money", render: (r) => priceCell(r.wb_buyer_price, r.wb_seller_price) },
          { key: "ozon_buyer_price", label: "Цена на Ozon", type: "money", render: (r) => priceCell(r.ozon_buyer_price, r.ozon_seller_price) },
          { key: "ym_buyer_price", label: "Цена на ЯМ", type: "money", value: () => null, render: () => <Dash /> },
          { key: "buyer_spread_pct", label: "Разница", type: "percent", value: (r) => (r.buyer_spread_pct === null || r.buyer_spread_pct === undefined ? null : r.buyer_spread_pct / 100) },
        ]}
      />
    </div>
  );
}

function Costs({ onImported }) {
  const [costs, setCosts] = useState([]);
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [onlyLoaded, setOnlyLoaded] = useState(false);
  const loaded = useMemo(() => new Set(result?.updated ?? []), [result]);
  const shown = onlyLoaded ? costs.filter((c) => loaded.has(c.offer_id)) : costs;

  const load = () =>
    safeCall(() => request("/api/v1/pricing/costs", { admin: true })).then((res) => setCosts(res.ok ? res.data : []));

  useEffect(() => {
    load();
  }, []);

  const importText = async (body) => {
    setBusy(true);
    const res = await safeCall(() => request("/api/v1/pricing/costs/import", { method: "POST", admin: true, body: { text: body } }));
    setBusy(false);
    setResult(res.ok ? res.data : { imported: 0, errors: [res.error] });
    setOnlyLoaded(false);
    if (res.ok && res.data.imported) {
      setText("");
      load();
      onImported();
    }
  };
  const handleImport = () => importText(text);

  // only the headers: the seller pastes their own articles and costs under them
  const downloadTemplate = () =>
    downloadXlsx("Себестоимость", "Себестоимость", [
      { label: "Артикул продавца", type: "text", width: 30 },
      { label: "Себестоимость", type: "money", width: 18 },
    ], []);

  const handleDelete = async (offerId) => {
    const res = await safeCall(() => request(`/api/v1/pricing/costs/${encodeURIComponent(offerId)}`, { method: "DELETE", admin: true }));
    if (res.ok) setCosts((prev) => prev.filter((c) => c.offer_id !== offerId));
  };

  return (
    <div className="space-y-4">
      <div className="md3-card-elevated p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold">Загрузить себестоимость</h3>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={buttonClass} onClick={downloadTemplate}>
              <FileXls size={16} aria-hidden="true" /> Шаблон Excel
            </button>
            <FileImportButton onText={importText} busy={busy}>Загрузить из Excel</FileImportButton>
          </div>
        </div>
        <p className="text-xs text-[var(--color-on-surface-variant)]">
          В шаблоне только заголовки «Артикул продавца» и «Себестоимость». Вставьте под них два столбца из своей таблицы —
          в любом порядке и сколько угодно артикулов — и загрузите файл (.xlsx или CSV). Себестоимость одна для артикула на
          всех площадках, поэтому загружается один раз; повторная загрузка обновляет значения, артикулы не из файла и пустые
          ячейки не меняются. Можно и просто вставить два столбца из таблицы в поле ниже.
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
            <span className="text-sm" role="status">
              Загружено: {result.imported}
              {result.errors.length > 0 && <span className="text-red-600"> · ошибок: {result.errors.length}</span>}
              {result.updated?.length > 0 && <span className="text-[var(--color-on-surface-variant)]"> · подсвечены в списке ниже</span>}
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
        <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
          <h3 className="text-sm font-semibold">Себестоимость по артикулам ({costs.length})</h3>
          <LoadedToggle count={loaded.size} on={onlyLoaded} onChange={setOnlyLoaded} />
        </div>
        {costs.length === 0 ? (
          <p className="text-sm text-[var(--color-on-surface-variant)]">Пока пусто. Без себестоимости маржа не считается.</p>
        ) : (
          <div className="overflow-auto max-h-[50vh]">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className={thClass}><span className="sr-only">Фото</span></th>
                  <th className={thClass}>Артикул</th>
                  <th className={thClass}>Себестоимость</th>
                  <th className={thClass}>Обновлено</th>
                  <th className={thClass}><span className="sr-only">Удалить</span></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-outline-variant)]">
                {shown.map((c) => (
                  <tr key={c.offer_id} className={loaded.has(c.offer_id) ? "bg-[var(--color-primary-container)]/50" : ""}>
                    <td className={`${tdClass} w-12`}>
                      {c.image_url && (
                        <img src={c.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" className="h-10 w-8 rounded object-cover" />
                      )}
                    </td>
                    <td className={tdClass}>
                      <div className="font-mono text-xs">{c.offer_id}</div>
                      {c.title && <div className="text-xs text-[var(--color-on-surface-variant)] truncate max-w-[260px]">{c.title}</div>}
                    </td>
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
  const [actionsEnabled, setActionsEnabled] = useState(true);

  const load = () =>
    Promise.all([
      safeCall(() => request("/api/v1/pricing/breakdown", { admin: true })),
      safeCall(() => request("/api/v1/pricing/compare", { admin: true })),
      safeCall(() => request("/api/v1/pricing/status", { admin: true })),
    ]).then(([bRes, cRes, sRes]) => {
      setBreakdown(bRes.ok ? bRes.data : []);
      setCompare(cRes.ok ? cRes.data : []);
      if (sRes.ok) setActionsEnabled(Boolean(sRes.data.marketplace_actions_enabled));
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
      {tab === "breakdown" && <Breakdown rows={breakdown} setRows={setBreakdown} onError={setError} onReload={load} actionsEnabled={actionsEnabled} />}
      {tab === "compare" && <Compare rows={compare} />}
      {tab === "costs" && <Costs onImported={load} />}
    </div>
  );
}
