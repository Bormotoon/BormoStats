const STORE_KEYS = {
  apiBase: "bormostats_ui_api_base",
  theme: "bormostats_ui_theme",
};

const state = {
  apiBase: "",
  adminKey: "",
};

export function loadSettings() {
  state.apiBase = normalizeBaseUrl(localStorage.getItem(STORE_KEYS.apiBase) || "");
  state.adminKey = sessionStorage.getItem("bormostats_admin_key") || "";
}

export function getApiBase() {
  return state.apiBase || window.location.origin;
}

export function getAdminKey() {
  return state.adminKey;
}

export function setAdminKey(key) {
  state.adminKey = key;
  if (key) {
    sessionStorage.setItem("bormostats_admin_key", key);
  } else {
    sessionStorage.removeItem("bormostats_admin_key");
  }
}

export function setApiBase(base) {
  state.apiBase = normalizeBaseUrl(base);
  localStorage.setItem(STORE_KEYS.apiBase, state.apiBase);
}

export function getTheme() {
  return localStorage.getItem(STORE_KEYS.theme) || "dark";
}

export function setTheme(theme) {
  localStorage.setItem(STORE_KEYS.theme, theme);
  document.documentElement.dataset.theme = theme;
}

function normalizeBaseUrl(value) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  return trimmed.replace(/\/+$/, "");
}

export async function request(path, options = {}) {
  const { query, method = "GET", body } = options;
  const headers = {};
  const admin = options.admin ?? false;

  if (admin) {
    if (!state.adminKey.trim()) {
      throw new Error("Admin API key not set. Set it in Settings.");
    }
    headers["X-API-Key"] = state.adminKey.trim();
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
    throw new Error(`HTTP ${response.status}: ${message}`);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("text/plain")) {
    return response.text();
  }
  return response.json();
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
