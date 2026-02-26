const chat = document.getElementById("chat");
const input = document.getElementById("input");

const sendBtn = document.getElementById("send");
const sendLabel = document.getElementById("sendLabel");
const sendSpinner = document.getElementById("sendSpinner");

const serverUrlEl = document.getElementById("serverUrl");
const tempEl = document.getElementById("temp");
const tempVal = document.getElementById("tempVal");
const maxTokEl = document.getElementById("maxTok");
const saveBtn = document.getElementById("save");

const statusPill = document.getElementById("statusPill");
const welcome = document.getElementById("welcome");

const settings = document.getElementById("settings");
const toggleSettingsBtn = document.getElementById("toggleSettings");

const errorBanner = document.getElementById("errorBanner");
const errorText = document.getElementById("errorText");
const dismissError = document.getElementById("dismissError");

// -------- UX helpers --------
function autoGrow(el){
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 96) + "px";
}
input.addEventListener("input", () => autoGrow(input));

function setStatus(ok) {
  statusPill.textContent = ok ? "Connected" : "Offline";
  statusPill.className = `pill ${ok ? "pill-ok" : "pill-warn"}`;
}

function showError(msg) {
  errorText.textContent = msg;
  errorBanner.classList.remove("hidden");
}

function hideError() {
  errorBanner.classList.add("hidden");
}

function setLoading(isLoading) {
  sendBtn.disabled = isLoading;
  input.disabled = isLoading;
  sendSpinner.classList.toggle("hidden", !isLoading);
  sendLabel.textContent = isLoading ? "Tenker…" : "Send";
}

function scrollToBottom() {
  chat.scrollTop = chat.scrollHeight;
}

// -------- Smalltalk --------
function isSmallTalk(userText) {
  const t = (userText || "").trim().toLowerCase();
  if (!t) return false;
  const patterns = [
    /^hei+!?$/,
    /^hallo+!?$/,
    /^heisann!?$/,
    /^yo!?$/,
    /^hey!?$/,
    /^hello!?$/,
    /^sup!?$/,
    /^hva skjer\??$/,
    /^test!?$/,
    /^er du der\??$/,
    /^kan du svare meg\??$/
  ];
  return patterns.some(rx => rx.test(t));
}

function smallTalkReply(userText) {
  const t = (userText || "").trim().toLowerCase();
  if (t.includes("kan du svare")) {
    return "Ja 😄 Jeg er her. Spør meg om f.eks. Canvas, Inspera, studentkort, parkering eller campus-info.";
  }
  return "Hei! 😄 Spør meg om noe konkret (f.eks. «Når åpner kantina?»), så svarer jeg kort og presist.";
}

function looksEmptyOrUseless(aiText) {
  const t = (aiText || "").trim();
  if (!t) return true;
  if (t.length < 6) return true;
  if (/^(svar|answer)\s*:\s*$/i.test(t)) return true;
  if (t.toLowerCase().startsWith("error:")) return true;
  return false;
}

// -------- UI messages --------
function addMsg(text, who) {
  const wrap = document.createElement("div");
  wrap.className = `message ${who === "user" ? "message-user" : "message-ai"}`;

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";

  const content = document.createElement("div");
  content.className = "message-content";
  content.textContent = (text && text.trim()) ? text.trim() : "(tomt svar)";
  bubble.appendChild(content);

  if (who === "ai") {
    const actions = document.createElement("div");
    actions.className = "message-actions";

    const copyBtn = document.createElement("button");
    copyBtn.className = "mini-btn";
    copyBtn.textContent = "Kopier";
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText((text || "").trim());
        copyBtn.textContent = "Kopiert!";
        setTimeout(() => (copyBtn.textContent = "Kopier"), 900);
      } catch {
        copyBtn.textContent = "Feil";
        setTimeout(() => (copyBtn.textContent = "Kopier"), 900);
      }
    });

    actions.appendChild(copyBtn);
    bubble.appendChild(actions);
  }

  wrap.appendChild(bubble);
  chat.appendChild(wrap);

  if (welcome) welcome.style.display = "none";
  scrollToBottom();
}

