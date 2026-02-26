chrome.runtime.onInstalled.addListener(async () => {
  const defaults = {
    serverUrl: "http://127.0.0.1:8000",
    temperature: 0.3,
    maxNewTokens: 180,
    uiMode: "both" // popup | widget | both
  };
  const existing = await chrome.storage.local.get(Object.keys(defaults));
  await chrome.storage.local.set({ ...defaults, ...existing });
});

async function getSettings() {
  return await chrome.storage.local.get({
    serverUrl: "http://127.0.0.1:8000",
    temperature: 0.3,
    maxNewTokens: 180,
    uiMode: "both"
  });
}

async function postJson(url, bodyObj) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(bodyObj)
  });

  if (!r.ok) {
    const txt = await r.text().catch(() => "");
    throw new Error(`Server error ${r.status}: ${txt}`);
  }
  return await r.json();
}

async function getHealth(url) {
  const r = await fetch(url, { method: "GET" });
  if (!r.ok) throw new Error(`Health not ok: ${r.status}`);
  return await r.json().catch(() => ({}));
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg?.type === "GET_SETTINGS") {
        const s = await chrome.storage.local.get(null);
        sendResponse(s);
        return;
      }

      if (msg?.type === "SET_SETTINGS") {
        await chrome.storage.local.set(msg.payload || {});
        sendResponse({ ok: true });
        return;
      }

      if (msg?.type === "HEALTH") {
        const s = await getSettings();
        const base = (msg.baseUrl || s.serverUrl || "").trim();
        const data = await getHealth(`${base}/health`);
        sendResponse({ ok: true, data });
        return;
      }

      if (msg?.type === "CHAT") {
        const s = await getSettings();
        const base = (msg.baseUrl || s.serverUrl || "").trim();
        const message = (msg.message || "").trim();
        const temperature = typeof msg.temperature === "number" ? msg.temperature : s.temperature;
        const max_new_tokens = typeof msg.maxNewTokens === "number" ? msg.maxNewTokens : s.maxNewTokens;

        const data = await postJson(`${base}/chat`, {
          message,
          temperature,
          max_new_tokens,
          // ✅ Always hide sources for users
          show_sources: false
        });

        sendResponse({ ok: true, data });
        return;
      }

      sendResponse({ ok: false, error: "Unknown message type" });
    } catch (e) {
      sendResponse({ ok: false, error: String(e?.message || e) });
    }
  })();

  return true;
});