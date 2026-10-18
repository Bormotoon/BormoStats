import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { request, safeCall } from "../utils/api.js";
import { formatAsOf, marketplaceName, numberFmt } from "../utils/formats.js";
import { Spinner } from "../components/StatusChip.jsx";
import {
  ArrowClockwise, Camera, ChatCircleText, Check, MagicWand, Note, PaperPlaneRight, PencilSimple, Plus, Star, Trash, Warning, X,
} from "@phosphor-icons/react";

const TABS = [
  { id: "reviews", label: "Отзывы" },
  { id: "auto", label: "Автоответы" },
  { id: "templates", label: "Шаблоны" },
];
const RATINGS = [5, 4, 3, 2, 1];
const PAGE = 30;
const MODE_LABELS = { off: "Не отвечать", template: "Шаблон из списка", ai: "Генерация ИИ" };
const SYNC_STATUS = {
  ok: "собраны",
  unavailable: "нет доступа к методу",
  error: "ошибка",
  no_credentials: "нет ключа",
};
const SOURCE_LABELS = { manual: "вручную", auto_template: "автоответ, шаблон", auto_ai: "автоответ, ИИ" };

const buttonClass =
  "inline-flex items-center gap-1 px-3 py-1.5 rounded-full border border-[var(--color-outline-variant)] text-sm font-medium hover:bg-[var(--color-surface-container)] disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]";
const primaryClass =
  "inline-flex items-center gap-1 px-4 py-1.5 rounded-full bg-[var(--color-primary)] text-white text-sm font-medium disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]";
const selectClass =
  "px-2.5 py-1.5 rounded-lg bg-[var(--color-surface)] border border-[var(--color-outline-variant)] text-sm text-[var(--color-on-surface)] focus:outline-none focus:border-[var(--color-primary)]";

