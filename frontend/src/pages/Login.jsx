import { useState } from "react";
import { useI18n } from "../utils/i18n.jsx";
import { request, setApiKey, setRememberKey } from "../utils/api.js";

const inputClass =
  "w-full px-3 py-2 rounded-lg bg-[var(--color-surface-container)] border border-[var(--color-outline-variant)] text-sm text-[var(--color-on-surface)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]";

export default function Login() {
  const { t } = useI18n();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = (event) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    request("/api/v1/auth/login", { method: "POST", body: { email, password } })
      .then((res) => {
        // a session lasts 30 days on this device
        setRememberKey(true);
        setApiKey(res.token);
      })
      .catch((err) => {
        setError(err.status === 401 ? t("login.wrong") : err.status === 429 ? t("login.tooMany") : err.message);
        setBusy(false);
      });
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[var(--color-surface)] px-4">
      <form onSubmit={submit} className="md3-card-elevated w-full max-w-sm p-6 space-y-4">
        <div>
          <h1 className="text-xl font-bold text-[var(--color-on-surface)]">BormoStats</h1>
          <p className="text-sm text-[var(--color-on-surface-variant)]">{t("login.title")}</p>
        </div>
        <label className="block space-y-1 text-sm">
          <span>{t("login.email")}</span>
          <input type="email" autoComplete="username" required className={inputClass} value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="block space-y-1 text-sm">
          <span>{t("login.password")}</span>
          <input type="password" autoComplete="current-password" required className={inputClass} value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="text-sm text-[var(--color-error)]">{error}</p>}
        <button type="submit" disabled={busy} className="w-full px-4 py-2 rounded-lg bg-[var(--color-primary)] text-[var(--color-on-primary)] font-semibold disabled:opacity-60">
          {t("login.submit")}
        </button>
      </form>
    </div>
  );
}
