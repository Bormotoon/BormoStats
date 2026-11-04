import { useRef, useState } from "react";
import { request } from "../utils/api.js";

const inputClass = "w-full min-h-10 px-3 py-2 rounded-lg bg-[var(--color-surface-container)] border border-[var(--color-outline-variant)] text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]";

function currentDay() {
  const parts = new Intl.DateTimeFormat("en", { timeZone: "Europe/Moscow", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  return `${parts.find((p) => p.type === "year").value}-${parts.find((p) => p.type === "month").value}-${parts.find((p) => p.type === "day").value}`;
}

export default function ExpenseForm({ onSaved }) {
  const [expenseDate, setExpenseDate] = useState(currentDay);
  const [category, setCategory] = useState("");
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const submitting = useRef(false);

  async function submit(event) {
    event.preventDefault();
    if (submitting.current) return;
    setError("");
    setMessage("");
    const normalized = amount.replace(/\s/g, "").replace(",", ".");
    if (!category.trim()) {
      setError("Укажите категорию расхода.");
      return;
    }
    if (!/^\d+(\.\d{1,2})?$/.test(normalized) || !Number.isFinite(Number(normalized)) || Number(normalized) <= 0) {
      setError("Укажите сумму больше нуля, не более двух знаков после запятой.");
      return;
    }
    if (!/^\d{4}-(0[1-9]|1[0-2])-\d{2}$/.test(expenseDate) || Number.isNaN(Date.parse(expenseDate))) {
      setError("Укажите корректную дату расхода.");
      return;
    }
    submitting.current = true;
    setBusy(true);
    try {
      const expense = await request("/api/v1/pnl/expenses", {
        admin: true, method: "POST",
        body: { expense_date: expenseDate, category: category.trim(), amount_rub: Number(normalized), description: description.trim() },
      });
      onSaved(expense);
      setCategory("");
      setAmount("");
      setDescription("");
      setMessage("Расход сохранён. Месячный P&L учитывает изменения после пересчёта отчёта.");
    } catch (err) {
      setError(err.status === 403 ? "Для добавления расходов нужны права администратора организации." : `Не удалось сохранить расход. ${err.message}`);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="md3-card-elevated p-4 space-y-3" aria-label="Добавить внешний расход">
      <div>
        <h3 className="text-sm font-semibold">Добавить внешний расход</h3>
        <p className="text-xs text-[var(--color-on-surface-variant)] mt-1">Общий расход организации за выбранный день: аренда, зарплата, услуги и другие затраты.</p>
      </div>
      <fieldset disabled={busy} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 disabled:opacity-60">
        <label className="block space-y-1 text-sm">
          <span>Дата расхода</span>
          <input className={inputClass} type="date" required min="1970-01-01" max="2149-06-06" value={expenseDate} onChange={(e) => setExpenseDate(e.target.value)} />
        </label>
        <label className="block space-y-1 text-sm">
          <span>Категория</span>
          <input className={inputClass} required maxLength={100} placeholder="Например, аренда" value={category} onChange={(e) => setCategory(e.target.value)} />
        </label>
        <label className="block space-y-1 text-sm">
          <span>Сумма, ₽</span>
          <input className={`${inputClass} tabular-nums`} required inputMode="decimal" placeholder="0,00" value={amount} onChange={(e) => setAmount(e.target.value)} />
        </label>
        <label className="block space-y-1 text-sm">
          <span>Комментарий (необязательно)</span>
          <input className={inputClass} maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <button type="submit" className="min-h-10 justify-self-start px-4 py-2 rounded-lg bg-[var(--color-primary)] text-[var(--color-on-primary)] text-sm font-semibold active:scale-[0.96] transition-transform disabled:cursor-wait">
          {busy ? "Сохранение…" : "Добавить расход"}
        </button>
      </fieldset>
      {error && <p role="alert" className="text-sm text-[var(--color-error)]">{error}</p>}
      <p role="status" className="text-sm text-[var(--color-on-surface-variant)]">{message}</p>
    </form>
  );
}