function TabButton({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
        active ? "bg-[var(--color-primary)] text-white" : "text-[var(--color-on-surface-variant)] hover:bg-[var(--color-surface-container)]"
      }`}
    >
      {children}
    </button>
  );
}

export function Stars({ rating, size = 14 }) {
  return (
    <span className="inline-flex items-center gap-0.5" aria-label={`${rating} из 5`} role="img">
      {[1, 2, 3, 4, 5].map((n) => (
        <Star key={n} size={size} weight={n <= rating ? "fill" : "regular"} className={n <= rating ? "text-amber-500" : "text-[var(--color-outline-variant)]"} aria-hidden="true" />
      ))}
    </span>
  );
}

function errorText(error) {
  if (String(error).includes("ai_unavailable")) return "ИИ не настроен на сервере: задайте AI_API_URL и AI_API_KEY";
  return String(error);
}

// -- reviews --

function ReviewCard({ review, onReplied }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  const draft = async (source) => {
    setBusy(source);
    setError("");
    const res = await safeCall(() => request(`/api/v1/reviews/${review.marketplace}/${encodeURIComponent(review.review_id)}/draft`, { method: "POST", admin: true, body: { source } }));
    setBusy("");
    if (!res.ok) return setError(errorText(res.error));
    if (!res.data.text) return setError("Для этой оценки нет шаблонов — добавьте их на вкладке «Шаблоны»");
    setText(res.data.text);
    setOpen(true);
  };

  const send = async () => {
    setBusy("send");
    setError("");
    const res = await safeCall(() => request(`/api/v1/reviews/${review.marketplace}/${encodeURIComponent(review.review_id)}/reply`, { method: "POST", admin: true, body: { text } }));
    setBusy("");
    if (!res.ok) return setError(`Площадка не приняла ответ: ${res.error}`);
    setText("");
    setOpen(false);
    onReplied(res.data);
  };

  return (
    <article className="md3-card-elevated p-4 space-y-3">
      <header className="flex items-start gap-3">
        {review.image_url ? (
          <img src={review.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" className="h-16 w-12 rounded object-cover shrink-0" />
        ) : (
          <div className="h-16 w-12 rounded bg-[var(--color-surface-container)] shrink-0" aria-hidden="true" />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <Stars rating={review.rating} />
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-[var(--color-surface-container)]">{marketplaceName(review.marketplace)}</span>
            <span className="text-xs text-[var(--color-on-surface-variant)]">{formatAsOf(review.created_at)}</span>
            {review.user_name && <span className="text-xs text-[var(--color-on-surface-variant)]">{review.user_name}</span>}
            {review.photos > 0 && (
              <span className="inline-flex items-center gap-1 text-xs text-[var(--color-on-surface-variant)]"><Camera size={12} aria-hidden="true" /> {review.photos}</span>
            )}
          </div>
          <p className="text-sm font-medium mt-1 truncate">{review.product_name || review.product_id}</p>
          {review.offer_id && <p className="text-xs font-mono text-[var(--color-on-surface-variant)]">{review.offer_id}</p>}
        </div>
      </header>

      {review.has_text ? (
        <div className="text-sm space-y-1 whitespace-pre-line">
          {review.text && <p>{review.text}</p>}
          {review.pros && <p><span className="font-semibold">Достоинства: </span>{review.pros}</p>}
          {review.cons && <p><span className="font-semibold">Недостатки: </span>{review.cons}</p>}
        </div>
      ) : (
        <p className="text-sm italic text-[var(--color-on-surface-variant)]">Только оценка, без текста</p>
      )}

      {review.is_answered ? (
        <div className="rounded-lg bg-[var(--color-surface-container-low)] p-3 text-sm">
          <p className="text-xs font-semibold text-[var(--color-on-surface-variant)] mb-1 flex items-center gap-1">
            <Check size={12} aria-hidden="true" /> Ответ{review.reply_source ? ` (${SOURCE_LABELS[review.reply_source] || review.reply_source})` : ""}
          </p>
          <p className="whitespace-pre-line">{review.answer_text || "Ответ дан на площадке"}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {review.reply_status === "failed" && (
            <p className="text-xs text-red-700 flex items-start gap-1"><Warning size={14} className="shrink-0" aria-hidden="true" /> Прошлый ответ не отправлен: {review.reply_error}</p>
          )}
          <div className="flex flex-wrap gap-2">
            <button type="button" className={buttonClass} disabled={!!busy} onClick={() => draft("ai")}>
              <MagicWand size={16} aria-hidden="true" /> {busy === "ai" ? "Генерирую…" : "Сгенерировать ИИ"}
            </button>
            <button type="button" className={buttonClass} disabled={!!busy} onClick={() => draft("template")}>
              <Note size={16} aria-hidden="true" /> Шаблон
            </button>
            <button type="button" className={buttonClass} disabled={!!busy} onClick={() => setOpen(true)}>
              <PencilSimple size={16} aria-hidden="true" /> Написать
            </button>
          </div>
          {open && (
            <div className="space-y-2">
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                maxLength={3000}
                rows={4}
                aria-label="Текст ответа"
                placeholder="Текст ответа покупателю"
                className="w-full px-3 py-2 rounded-lg border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm"
              />
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" className={primaryClass} disabled={!!busy || text.trim().length < 2} onClick={send}>
                  <PaperPlaneRight size={16} aria-hidden="true" /> {busy === "send" ? "Отправляю…" : `Отправить на ${marketplaceName(review.marketplace)}`}
                </button>
                <button type="button" className={buttonClass} disabled={!!busy} onClick={() => { setOpen(false); setText(""); }}>
                  <X size={16} aria-hidden="true" /> Отмена
                </button>
                <span className="text-xs text-[var(--color-on-surface-variant)]">{text.length} / 3000</span>
              </div>
            </div>
          )}
        </div>
      )}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </article>
  );
}

function ReviewList({ summary, onChanged }) {
  const [searchParams] = useSearchParams();
  const marketplace = searchParams.get("marketplace") || "";
  const [filters, setFilters] = useState({ status: "unanswered", has_text: "true", rating: "", q: "" });
  const [state, setState] = useState({ loading: true, items: [], total: 0, error: "" });
  const [offset, setOffset] = useState(0);

  const load = useCallback(
    (nextOffset = 0) => {
      setState((s) => ({ ...s, loading: true, error: "" }));
      const query = { ...filters, marketplace, limit: PAGE, offset: nextOffset };
      safeCall(() => request("/api/v1/reviews", { query, admin: true })).then((res) => {
        setOffset(nextOffset);
        setState((s) =>
          res.ok
            ? { loading: false, items: nextOffset ? [...s.items, ...res.data.items] : res.data.items, total: res.data.total, error: "" }
            : { loading: false, items: [], total: 0, error: res.error }
        );
      });
    },
    [filters, marketplace]
  );

  useEffect(() => { load(0); }, [load]);

  const set = (key) => (e) => setFilters((f) => ({ ...f, [key]: e.target.value }));
  const replaced = (updated) => {
    setState((s) => ({
      ...s,
      items: filters.status === "unanswered" ? s.items.filter((r) => r.review_id !== updated.review_id) : s.items.map((r) => (r.review_id === updated.review_id ? updated : r)),
      total: filters.status === "unanswered" ? s.total - 1 : s.total,
    }));
    onChanged();
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3 p-3 rounded-xl border border-[var(--color-outline-variant)] bg-[var(--color-surface-container-low)]">
        <label className="flex flex-col gap-1 text-xs font-semibold text-[var(--color-on-surface-variant)]">
          Статус
          <select value={filters.status} onChange={set("status")} className={selectClass}>
            <option value="unanswered">Без ответа</option>
            <option value="answered">С ответом</option>
            <option value="all">Все</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold text-[var(--color-on-surface-variant)]">
          Текст
          <select value={filters.has_text} onChange={set("has_text")} className={selectClass}>
            <option value="true">С текстом ({numberFmt(summary?.unanswered_with_text || 0)} без ответа)</option>
            <option value="false">Только оценка ({numberFmt(summary?.unanswered_without_text || 0)} без ответа)</option>
            <option value="">Все</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold text-[var(--color-on-surface-variant)]">
          Оценка
          <select value={filters.rating} onChange={set("rating")} className={selectClass}>
            <option value="">Все</option>
            {RATINGS.map((r) => <option key={r} value={r}>{"★".repeat(r)}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-semibold text-[var(--color-on-surface-variant)] flex-1 min-w-[180px]">
          Поиск
          <input type="search" value={filters.q} onChange={set("q")} placeholder="Артикул, товар или слово из отзыва" className={selectClass} />
        </label>
      </div>

      {state.error && <div role="alert" className="md3-card-elevated p-3 border-l-4 border-red-500 text-sm text-red-700">{state.error}</div>}
      <p className="text-xs text-[var(--color-on-surface-variant)]">Найдено: {numberFmt(state.total)}</p>
      {!state.loading && !state.items.length && !state.error && (
        <div className="rounded-xl border border-dashed border-[var(--color-outline-variant)] text-[var(--color-on-surface-variant)] text-center py-12 px-4 text-sm">
          Отзывов нет. Отзывы собираются каждые 15 минут.
        </div>
      )}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        {state.items.map((review) => (
          <ReviewCard key={`${review.marketplace}:${review.review_id}`} review={review} onReplied={replaced} />
        ))}
      </div>
      {state.loading && <Spinner />}
      {!state.loading && state.items.length < state.total && (
        <div className="flex justify-center">
          <button type="button" className={buttonClass} onClick={() => load(offset + PAGE)}>Показать ещё</button>
        </div>
      )}
    </div>
  );
}

// -- auto replies --

function AutoReplies({ summary }) {
  const [settings, setSettings] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    safeCall(() => request("/api/v1/reviews/settings", { admin: true })).then((res) => setSettings(res.ok ? res.data : { auto_enabled: false, modes: {} }));
  }, []);

  if (!settings) return <Spinner />;

  const save = async (next) => {
    setSettings(next);
    setBusy(true);
    const res = await safeCall(() => request("/api/v1/reviews/settings", { method: "PUT", admin: true, body: next }));
    setBusy(false);
    setMessage(res.ok ? "Сохранено" : res.error);
    if (res.ok) setSettings(res.data);
  };
  const usesAi = Object.values(settings.modes || {}).includes("ai");

  return (
    <div className="space-y-4">
      <section className="md3-card-elevated p-4 space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold">Автоответы на отзывы без текста</h3>
            <p className="text-xs text-[var(--color-on-surface-variant)] mt-1 max-w-2xl">
              Отзывы, где покупатель поставил только оценку, получают ответ без вашего участия: при каждом сборе отзывов (раз в
              15 минут) — шаблон из списка этой оценки в случайном порядке или текст, сгенерированный ИИ. Отзывы с текстом
              автоматически не отвечаются: на них отвечайте на вкладке «Отзывы» с помощью ИИ, шаблона или вручную.
            </p>
          </div>
          <label className="inline-flex items-center gap-2 text-sm font-semibold cursor-pointer">
            <input
              type="checkbox"
              className="h-5 w-5 accent-[var(--color-primary)]"
              checked={settings.auto_enabled}
              disabled={busy}
              onChange={(e) => save({ ...settings, auto_enabled: e.target.checked })}
            />
            Автоответы включены
          </label>
        </div>

        <table className="w-full max-w-xl text-sm">
          <thead>
            <tr className="text-[var(--color-on-surface-variant)] border-b border-[var(--color-outline-variant)]">
              <th className="text-left py-2 font-medium">Оценка</th>
              <th className="text-left py-2 font-medium">Как отвечать</th>
            </tr>
          </thead>
          <tbody>
            {RATINGS.map((r) => (
              <tr key={r} className="border-b border-[var(--color-outline-variant)]/50">
                <td className="py-2"><Stars rating={r} /></td>
                <td className="py-2">
                  <select
                    aria-label={`Ответ на оценку ${r}`}
                    value={settings.modes?.[String(r)] || "off"}
                    disabled={busy}
                    onChange={(e) => save({ ...settings, modes: { ...settings.modes, [String(r)]: e.target.value } })}
                    className={selectClass}
                  >
                    {Object.entries(MODE_LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {usesAi && !summary?.ai_available && (
          <p className="flex items-start gap-2 text-xs text-amber-800 dark:text-amber-300">
            <Warning size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
            ИИ не настроен на сервере (AI_API_URL, AI_API_KEY): оценки с режимом «Генерация ИИ» не получат ответ, пока он не
            будет настроен. Выберите для них «Шаблон из списка» или настройте ИИ.
          </p>
        )}
        {!settings.auto_enabled && <p className="text-xs text-[var(--color-on-surface-variant)]">Сейчас выключены: ни один ответ не отправляется автоматически.</p>}
        {message && <p className="text-xs" role="status">{message}</p>}
        <p className="text-xs text-[var(--color-on-surface-variant)]">
          Автоответ уходит только на отзывы не старше 30 дней и не больше 100 за один сбор. Отправленные ответы видны на вкладке
          «Отзывы» со статусом «С ответом».
        </p>
      </section>
    </div>
  );
}

// -- templates --

function TemplateRow({ template, onSaved, onDeleted }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(template.text);
  const [error, setError] = useState("");

  const save = async () => {
    const res = await safeCall(() => request(`/api/v1/reviews/templates/${template.template_id}`, { method: "PUT", admin: true, body: { text } }));
    if (!res.ok) return setError(res.error);
    setEditing(false);
    onSaved(res.data);
  };
  const remove = async () => {
    const res = await safeCall(() => request(`/api/v1/reviews/templates/${template.template_id}`, { method: "DELETE", admin: true }));
    if (!res.ok) return setError(res.error);
    onDeleted(template.template_id);
  };

  return (
    <li className="py-2 space-y-1">
      {editing ? (
        <div className="space-y-2">
          <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={3000} aria-label="Текст шаблона" className="w-full px-3 py-2 rounded-lg border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm" />
          <div className="flex gap-2">
            <button type="button" className={primaryClass} disabled={text.trim().length < 2} onClick={save}>Сохранить</button>
            <button type="button" className={buttonClass} onClick={() => { setEditing(false); setText(template.text); }}>Отмена</button>
          </div>
        </div>
      ) : (
        <div className="flex items-start gap-2">
          <p className="text-sm flex-1 whitespace-pre-line">{template.text}</p>
          <button type="button" onClick={() => setEditing(true)} aria-label="Изменить шаблон" className="p-1.5 rounded-lg hover:bg-[var(--color-surface-container)]"><PencilSimple size={14} /></button>
          <button type="button" onClick={remove} aria-label="Удалить шаблон" className="p-1.5 rounded-lg hover:bg-red-50 text-red-500"><Trash size={14} /></button>
        </div>
      )}
      {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
    </li>
  );
}

function NewTemplate({ kind, rating, onCreated }) {
  const [text, setText] = useState("");
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const create = async () => {
    const res = await safeCall(() => request("/api/v1/reviews/templates", { method: "POST", admin: true, body: { kind, rating, text } }));
    if (!res.ok) return setError(res.error);
    setText("");
    setOpen(false);
    onCreated(res.data);
  };
  if (!open) {
    return <button type="button" className={buttonClass} onClick={() => setOpen(true)}><Plus size={14} aria-hidden="true" /> Добавить шаблон</button>;
  }
  return (
    <div className="space-y-2">
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={3000} aria-label="Новый шаблон" placeholder="Например: Спасибо, {имя}! Рады, что {товар} вам понравился." className="w-full px-3 py-2 rounded-lg border border-[var(--color-outline)] bg-[var(--color-surface)] text-sm" />
      <div className="flex gap-2">
        <button type="button" className={primaryClass} disabled={text.trim().length < 2} onClick={create}>Добавить</button>
        <button type="button" className={buttonClass} onClick={() => setOpen(false)}>Отмена</button>
      </div>
      {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
    </div>
  );
}

function Templates() {
  const [kind, setKind] = useState("no_text");
  const [templates, setTemplates] = useState(null);

  useEffect(() => {
    safeCall(() => request("/api/v1/reviews/templates", { admin: true })).then((res) => setTemplates(res.ok ? res.data : []));
  }, []);

  if (!templates) return <Spinner />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <TabButton active={kind === "no_text"} onClick={() => setKind("no_text")}>Для отзывов без текста</TabButton>
        <TabButton active={kind === "text"} onClick={() => setKind("text")}>Для отзывов с текстом</TabButton>
      </div>
      <p className="text-xs text-[var(--color-on-surface-variant)]">
        {kind === "no_text"
          ? "Из этих шаблонов автоответ выбирает случайный для оценки отзыва. "
          : "Эти шаблоны подставляются кнопкой «Шаблон» в отзыве с текстом — перед отправкой текст можно поправить. "}
        В тексте можно использовать {"{имя}"} — имя покупателя и {"{товар}"} — название товара.
      </p>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {RATINGS.map((rating) => {
          const list = templates.filter((t) => t.kind === kind && t.rating === rating);
          return (
            <section key={rating} className="md3-card-elevated p-4">
              <h3 className="flex items-center gap-2 text-sm font-semibold mb-1"><Stars rating={rating} /> <span className="text-[var(--color-on-surface-variant)] font-normal">{list.length} шт.</span></h3>
              <ul className="divide-y divide-[var(--color-outline-variant)] mb-3">
                {list.map((t) => (
                  <TemplateRow
                    key={t.template_id}
                    template={t}
                    onSaved={(saved) => setTemplates((prev) => prev.map((x) => (x.template_id === saved.template_id ? saved : x)))}
                    onDeleted={(id) => setTemplates((prev) => prev.filter((x) => x.template_id !== id))}
                  />
                ))}
                {!list.length && <li className="py-2 text-sm text-[var(--color-on-surface-variant)]">Шаблонов нет</li>}
              </ul>
              <NewTemplate kind={kind} rating={rating} onCreated={(t) => setTemplates((prev) => [...prev, t])} />
            </section>
          );
        })}
      </div>
    </div>
  );
}

// -- page --

function SyncStatus({ summary, onSync, syncing }) {
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs text-[var(--color-on-surface-variant)]">
      {(summary?.sync || []).map((s) => (
        <span key={`${s.marketplace}:${s.account_id}`} className={`inline-flex items-center gap-1 ${s.status === "ok" ? "" : "text-amber-800 dark:text-amber-300"}`} title={s.message}>
          {s.status !== "ok" && <Warning size={12} aria-hidden="true" />}
          {marketplaceName(s.marketplace)}: {SYNC_STATUS[s.status] || s.status}
          {s.synced_at ? ` ${formatAsOf(s.synced_at)}` : ""}
          {s.status === "unavailable" && s.marketplace === "ozon" ? " — отзывы Ozon доступны по API с подпиской Premium Plus" : ""}
        </span>
      ))}
      {!summary?.sync?.length && <span>Отзывы ещё не собирались — первый сбор в течение 15 минут.</span>}
      <button type="button" className={buttonClass} onClick={onSync} disabled={syncing}>
        <ArrowClockwise size={14} aria-hidden="true" /> {syncing ? "Собираю…" : "Собрать сейчас"}
      </button>
    </div>
  );
}

export default function Reviews() {
  const [tab, setTab] = useState("reviews");
  const [summary, setSummary] = useState(null);
  const [syncing, setSyncing] = useState(false);

  const loadSummary = useCallback(() => {
    safeCall(() => request("/api/v1/reviews/summary", { admin: true })).then((res) => res.ok && setSummary(res.data));
  }, []);
  useEffect(() => { loadSummary(); }, [loadSummary]);

  const sync = async () => {
    setSyncing(true);
    await safeCall(() => request("/api/v1/reviews/sync", { method: "POST", admin: true }));
    // the worker needs a little while; refresh the status afterwards
    setTimeout(() => { loadSummary(); setSyncing(false); }, 20_000);
  };

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <div className="md3-card-elevated p-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-on-surface-variant)]">Без ответа, с текстом</p>
          <p className="mt-2 text-2xl font-bold flex items-center gap-2"><ChatCircleText size={22} aria-hidden="true" /> {numberFmt(summary?.unanswered_with_text || 0)}</p>
          <p className="mt-1 text-xs text-[var(--color-on-surface-variant)]">ждут вашего ответа</p>
        </div>
        <div className="md3-card-elevated p-4">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-on-surface-variant)]">Без ответа, только оценка</p>
          <p className="mt-2 text-2xl font-bold flex items-center gap-2"><Star size={22} aria-hidden="true" /> {numberFmt(summary?.unanswered_without_text || 0)}</p>
          <p className="mt-1 text-xs text-[var(--color-on-surface-variant)]">можно отдать автоответам</p>
        </div>
        <div className="md3-card-elevated p-4 col-span-2 md:col-span-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-on-surface-variant)]">Отправлено сегодня</p>
          <p className="mt-2 text-2xl font-bold flex items-center gap-2"><PaperPlaneRight size={22} aria-hidden="true" /> {numberFmt(summary?.sent_today || 0)}</p>
          <p className="mt-1 text-xs text-[var(--color-on-surface-variant)]">ответов из BormoStats</p>
        </div>
      </div>
      <SyncStatus summary={summary} onSync={sync} syncing={syncing} />
      <div className="flex flex-wrap gap-2">
        {TABS.map((t) => <TabButton key={t.id} active={tab === t.id} onClick={() => setTab(t.id)}>{t.label}</TabButton>)}
      </div>
      {tab === "reviews" && <ReviewList summary={summary} onChanged={loadSummary} />}
      {tab === "auto" && <AutoReplies summary={summary} />}
      {tab === "templates" && <Templates />}
    </div>
  );
}
