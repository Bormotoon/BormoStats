// API client and connection settings.
//
// Security notes:
// - The API key (a personal user key, ideally not the platform master key) is kept
//   in sessionStorage, so it is gone with the tab, unless the user ticks "remember on
//   this device": then it is kept in localStorage until "sign out". It is sent with every
//   API request as X-API-Key.
// - The API base URL defaults to the page origin. In production builds a custom
//   base is accepted only for origins listed in VITE_ALLOWED_API_ORIGINS, so a
//   tampered localStorage entry cannot redirect credentials to another host.

const STORE_KEYS = {
  apiBase: "bormostats_ui_api_base",
  theme: "bormostats_ui_theme",
  apiKey: "bormostats_api_key",
  legacyAdminKey: "bormostats_admin_key",
  organization: "bormostats_organization_id",
};

// the key survives closing the tab only when the user asked for it
function keyStorages() {
  return [sessionStorage, localStorage];
}

const ALLOWED_ORIGINS = (import.meta.env.VITE_ALLOWED_API_ORIGINS || "")
  .split(",")
  .map((item) => item.trim().replace(/\/+$/, ""))
  .filter(Boolean);

const state = {
  apiBase: "",
  apiKey: "",
  organizationId: "",
  rememberKey: false,
};

const listeners = new Set();

function safeGet(storage, key) {
  try {
    return storage.getItem(key) || "";
  } catch {
    return "";
  }
}

function safeSet(storage, key, value) {
  try {
    if (value) storage.setItem(key, value);
    else storage.removeItem(key);
  } catch {
    // storage may be unavailable (private mode); settings then live in memory only
  }
}

function notify() {
  listeners.forEach((listener) => listener({ ...state }));
}