function addThinkingMsg() {
  const wrap = document.createElement("div");
  wrap.className = "message message-ai";
  wrap.id = "thinkingMsg";

  const bubble = document.createElement("div");
  bubble.className = "message-bubble";
  bubble.textContent = "Tenker…";

  wrap.appendChild(bubble);
  chat.appendChild(wrap);
  scrollToBottom();
}

function removeThinkingMsg() {
  const el = document.getElementById("thinkingMsg");
  if (el) el.remove();
}

// -------- Settings --------
async function loadSettings() {
  const s = await chrome.storage.local.get({
    serverUrl: "http://127.0.0.1:8000",
    temperature: 0.3,
    maxNewTokens: 180,
    settingsOpen: false
  });

  serverUrlEl.value = s.serverUrl;
  tempEl.value = s.temperature;
  tempVal.textContent = String(s.temperature);
  maxTokEl.value = s.maxNewTokens;

  settings.classList.toggle("hidden", !s.settingsOpen);
}

async function saveSettings() {
  await chrome.storage.local.set({
    serverUrl: serverUrlEl.value.trim(),
    temperature: Number(tempEl.value),
    maxNewTokens: Number(maxTokEl.value)
  });
  await ping();
}

async function setSettingsOpen(open) {
  await chrome.storage.local.set({ settingsOpen: open });
}

// -------- Network --------
async function ping() {
  const base = serverUrlEl.value.trim();
  try {
    const r = await fetch(`${base}/health`);
    setStatus(r.ok);
    if (!r.ok) showError("Server svarer ikke riktig. Sjekk /health.");
    else hideError();
  } catch {
    setStatus(false);
    showError("Fant ikke server. Har du startet uvicorn + Ollama?");
  }
}

async function askLocal(message) {
  const base = serverUrlEl.value.trim();
  const temperature = Number(tempEl.value);
  const maxNewTokens = Number(maxTokEl.value);

  const r = await fetch(`${base}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // ✅ show_sources: false (default) – kilder skjules
    body: JSON.stringify({ message, temperature, max_new_tokens: maxNewTokens })
  });

  if (!r.ok) {
    const txt = await r.text().catch(() => "");
    throw new Error(`Server error ${r.status}: ${txt}`.slice(0, 300));
  }

  const data = await r.json().catch(() => ({}));
  return data.reply || "";
}

// -------- Send flow --------
async function send() {
  const text = input.value.trim();
  if (!text) return;

  hideError();
  input.value = "";
  input.style.height = "auto";

  addMsg(text, "user");

  if (isSmallTalk(text)) {
    addMsg(smallTalkReply(text), "ai");
    setStatus(true);
    input.focus();
    return;
  }

  setLoading(true);
  addThinkingMsg();

  try {
    const reply = await askLocal(text);
    removeThinkingMsg();

    if (looksEmptyOrUseless(reply)) {
      addMsg("Jeg fant ikke nok info til å svare. Prøv å spørre mer konkret.", "ai");
    } else {
      addMsg(reply, "ai");
    }

    setStatus(true);
  } catch (e) {
    removeThinkingMsg();
    addMsg(`Jeg fikk en feil: ${e.message}`, "ai");
    setStatus(false);
    showError("Kunne ikke nå serveren. Start uvicorn og Ollama.");
  } finally {
    setLoading(false);
    input.focus();
  }
}

// -------- Events --------
tempEl.addEventListener("input", () => (tempVal.textContent = tempEl.value));
saveBtn.addEventListener("click", saveSettings);

sendBtn.addEventListener("click", send);
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
});

document.querySelectorAll(".chip").forEach((btn) => {
  btn.addEventListener("click", () => {
    input.value = btn.dataset.q || "";
    autoGrow(input);
    input.focus();
  });
});

toggleSettingsBtn.addEventListener("click", async () => {
  const open = settings.classList.toggle("hidden") === false;
  await setSettingsOpen(open);
});

dismissError.addEventListener("click", hideError);

(async function init() {
  await loadSettings();
  await ping();
})();