(() => {
  if (window.__CC_LOCAL_WIDGET__) return;
  window.__CC_LOCAL_WIDGET__ = true;

  const state = {
    ready: false,
    deadContext: false,
  };

  function markContextDead() {
    state.deadContext = true;
    setStatus(false, "Reload siden");
    addMsg(
      "Extension ble reloadet/oppdatert. Refresh denne nettsiden (Cmd+R), så fungerer widgeten igjen.",
      "ai"
    );
  }

  // ---- UI ----
  const btn = document.createElement("button");
  btn.className = "cc-chat-button";
  btn.title = "CampusConnect";

  const win = document.createElement("div");
  win.className = "cc-chat-window cc-hidden";
  win.innerHTML = `
    <div class="cc-header">
      <div class="cc-head-left">
        <div class="cc-head-title">CampusConnect</div>
        <div class="cc-head-sub">Personvern-først • Lokal server</div>
      </div>
      <div class="cc-head-right">
        <span class="cc-status cc-status-off" id="ccStatus">Offline</span>
        <button class="cc-close" aria-label="Close">×</button>
      </div>
    </div>

    <div class="cc-body" id="ccBody">
      <div class="cc-row cc-ai">
        <div class="cc-bubble">
          Hei! Jeg er CampusConnect 😄<br/>
          Spør meg om studier, tjenester og praktisk info ved Universitetet i Innlandet.
        </div>
      </div>
    </div>

    <div class="cc-footer">
      <textarea class="cc-input" rows="2" placeholder="Skriv et spørsmål…"></textarea>
      <button class="cc-send">Send</button>
      <div class="cc-hint">Enter = send • Shift+Enter = ny linje</div>
    </div>
  `;

  document.documentElement.appendChild(btn);
  document.documentElement.appendChild(win);

  const closeBtn = win.querySelector(".cc-close");
  const bodyEl = win.querySelector("#ccBody");
  const inputEl = win.querySelector(".cc-input");
  const sendBtn = win.querySelector(".cc-send");
  const statusEl = win.querySelector("#ccStatus");

  function setStatus(ok, textOverride = null) {
    statusEl.textContent = textOverride ? textOverride : (ok ? "Klar" : "Offline");
    statusEl.classList.remove("cc-status-ok", "cc-status-off");
    statusEl.classList.add(ok ? "cc-status-ok" : "cc-status-off");
  }

  function addMsg(text, who) {
    const row = document.createElement("div");
    row.className = `cc-row ${who === "user" ? "cc-user" : "cc-ai"}`;

    const bubble = document.createElement("div");
    bubble.className = "cc-bubble";
    bubble.textContent = text || "(tomt svar)";

    row.appendChild(bubble);
    bodyEl.appendChild(row);
    bodyEl.scrollTop = bodyEl.scrollHeight;
  }

  function isSmallTalk(userText) {
    const t = (userText || "").trim().toLowerCase();
    const patterns = [
      /^hei+!?$/,
      /^hallo+!?$/,
      /^heisann!?$/,
      /^yo!?$/,
      /^hey!?$/,
      /^hello!?$/,
      /^test!?$/,
      /^er du der\??$/,
      /^kan du svare meg\??$/,
    ];
    return patterns.some((rx) => rx.test(t));
  }

  function smallTalkReply(userText) {
    const t = (userText || "").trim().toLowerCase();
    if (t.includes("kan du svare")) {
      return "Ja 😄 Spør meg om f.eks. Canvas, Inspera, SINN, parkering eller studier.";
    }
    return "Hei! 😄 Spør meg om noe konkret (Canvas/Inspera/SINN/studier), så svarer jeg kort og presist.";
  }

  // ---- Background relay (fixes CORS loopback block) ----
  function bgHealth() {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "HEALTH" }, (resp) => resolve(resp));
    });
  }

  function bgChat(message) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: "CHAT", message }, (resp) => resolve(resp));
    });
  }

  async function ping() {
    if (state.deadContext) return false;
    try {
      const resp = await bgHealth();
      const ok = !!resp?.ok;
      setStatus(ok);
      return ok;
    } catch {
      setStatus(false);
      return false;
    }
  }

  async function send() {
    const text = inputEl.value.trim();
    if (!text) return;

    inputEl.value = "";
    addMsg(text, "user");

    if (state.deadContext) {
      addMsg("Extension-kontekst er reloadet. Refresh siden (Cmd+R).", "ai");
      return;
    }

    if (isSmallTalk(text)) {
      addMsg(smallTalkReply(text), "ai");
      return;
    }

    sendBtn.disabled = true;

    const ok = await ping();
    if (!ok) {
      addMsg("Jeg får ikke kontakt med serveren. Start uvicorn + Ollama, og prøv igjen.", "ai");
      sendBtn.disabled = false;
      inputEl.focus();
      return;
    }

    try {
      const resp = await bgChat(text);
      if (!resp?.ok) {
        addMsg(`Jeg fikk en feil: ${resp?.error || "ukjent feil"}`, "ai");
        setStatus(false);
      } else {
        const reply = resp?.data?.reply || "";
        if (!reply || reply.trim().length < 6) {
          addMsg("Jeg fikk ikke nok info til å svare. Prøv et mer konkret spørsmål.", "ai");
        } else {
          // ✅ Sources are hidden by server now, so just show reply
          addMsg(reply, "ai");
        }
        setStatus(true);
      }
    } catch (e) {
      const msg = String(e?.message || "");
      if (msg.toLowerCase().includes("extension context invalidated")) {
        markContextDead();
      } else {
        addMsg("Jeg fikk en feil ved henting av svar. Sjekk at serveren kjører.", "ai");
      }
      setStatus(false);
    } finally {
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  // ---- Events ----
  btn.addEventListener("click", async () => {
    win.classList.toggle("cc-hidden");
    if (!win.classList.contains("cc-hidden")) {
      await ping();
      inputEl.focus();
    }
  });

  closeBtn.addEventListener("click", () => win.classList.add("cc-hidden"));
  sendBtn.addEventListener("click", send);

  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  // ---- INIT ----
  (async function init() {
    try {
      btn.style.backgroundImage = `url(${chrome.runtime.getURL("assets/Owl-logo.png")})`;
      state.ready = true;
      await ping();
    } catch (e) {
      markContextDead();
    }
  })();
})();