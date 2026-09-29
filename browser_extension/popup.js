const $ = (id) => document.getElementById(id);

function normalizeOrigin(raw) {
  const url = new URL(raw.trim());
  if (url.protocol !== "https:" && url.hostname !== "localhost") {
    throw new Error("Нужен HTTPS-адрес");
  }
  if (url.username || url.password) throw new Error("URL не должен содержать логин/пароль");
  return url.origin;
}

$("save").addEventListener("click", async () => {
  try {
    const apiOrigin = normalizeOrigin($("apiOrigin").value);
    // Ask for host access to exactly this origin — nothing broader is requested.
    const granted = await chrome.permissions.request({ origins: [`${apiOrigin}/*`] });
    if (!granted) throw new Error("Доступ к адресу не выдан");
    const previous = await chrome.storage.local.get(["apiOrigin"]);
    if (previous.apiOrigin && previous.apiOrigin !== apiOrigin) {
      await chrome.permissions.remove({ origins: [`${previous.apiOrigin}/*`] });
    }
    await chrome.storage.local.set({
      apiOrigin,
      apiKey: $("apiKey").value.trim(),
      accountId: $("accountId").value.trim() || "default",
    });
    await chrome.storage.sync.remove(["apiUrl", "apiKey"]); // legacy synced settings
    $("status").textContent = "Сохранено";
  } catch (error) {
    $("status").textContent = error.message;
  }
});

$("clear").addEventListener("click", async () => {
  const { apiOrigin } = await chrome.storage.local.get(["apiOrigin"]);
  if (apiOrigin) await chrome.permissions.remove({ origins: [`${apiOrigin}/*`] });
  await chrome.storage.local.remove(["apiOrigin", "apiKey", "accountId"]);
  $("apiOrigin").value = "";
  $("apiKey").value = "";
  $("accountId").value = "";
  $("status").textContent = "Очищено";
});

chrome.storage.local.get(["apiOrigin", "apiKey", "accountId"], (data) => {
  if (data.apiOrigin) $("apiOrigin").value = data.apiOrigin;
  if (data.apiKey) $("apiKey").value = data.apiKey;
  if (data.accountId) $("accountId").value = data.accountId;
});
