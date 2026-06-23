document.getElementById("save").addEventListener("click", () => {
  const apiUrl = document.getElementById("apiUrl").value;
  const apiKey = document.getElementById("apiKey").value;
  chrome.storage.sync.set({ apiUrl, apiKey }, () => {
    document.getElementById("status").textContent = "Saved!";
  });
});

chrome.storage.sync.get(["apiUrl", "apiKey"], (data) => {
  if (data.apiUrl) document.getElementById("apiUrl").value = data.apiUrl;
  if (data.apiKey) document.getElementById("apiKey").value = data.apiKey;
});