export function subscribeSettings(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function loadSettings() {
  const storedBase = safeGet(localStorage, STORE_KEYS.apiBase);
  const validation = validateApiBase(storedBase);
  state.apiBase = validation.ok ? validation.value : "";
  if (!validation.ok) safeSet(localStorage, STORE_KEYS.apiBase, "");

  // migrate the pre-2026.10 session key name
  const legacy = safeGet(sessionStorage, STORE_KEYS.legacyAdminKey);
  if (legacy && !safeGet(sessionStorage, STORE_KEYS.apiKey)) {
    safeSet(sessionStorage, STORE_KEYS.apiKey, legacy);
  }
  safeSet(sessionStorage, STORE_KEYS.legacyAdminKey, "");
  const remembered = safeGet(localStorage, STORE_KEYS.apiKey);
  state.rememberKey = Boolean(remembered);
  state.apiKey = safeGet(sessionStorage, STORE_KEYS.apiKey) || remembered;
  state.organizationId =
    safeGet(sessionStorage, STORE_KEYS.organization) || safeGet(localStorage, STORE_KEYS.organization);
}

export function getSettings() {
  return { ...state };
}

export function getApiBase() {
  return state.apiBase || window.location.origin;
}

export function getApiKey() {
  return state.apiKey;
}

/** @deprecated kept for older pages; every key is now sent with every request. */
export const getAdminKey = getApiKey;

function persistKey() {
  safeSet(sessionStorage, STORE_KEYS.apiKey, state.apiKey);
  safeSet(sessionStorage, STORE_KEYS.organization, state.organizationId);
  safeSet(localStorage, STORE_KEYS.apiKey, state.rememberKey ? state.apiKey : "");
  safeSet(localStorage, STORE_KEYS.organization, state.rememberKey ? state.organizationId : "");
}

export function setApiKey(key) {
  state.apiKey = (key || "").trim();
  persistKey();
  notify();
}

/** Keep the key on this device (localStorage) or only for the tab (sessionStorage). */
export function setRememberKey(remember) {
  state.rememberKey = Boolean(remember);
  persistKey();
  notify();
}

export function setOrganizationId(value) {
  state.organizationId = (value || "").trim();
  persistKey();
  notify();
}

export function signOut() {
  state.apiKey = "";
  state.organizationId = "";
  state.rememberKey = false;
  for (const storage of keyStorages()) {
    safeSet(storage, STORE_KEYS.apiKey, "");
    safeSet(storage, STORE_KEYS.organization, "");
  }
  notify();
}

/**
 * Validate a user-supplied API base URL.
 * Returns { ok, value, error, crossOrigin }.
 */
export function validateApiBase(raw) {
  const trimmed = (raw || "").trim().replace(/\/+$/, "");
  if (!trimmed) return { ok: true, value: "", error: "", crossOrigin: false };
  let url;
  try {
    url = new URL(trimmed);
  } catch {
    return { ok: false, value: "", error: "invalidUrl", crossOrigin: false };
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") {
    return { ok: false, value: "", error: "invalidProtocol", crossOrigin: false };
  }
  if (url.username || url.password) {
    return { ok: false, value: "", error: "invalidUrl", crossOrigin: false };
  }
  const origin = url.origin;
  const crossOrigin = origin !== window.location.origin;
  if (crossOrigin && import.meta.env.PROD && !ALLOWED_ORIGINS.includes(origin)) {
    return { ok: false, value: "", error: "originNotAllowed", crossOrigin };
  }
  if (import.meta.env.PROD && url.protocol === "http:" && window.location.protocol === "https:") {
    return { ok: false, value: "", error: "insecureProtocol", crossOrigin };
  }
  return { ok: true, value: `${origin}${url.pathname.replace(/\/+$/, "")}`, error: "", crossOrigin };
}

export function setApiBase(base) {
  const result = validateApiBase(base);
  if (result.ok) {
    state.apiBase = result.value;
    safeSet(localStorage, STORE_KEYS.apiBase, state.apiBase);
    notify();
  }
  return result;
}

export function getTheme() {
  return safeGet(localStorage, STORE_KEYS.theme) || "dark";
}

export function setTheme(theme) {
  safeSet(localStorage, STORE_KEYS.theme, theme);
  document.documentElement.dataset.theme = theme;
}

export class ApiError extends Error {
  constructor(status, message) {
    super(`HTTP ${status}: ${message}`);
    this.status = status;
  }
}

export async function request(path, options = {}) {
  const { query, method = "GET", body } = options;
  const headers = {};
  const requireKey = options.admin ?? false;

  if (requireKey && !state.apiKey) {
    throw new Error("API key not set. Set it in Settings.");
  }
  if (state.apiKey) {
    headers["X-API-Key"] = state.apiKey;
  }
  if (state.organizationId) {
    headers["X-Organization-Id"] = state.organizationId;
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const url = new URL(`${getApiBase()}${path}`, window.location.origin);
  if (query) {
    Object.entries(query).forEach(([key, value]) => {
      if (value !== "" && value !== null && value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    });
  }

  const response = await fetch(url.toString(), {
    method,
    headers,
    credentials: "omit",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!response.ok) {
    const text = await response.text();
    let message = text;
    try {
      const payload = JSON.parse(text);
      message = payload?.error?.message || payload?.detail || text;
    } catch {
      message = text;
    }
    // an expired or revoked session: back to the sign-in screen
    if (response.status === 401 && state.apiKey && path !== "/api/v1/auth/login") {
      signOut();
    }
    throw new ApiError(response.status, message);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("text/plain")) {
    return response.text();
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

/**
 * Every item of a paginated list endpoint. Totals and charts need all rows: a page holds at
 * most 2000, and summing one page silently drops the rest of the period.
 */
export async function requestAll(path, options = {}) {
  const pageSize = 2000; // the API's MAX_PAGE_LIMIT
  const items = [];
  let offset = 0;
  for (;;) {
    const page = await request(path, { ...options, query: { ...options.query, limit: pageSize, offset } });
    items.push(...(page?.items || []));
    const next = page?.pagination?.next_offset;
    if (next === null || next === undefined) {
      return { ...page, items };
    }
    offset = next;
  }
}

/** Download a protected file (the API key travels in a header, so plain links cannot be used). */
export async function downloadFile(path, fallbackName) {
  const headers = {};
  if (state.apiKey) headers["X-API-Key"] = state.apiKey;
  if (state.organizationId) headers["X-Organization-Id"] = state.organizationId;
  const response = await fetch(new URL(`${getApiBase()}${path}`, window.location.origin), {
    headers,
    credentials: "omit",
  });
  if (!response.ok) throw new ApiError(response.status, await response.text());
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^";]+)"?/);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = match ? match[1] : fallbackName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function getCurrentPrincipal() {
  return request("/api/v1/users/me");
}

export async function safeCall(fn) {
  try {
    const data = await fn();
    return { ok: true, data, error: "" };
  } catch (error) {
    return {
      ok: false,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}
