import { useEffect, useState } from "react";
import { SignOut, UserCircle, Warning } from "@phosphor-icons/react";
import { useI18n } from "../utils/i18n.jsx";
import {
  getCurrentPrincipal,
  getSettings,
  setApiBase,
  setApiKey,
  setOrganizationId,
  signOut,
  subscribeSettings,
  validateApiBase,
} from "../utils/api.js";

const inputClass =
  "w-full px-3 py-2 rounded-lg bg-[var(--color-surface-container)] border border-[var(--color-outline-variant)] text-sm text-[var(--color-on-surface)] placeholder:text-[var(--color-on-surface-variant)] focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]";

export function usePrincipal() {
  const [principal, setPrincipal] = useState(null);
  const [settings, setSettingsState] = useState(getSettings);

  useEffect(() => subscribeSettings(setSettingsState), []);

  useEffect(() => {
    let cancelled = false;
    if (!settings.apiKey) {
      setPrincipal(null);
      return undefined;
    }
    getCurrentPrincipal()
      .then((data) => { if (!cancelled) setPrincipal(data); })
      .catch(() => { if (!cancelled) setPrincipal(null); });
    return () => { cancelled = true; };
  }, [settings.apiKey, settings.organizationId, settings.apiBase]);

  return { principal, settings };
}

export default function SettingsPanel() {
  const { t } = useI18n();
  const { principal, settings } = usePrincipal();
  const [apiBaseInput, setApiBaseInput] = useState(settings.apiBase);
  const [keyInput, setKeyInput] = useState(settings.apiKey);
  const [orgInput, setOrgInput] = useState(settings.organizationId);
  const [baseError, setBaseError] = useState("");

  useEffect(() => {
    setKeyInput(settings.apiKey);
    setOrgInput(settings.organizationId);
  }, [settings.apiKey, settings.organizationId]);

  const preview = validateApiBase(apiBaseInput);

  const commitApiBase = () => {
    const result = setApiBase(apiBaseInput);
    setBaseError(result.ok ? "" : t(`common.apiBaseErrors.${result.error}`));
  };

  return (
    <div className="px-4 py-3 space-y-3">
      <div className="rounded-lg bg-[var(--color-surface-container)] px-3 py-2 text-xs text-[var(--color-on-surface-variant)]" aria-live="polite">
        {principal ? (
          <div className="flex items-start gap-2">
            <UserCircle size={18} aria-hidden="true" className="shrink-0 mt-0.5" />
            <div className="min-w-0">
              <p className="font-semibold text-[var(--color-on-surface)] truncate">
                {principal.auth_method === "admin_key" ? t("common.platformAdmin") : `${t("common.signedInAs")} ${principal.name || principal.email || principal.principal_id}`}
              </p>
              <p className="truncate">{principal.organization_id} · {t("common.role")}: {principal.role}</p>
              {principal.api_key_expires_at && (
                <p>{t("common.keyExpires")}: {new Date(principal.api_key_expires_at).toLocaleDateString()}</p>
              )}
            </div>
          </div>
        ) : (
          <p>{t("common.signedOutHint")}</p>
        )}
      </div>

      <label className="block">
        <span className="text-xs font-semibold text-[var(--color-on-surface-variant)] block mb-1.5">{t("common.adminApiKey")}</span>
        <input
          type="password"
          autoComplete="off"
          value={keyInput}
          onChange={(e) => setKeyInput(e.target.value)}
          onBlur={() => setApiKey(keyInput)}
          onKeyDown={(e) => { if (e.key === "Enter") setApiKey(keyInput); }}
          placeholder={t("common.placeholderKey")}
          className={inputClass}
        />
      </label>

      {principal?.auth_method === "admin_key" && (
        <label className="block">
          <span className="text-xs font-semibold text-[var(--color-on-surface-variant)] block mb-1.5">{t("common.organization")}</span>
          <input
            type="text"
            value={orgInput}
            onChange={(e) => setOrgInput(e.target.value)}
            onBlur={() => setOrganizationId(orgInput)}
            placeholder={t("common.placeholderOrg")}
            className={inputClass}
          />
        </label>
      )}

      <label className="block">
        <span className="text-xs font-semibold text-[var(--color-on-surface-variant)] block mb-1.5">{t("common.apiBaseUrl")}</span>
        <input
          type="url"
          value={apiBaseInput}
          onChange={(e) => setApiBaseInput(e.target.value)}
          onBlur={commitApiBase}
          placeholder={t("common.placeholderApi")}
          aria-invalid={!!baseError}
          className={inputClass}
        />
        {baseError && <span className="block mt-1 text-xs text-[var(--color-error)]" role="alert">{baseError}</span>}
        {!baseError && preview.ok && preview.crossOrigin && (
          <span className="flex items-center gap-1 mt-1 text-xs text-[var(--color-warning)]">
            <Warning size={14} aria-hidden="true" /> {t("common.crossOriginWarning")}
          </span>
        )}
      </label>

      <p className="text-xs text-[var(--color-on-surface-variant)] leading-relaxed">{t("common.keyNote")}</p>

      <button
        type="button"
        onClick={() => { signOut(); setKeyInput(""); setOrgInput(""); }}
        disabled={!settings.apiKey}
        className="flex items-center justify-center gap-2 w-full px-3 py-2 rounded-lg text-sm font-medium border border-[var(--color-outline-variant)] text-[var(--color-on-surface)] hover:bg-[var(--color-surface-container)] disabled:opacity-50 disabled:cursor-not-allowed focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-primary)]"
      >
        <SignOut size={16} aria-hidden="true" /> {t("common.signOut")}
      </button>
    </div>
  );
}
